"""Bracket-order execution: entry, a stop, and a target, sized by risk.

This is a different mechanism from the rest of the project, which holds target weights
and rebalances. Here each position carries a stop and a take-profit, and the bar's own
high and low decide which one is reached.

The decision that matters most: when a single bar touches BOTH the stop and the target,
daily OHLC cannot say which came first. This engine always assumes the STOP. Assuming
the target instead is the classic way a bracket backtest invents money.
"""
import numpy as np
import pandas as pd
import pytest
from referee import brackets, costs, venues

V = venues.get("binance")


def _bars(o, h, l, c, qv=1e9, start="2021-01-01"):
    idx = pd.date_range(start, periods=len(o), freq="1D", tz="UTC")
    return {"A": pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                               "volume": 1e6, "quote_volume": qv}, index=idx)}


def _sig(idx, at, stop, target, sym="A"):
    """An entry signal on bar `at`, to be filled at the open of the NEXT bar."""
    s = pd.DataFrame(index=idx, columns=pd.MultiIndex.from_product([[sym], ["enter", "stop", "target"]]),
                     dtype=float)
    s[(sym, "enter")] = 0.0
    s.iloc[at, s.columns.get_loc((sym, "enter"))] = 1.0
    s.iloc[at, s.columns.get_loc((sym, "stop"))] = stop
    s.iloc[at, s.columns.get_loc((sym, "target"))] = target
    return s


# ---- entry timing ---------------------------------------------------------
def test_entry_fills_at_the_next_bar_open_never_the_signal_bar():
    b = _bars([100]*10, [101]*10, [99]*10, [100]*10)
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 3, stop=95.0, target=110.0), venue=V)
    assert len(r.trades) >= 1
    first = r.trades.iloc[0]
    assert first["time"] == idx[4], "entry must be the bar AFTER the signal"
    assert first["ref_open"] == 100.0 and first["fill"] > 100.0


# ---- the stop and the target ----------------------------------------------
def test_stop_is_hit_and_fills_worse_than_the_stop_price():
    o = [100]*6 + [100]*4
    lo = [99]*6 + [90]*4          # bar 6 onwards trades down to 90
    b = _bars(o, [101]*10, lo, [100]*10)
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 0, stop=95.0, target=200.0), venue=V)
    exits = r.trades[r.trades["reason"] == "stop"]
    assert len(exits) == 1
    assert exits.iloc[0]["fill"] < 95.0, "a triggered stop becomes a market order and slips"


def test_target_is_hit_and_fills_at_the_target():
    hi = [101]*46 + [130]*4
    b = _bars([100]*50, hi, [99]*50, [100]*50)
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 40, stop=50.0, target=120.0), start_equity=50_000.0, venue=V)
    exits = r.trades[r.trades["reason"] == "target"]
    assert len(exits) == 1
    assert exits.iloc[0]["fill"] == pytest.approx(120.0)


def test_when_a_bar_touches_both_the_stop_is_assumed():
    """The pessimistic rule. Daily OHLC cannot order the two touches."""
    b = _bars([100]*10, [101]*5 + [200]*5, [99]*5 + [50]*5, [100]*10)
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 0, stop=95.0, target=120.0), venue=V)
    ex = r.trades[r.trades["reason"].isin(["stop", "target"])]
    assert len(ex) == 1
    assert ex.iloc[0]["reason"] == "stop", "both touched: must assume the stop"


def test_the_stop_can_trigger_on_the_entry_bar_itself():
    b = _bars([100]*10, [101]*10, [99]*4 + [80] + [99]*5, [100]*10)
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 3, stop=95.0, target=200.0), venue=V)
    assert (r.trades["reason"] == "stop").any()
    assert r.trades[r.trades["reason"] == "stop"].iloc[0]["time"] == idx[4]


# ---- risk-based sizing ----------------------------------------------------
def test_size_is_set_by_the_distance_to_the_stop():
    """1% of a 10,000 account risked, with the stop 10 below a 100 entry, puts about
    100 at risk. The signal is placed late enough that the coin has a liquidity
    history, otherwise the engine correctly charges its worst-case spread."""
    b = _bars([100]*60, [101]*60, [99]*60, [100]*60)
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 40, stop=90.0, target=200.0),
                         start_equity=10_000.0, risk_frac=0.01, venue=V)
    entry = r.trades.iloc[0]
    risked = entry["units"] * (entry["fill"] - 90.0)
    assert risked == pytest.approx(100.0, rel=0.05), f"risked {risked}"


def test_a_coin_with_no_liquidity_history_is_charged_the_worst_case_spread():
    """Conservative by design: before 10 bars of volume history the spread model has
    nothing to go on and assumes the worst."""
    b = _bars([100]*60, [101]*60, [99]*60, [100]*60)
    idx = b["A"].index
    early = brackets.execute(b, _sig(idx, 0, stop=90.0, target=200.0), start_equity=10_000.0, venue=V)
    late = brackets.execute(b, _sig(idx, 40, stop=90.0, target=200.0), start_equity=10_000.0, venue=V)
    assert early.trades.iloc[0]["fill"] > late.trades.iloc[0]["fill"]


def test_one_percent_risk_on_a_small_account_is_below_the_minimum_trade():
    """A real constraint on $1,000: risking 1% with a stop 10% away asks for a $100
    position, and with a wider stop it falls under the exchange minimum and is skipped.
    Risk-based sizing and a tiny account fight each other."""
    b = _bars([100]*60, [101]*60, [99]*60, [100]*60)
    idx = b["A"].index
    wide = brackets.execute(b, _sig(idx, 40, stop=50.0, target=200.0),
                            start_equity=1000.0, risk_frac=0.01, venue=V)
    assert len(wide.trades) == 0, "a $20 position should be refused, not silently placed"


def test_a_wider_stop_means_a_smaller_position():
    b = _bars([100]*10, [101]*10, [99]*10, [100]*10)
    idx = b["A"].index
    tight = brackets.execute(b, _sig(idx, 0, stop=99.0, target=200.0), start_equity=10_000.0, risk_frac=0.01, venue=V)
    wide = brackets.execute(b, _sig(idx, 0, stop=80.0, target=200.0), start_equity=10_000.0, risk_frac=0.01, venue=V)
    assert tight.trades.iloc[0]["units"] > wide.trades.iloc[0]["units"]


def test_position_is_capped_by_the_exposure_limit_however_tight_the_stop():
    b = _bars([100]*10, [101]*10, [99]*10, [100]*10)
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 0, stop=99.99, target=200.0),
                         start_equity=1000.0, risk_frac=0.01, venue=V)
    assert r.exposure.max() <= 1.0 + 1e-9
    assert r.weights.max().max() <= brackets.MAX_POSITION_FRAC + 1e-9


# ---- housekeeping ---------------------------------------------------------
def test_only_one_position_per_symbol():
    b = _bars([100]*60, [101]*60, [99]*60, [100]*60)
    idx = b["A"].index
    s = _sig(idx, 40, stop=50.0, target=500.0)
    for k in (42, 44, 46):
        s.iloc[k, s.columns.get_loc(("A", "enter"))] = 1.0
        s.iloc[k, s.columns.get_loc(("A", "stop"))] = 50.0
        s.iloc[k, s.columns.get_loc(("A", "target"))] = 500.0
    r = brackets.execute(b, s, start_equity=50_000.0, venue=V)
    assert len(r.trades[r.trades["reason"] == "entry"]) == 1, "re-entered while already long"


def test_deposits_are_tracked_and_never_counted_as_profit():
    b = _bars([100]*400, [101]*400, [99]*400, [100]*400)
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 40, stop=50.0, target=500.0), start_equity=50_000.0,
                         monthly_deposit=100.0, venue=V)
    assert r.contributed.iloc[-1] > 1000.0
    assert r.profit.iloc[-1] == pytest.approx(r.equity.iloc[-1] - r.contributed.iloc[-1], abs=1e-6)


def test_gross_never_falls_below_net():
    b = _bars([100]*60, [103]*60, [95]*60, [100 + (i % 5) for i in range(60)])
    idx = b["A"].index
    s = _sig(idx, 0, stop=96.0, target=104.0)
    r = brackets.execute(b, s, venue=V)
    assert (r.equity <= r.equity_gross * (1 + 1e-9)).all()


def test_a_coin_outside_the_universe_is_never_entered():
    b = _bars([100]*10, [101]*10, [99]*10, [100]*10)
    idx = b["A"].index
    uni = pd.DataFrame(False, index=idx, columns=["A"])
    r = brackets.execute(b, _sig(idx, 3, stop=95.0, target=110.0), universe=uni, venue=V)
    assert len(r.trades) == 0
