import numpy as np
import pandas as pd
import pytest
from referee import validate


def test_deflated_sharpe_penalises_many_trials():
    r = np.random.default_rng(0).normal(0.001, 0.01, 1000)
    one = validate.deflated_sharpe(r, n_trials=1, periods_per_year=365)
    many = validate.deflated_sharpe(r, n_trials=2000, periods_per_year=365)
    assert many["psr"] < one["psr"]
    assert many["expected_max_sharpe"] > one["expected_max_sharpe"]


def test_min_trade_gate():
    assert validate.passes_min_trades(n_trades=99) is False
    assert validate.passes_min_trades(n_trades=100) is True


def _daily_idx(n):
    return pd.date_range("2021-01-01", periods=n, freq="1D", tz="UTC")


def test_tripwire_on_sharpe_above_3():
    r = pd.Series(np.full(400, 0.01), index=_daily_idx(400)); r.iloc[::7] = 0.009
    trip = validate.tripwire(r, periods_per_year=365)
    assert trip.tripped and "sharpe" in trip.reason


def test_tripwire_sharpe_exempt_when_benchmark_did_the_same():
    """A bull run is not a bug: BTC itself posted a 1y Sharpe > 3 in 2020-21."""
    b = pd.Series(np.full(400, 0.01), index=_daily_idx(400)); b.iloc[::7] = 0.009
    r = 0.9 * b
    trip = validate.tripwire(r, periods_per_year=365, benchmark_returns=b)
    assert "sharpe" not in trip.reason


def test_tripwire_on_net_level_exceeding_gross_level():
    r = pd.Series(np.random.default_rng(0).normal(0.0005, 0.01, 400), index=_daily_idx(400))
    trip = validate.tripwire(r, periods_per_year=365, level_violations=3)
    assert trip.tripped and "net>gross" in trip.reason


def test_tripwire_when_strategy_beats_every_asset_on_a_bar():
    """Long-only spot cannot earn more on a bar than the best asset did using open/close."""
    idx = _daily_idx(400)
    r = pd.Series(np.zeros(400), index=idx); bound = pd.Series(np.full(400, 0.02), index=idx)
    r.iloc[50] = 0.03
    trip = validate.tripwire(r, periods_per_year=365, asset_bound=bound)
    assert trip.tripped and "asset" in trip.reason
    r.iloc[50] = 0.02
    assert "asset" not in validate.tripwire(r, periods_per_year=365, asset_bound=bound).reason


def test_tripwire_single_day_bound_is_applied_on_daily_resample():
    idx = pd.date_range("2021-01-01", periods=48, freq="1h", tz="UTC")
    r = pd.Series(np.zeros(48), index=idx); r.iloc[3:6] = 0.06       # three 6% hours = 19% day
    trip = validate.tripwire(r, periods_per_year=8760)
    assert trip.tripped and "single" in trip.reason
    r.iloc[3:6] = 0.04                                                   # 12.5% day: fine
    assert "single" not in validate.tripwire(r, periods_per_year=8760).reason


def test_tripwire_on_ten_straight_wins():
    r = pd.Series(np.random.default_rng(0).normal(0, 0.01, 400), index=_daily_idx(400)); r.iloc[100:110] = 0.001
    trip = validate.tripwire(r, periods_per_year=365)
    assert trip.tripped and "streak" in trip.reason


def test_tripwire_silent_on_ordinary_returns():
    r = pd.Series(np.random.default_rng(3).normal(0.0002, 0.02, 800), index=_daily_idx(800))
    assert not validate.tripwire(r, periods_per_year=365).tripped


def test_single_regime_label():
    idx = pd.date_range("2021-01-01", periods=400, tz="UTC")
    ret = pd.Series(0.0, index=idx); ret.iloc[:100] = 0.01
    lab = pd.DataFrame({"trend": ["bull"] * 100 + ["bear"] * 300, "vol": "mid", "chop": False}, index=idx)
    seg = validate.segment_by_regime(ret, lab)
    assert seg["single_regime"] is True
    assert seg["dominant"] == "bull"


def test_walk_forward_windows_do_not_overlap_in_test():
    idx = pd.date_range("2018-01-01", periods=2000, tz="UTC")
    ws = validate.windows(idx, train_days=365, test_days=91, warmup_days=200)
    for a, b in zip(ws, ws[1:]):
        assert a[3] < b[2]
        assert b[2] == a[3] + pd.Timedelta(days=1)
        assert a[1] < a[2]


def test_causality_battery_catches_a_leaky_rule(bars):
    close = pd.concat({s: d["close"] for s, d in bars.items()}, axis=1)
    def leaky(c):        # uses tomorrow's close
        on = (c.shift(-1) > c).astype(float)
        return on.div(on.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    def honest(c):
        on = (c > c.rolling(20).mean()).astype(float)
        return on.div(on.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    assert validate.causality_battery(honest, close).passed
    assert not validate.causality_battery(leaky, close).passed


def test_single_day_and_streak_exempt_when_benchmark_did_the_same():
    """ETH has had +20% days and BTC 11-day winning streaks. A strategy that merely
    held them is not a bug. Exempt when the benchmark's own daily returns show it."""
    idx = _daily_idx(400)
    b = pd.Series(np.random.default_rng(2).normal(0, 0.01, 400), index=idx)
    b.iloc[50] = 0.20; b.iloc[100:112] = 0.005                          # a +20% day and a 12-day streak
    r = 0.9 * b
    trip = validate.tripwire(r, periods_per_year=365, benchmark_returns=b)
    assert "single" not in trip.reason and "streak" not in trip.reason
    r2 = r.copy(); r2.iloc[300] = 0.19                                    # a big day the benchmark did NOT have
    assert "single" in validate.tripwire(r2, periods_per_year=365, benchmark_returns=b).reason
    r3 = r.copy(); r3.iloc[200:211] = 0.002                               # a streak the benchmark did NOT have
    assert "streak" in validate.tripwire(r3, periods_per_year=365, benchmark_returns=b).reason


def test_exemptions_accept_any_of_several_benchmarks():
    """benchmark_returns may be a DataFrame (BTC, ETH, 50/50): exempt if ANY column did it."""
    idx = _daily_idx(400)
    btc = pd.Series(np.random.default_rng(4).normal(0, 0.01, 400), index=idx)
    eth = btc.copy(); eth.iloc[100:112] = 0.005; eth.iloc[50] = 0.2      # only ETH had the streak and the big day
    bench = pd.DataFrame({"BTC": btc, "ETH": eth, "5050": (btc + eth) / 2})
    r = 0.9 * eth
    trip = validate.tripwire(r, periods_per_year=365, benchmark_returns=bench)
    assert "streak" not in trip.reason and "single" not in trip.reason
    assert "streak" in validate.tripwire(r, periods_per_year=365, benchmark_returns=btc).reason


def test_benchmark_daily_returns_covers_majors_and_a_basket(bars):
    b = validate.benchmark_daily_returns(bars)
    assert list(b.columns) == ["BTCUSDT", "ETHUSDT", "basket"]


def test_regime_labels_and_benchmarks_work_without_bitcoin_present():
    """The referee must not assume BTCUSDT is in the frame; it falls back to an
    equal-weight basket of whatever is there."""
    from tests.conftest import synth_bars
    b = synth_bars(n=500, seed=9, freq="1D", syms=("AAAUSDT", "BBBUSDT"))
    lab = validate._daily_labels(b, validate._close(b).index)
    assert set(lab.columns) == {"trend", "vol", "chop"}
    bench = validate.benchmark_daily_returns(b)
    assert len(bench.columns) >= 1 and len(bench) > 100


def test_single_day_rule_is_exempt_when_a_held_asset_moved_that_much():
    """A concentrated portfolio of volatile altcoins can legitimately gain 20% in a
    day, because an individual coin did. 'Implausible' must mean impossible, not
    merely large: the exemption is what the best available asset actually did."""
    idx = _daily_idx(400)
    r = pd.Series(np.zeros(400), index=idx); r.iloc[50] = 0.22
    bound = pd.Series(np.full(400, 0.01), index=idx); bound.iloc[50] = 0.40   # some coin did +40%
    trip = validate.tripwire(r, periods_per_year=365, asset_bound=bound)
    assert "single" not in trip.reason
    assert "asset" not in trip.reason
    # the same 22% day when nothing moved more than 5% IS implausible
    tight = pd.Series(np.full(400, 0.01), index=idx); tight.iloc[50] = 0.05
    bad = validate.tripwire(r, periods_per_year=365, asset_bound=tight)
    assert bad.tripped and ("asset" in bad.reason or "single" in bad.reason)
