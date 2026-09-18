"""Second audit, 2026-09-17, before the forex run. Each test fails before its fix.

1. The bracket engine sized a new entry using the fill bar's CLOSE to value existing
   positions, then filled at that bar's OPEN. Using a bar's close to size an order that
   fills at its open is look-ahead, small in effect and wrong in principle.
2. Forex entries were charged the DAY'S MEAN spread, but entries fill at the open, and
   the spread at the open (Sunday evening, Asian session) is much wider than the daily
   mean. Optimistic in exactly the direction that flatters a strategy.
3. Forex days were cut at UTC midnight. The market's day runs from 17:00 New York, which
   is 22:00 UTC. A midnight cut produces two-hour "days" at the Sunday open whose open
   price is a thin illiquid print, and it was being used as a fill price.
4. The bracket engine could only go long. In forex every position is long one currency
   and short another, so selling EURUSD is exactly as natural as buying it, and the
   tutorial's strategy was only ever half-tested.
5. Risk-based sizing at 1:1 leverage is throttled by the position cap on nearly every
   forex trade, so "1% risk" silently became about 0.25%. Not a bug, but it must be
   visible in the results rather than hidden.
"""
import numpy as np
import pandas as pd
import pytest
from referee import brackets, costmodels, forex, venues

V = venues.get("binance")


def _bars(o, h, l, c, qv=1e9, spread=None, start="2021-01-01"):
    idx = pd.date_range(start, periods=len(o), freq="1D", tz="UTC")
    d = {"open": o, "high": h, "low": l, "close": c, "volume": 1e6, "quote_volume": qv}
    if spread is not None:
        d["half_spread"] = spread; d["open_half_spread"] = spread
    return {"A": pd.DataFrame(d, index=idx)}


def _sig(idx, at, stop, target, side=+1, sym="A"):
    s = pd.DataFrame(index=idx, columns=pd.MultiIndex.from_product([[sym], ["enter", "stop", "target"]]),
                     dtype=float)
    s[(sym, "enter")] = 0.0
    s.iloc[at, s.columns.get_loc((sym, "enter"))] = float(side)
    s.iloc[at, s.columns.get_loc((sym, "stop"))] = stop
    s.iloc[at, s.columns.get_loc((sym, "target"))] = target
    return s


# ---- 1. sizing must not see the fill bar's close ---------------------------
def test_entry_size_does_not_depend_on_the_fill_bars_close():
    """Two worlds identical up to the fill bar's OPEN, differing only in that bar's
    close. The entry size must be identical."""
    n = 60
    base = _bars([100.0] * n, [101.0] * n, [99.0] * n, [100.0] * n)
    idx = base["A"].index
    sig = _sig(idx, 40, 95.0, 110.0)
    # an existing position so that equity depends on how it is valued
    sig.iloc[10, sig.columns.get_loc(("A", "enter"))] = 1.0
    sig.iloc[10, sig.columns.get_loc(("A", "stop"))] = 50.0
    sig.iloc[10, sig.columns.get_loc(("A", "target"))] = 500.0
    alt = {"A": base["A"].copy()}
    alt["A"].iloc[41, alt["A"].columns.get_loc("close")] = 130.0     # only the fill bar's close differs
    alt["A"].iloc[41, alt["A"].columns.get_loc("high")] = 131.0
    # add a second symbol so there is something to size on bar 41
    for b in (base, alt):
        b["B"] = b["A"].copy()
        b["B"]["close"] = 100.0; b["B"]["high"] = 101.0
    sig2 = pd.concat([sig, _sig(idx, 40, 95.0, 110.0, sym="B")], axis=1).sort_index(axis=1)
    r1 = brackets.execute(base, sig2, start_equity=10_000.0, venue=V, kill_switch=False)
    r2 = brackets.execute(alt, sig2, start_equity=10_000.0, venue=V, kill_switch=False)
    e1 = r1.trades[(r1.trades.symbol == "B") & (r1.trades.reason == "entry")].iloc[0]
    e2 = r2.trades[(r2.trades.symbol == "B") & (r2.trades.reason == "entry")].iloc[0]
    assert e1["units"] == pytest.approx(e2["units"]), "size changed with the fill bar's close: look-ahead"


# ---- 2. entries pay the open's spread, not the day's average ---------------
def test_entries_are_charged_the_spread_at_the_open():
    n = 60
    b = _bars([1.08] * n, [1.09] * n, [1.07] * n, [1.08] * n, spread=2e-5)
    b["A"]["open_half_spread"] = 2e-4                # ten times wider at the open
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 40, 1.05, 1.12), start_equity=10_000.0,
                         cost_model=costmodels.ForexCosts(), kill_switch=False)
    entry = r.trades[r.trades.reason == "entry"].iloc[0]
    from referee import fxcosts
    assert entry["fill"] == pytest.approx(fxcosts.fill_price(1.08, +1, 2e-4)), "used the daily mean, not the open"


def test_to_daily_records_the_opening_hours_spread_separately():
    idx = pd.date_range("2024-06-03 22:00", periods=24, freq="1h", tz="UTC")
    hs = np.full(24, 1e-5); hs[0] = 8e-5                # wide at the open, tight after
    h = pd.DataFrame({"open": 1.08, "high": 1.081, "low": 1.079, "close": 1.08,
                      "volume": 100.0, "half_spread": hs}, index=idx)
    d = forex.to_daily(h)
    assert d["open_half_spread"].iloc[0] == pytest.approx(8e-5)
    assert d["half_spread"].iloc[0] < d["open_half_spread"].iloc[0]


# ---- 3. the forex day starts at 22:00 UTC -----------------------------------
def test_forex_days_are_cut_at_the_new_york_close_not_utc_midnight():
    idx = pd.date_range("2024-06-02 22:00", periods=48, freq="1h", tz="UTC")    # Sunday 22:00 open
    h = pd.DataFrame({"open": 1.08, "high": 1.081, "low": 1.079, "close": 1.08,
                      "volume": 100.0, "half_spread": 1e-5}, index=idx)
    d = forex.to_daily(h)
    assert len(d) == 2, f"expected 2 full days, got {len(d)}"
    assert (d["n_bars"] == 24).all(), "a midnight cut would leave a two-hour stub"
    assert d.index[0] == idx[0]


def test_a_stub_day_shorter_than_half_a_session_is_not_a_bar():
    idx = pd.date_range("2024-06-02 22:00", periods=30, freq="1h", tz="UTC")
    h = pd.DataFrame({"open": 1.08, "high": 1.081, "low": 1.079, "close": 1.08,
                      "volume": 100.0, "half_spread": 1e-5}, index=idx)
    d = forex.to_daily(h)
    assert (d["n_bars"] >= 12).all(), "a 6-hour stub must not become a tradable daily bar"


# ---- 4. the bracket engine can go short --------------------------------------
def test_a_short_entry_is_sold_first_and_bought_back_at_the_target():
    n = 60
    o = [100.0] * 45 + [100.0] * 15
    lo = [99.0] * 45 + [85.0] * 15                     # after bar 45 it falls to the target
    b = _bars(o, [101.0] * n, lo, [100.0] * n)
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 40, stop=105.0, target=90.0, side=-1),
                         start_equity=10_000.0, venue=V, kill_switch=False)
    entry = r.trades[r.trades.reason == "entry"].iloc[0]
    assert entry["side"] == "SELL" and entry["units"] < 0
    assert entry["fill"] < entry["ref_open"], "a short entry sells below the open"
    exit_ = r.trades[r.trades.reason == "target"].iloc[0]
    assert exit_["side"] == "BUY"
    assert exit_["fill"] == pytest.approx(90.0)
    assert r.equity.iloc[-1] > 10_000.0


def test_a_short_is_stopped_when_price_rises_through_the_stop():
    n = 60
    hi = [101.0] * 45 + [120.0] * 15
    b = _bars([100.0] * n, hi, [99.0] * n, [100.0] * n)
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 40, stop=105.0, target=80.0, side=-1),
                         start_equity=10_000.0, venue=V, kill_switch=False)
    ex = r.trades[r.trades.reason == "stop"].iloc[0]
    assert ex["side"] == "BUY" and ex["fill"] > 105.0, "a short's stop is bought back worse than the stop"
    assert r.equity.iloc[-1] < 10_000.0


def test_when_both_are_touched_a_short_also_assumes_the_stop():
    n = 60
    b = _bars([100.0] * n, [101.0] * 45 + [120.0] * 15, [99.0] * 45 + [70.0] * 15, [100.0] * n)
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 40, stop=105.0, target=80.0, side=-1),
                         start_equity=10_000.0, venue=V, kill_switch=False)
    ex = r.trades[r.trades.reason.isin(["stop", "target"])].iloc[0]
    assert ex["reason"] == "stop"


def test_short_exposure_counts_toward_the_same_caps():
    n = 60
    b = _bars([100.0] * n, [101.0] * n, [99.0] * n, [100.0] * n)
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 40, stop=100.01, target=50.0, side=-1),
                         start_equity=1000.0, venue=V, kill_switch=False)
    assert r.exposure.max() <= 1.0 + 1e-9
    assert r.weights.abs().max().max() <= brackets.MAX_POSITION_FRAC + 1e-9


# ---- 5. the sizing throttle is reported, not hidden -------------------------
def test_result_reports_how_often_the_position_cap_throttled_the_risk_sizing():
    n = 60
    b = _bars([1.08] * n, [1.09] * n, [1.07] * n, [1.08] * n, spread=2e-5)
    idx = b["A"].index
    # a stop 0.5% away with 1% risk asks for 200% of equity: the cap must bind
    r = brackets.execute(b, _sig(idx, 40, 1.08 * 0.995, 1.10), start_equity=10_000.0,
                         risk_frac=0.01, cost_model=costmodels.ForexCosts(), kill_switch=False)
    assert r.n_capped >= 1
    assert r.effective_risk_frac < 0.01, "the realised risk per trade must be reported honestly"


# ---- 6. a data gap while a position is open must not poison the account ----
def test_a_nan_bar_mid_position_does_not_turn_equity_into_nan():
    """The forex panel is a UNION of dates, so a pair with a gap has NaN bars while
    others trade. If a position is open across such a bar, the engine must value it at
    the last known close, exactly as the rebalancing engine does. The first forex run
    produced equity of NaN and 964 entries with NaN size from this."""
    n = 80
    b = _bars([100.0] * n, [101.0] * n, [99.0] * n, [100.0] * n, spread=2e-5)
    b["A"].iloc[50:55] = np.nan                     # a five-day gap while long
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 40, stop=90.0, target=120.0), start_equity=10_000.0,
                         cost_model=costmodels.ForexCosts(), kill_switch=False)
    assert np.isfinite(r.equity).all(), "equity went NaN across the gap"
    assert np.isfinite(r.twr).all()
    assert r.equity.iloc[54] == pytest.approx(r.equity.iloc[49], rel=0.01), "valued at the last known close"
    assert np.isfinite(r.trades["units"]).all(), "an entry was sized from NaN equity"


def test_no_entry_is_placed_on_a_symbol_whose_bar_is_missing():
    n = 80
    b = _bars([100.0] * n, [101.0] * n, [99.0] * n, [100.0] * n, spread=2e-5)
    b["A"].iloc[41] = np.nan                        # the fill bar itself is missing
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 40, stop=90.0, target=120.0), start_equity=10_000.0,
                         cost_model=costmodels.ForexCosts(), kill_switch=False)
    assert len(r.trades) == 0
    assert np.isfinite(r.equity).all()


def test_sizing_ignores_a_symbol_with_no_open_on_the_fill_bar():
    """Two symbols; B is long and B's bar is missing on the day A is entered. A's size
    must come from finite equity, with B valued at its last close."""
    n = 80
    b = _bars([100.0] * n, [101.0] * n, [99.0] * n, [100.0] * n, spread=2e-5)
    b["B"] = b["A"].copy()
    b["B"].iloc[60:64] = np.nan
    idx = b["A"].index
    sig = pd.concat([_sig(idx, 30, 90.0, 500.0, sym="B"), _sig(idx, 60, 90.0, 120.0, sym="A")], axis=1).sort_index(axis=1)
    r = brackets.execute(b, sig, start_equity=10_000.0, cost_model=costmodels.ForexCosts(), kill_switch=False)
    a_entry = r.trades[(r.trades.symbol == "A") & (r.trades.reason == "entry")]
    assert len(a_entry) == 1 and np.isfinite(a_entry.iloc[0]["units"])
    assert np.isfinite(r.equity).all()
