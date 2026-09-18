"""One execution engine, two markets.

The bracket engine was written against the crypto cost model, where the spread is
inferred from dollar volume. Forex supplies a measured spread in the bars themselves.
Rather than fork the engine, costs become a pluggable object, and the crypto path must
behave EXACTLY as it did before so every earlier result stays valid.
"""
import numpy as np
import pandas as pd
import pytest
from referee import brackets, costmodels, costs, fxcosts, venues


def _bars(n=60, px=1.08, spread=2e-5, qv=1e9):
    idx = pd.date_range("2021-01-01", periods=n, freq="1D", tz="UTC")
    return {"A": pd.DataFrame({"open": px, "high": px * 1.01, "low": px * 0.99, "close": px,
                               "volume": 1e6, "quote_volume": qv,
                               "half_spread": spread}, index=idx)}


def _sig(idx, at, stop, target):
    s = pd.DataFrame(index=idx, columns=pd.MultiIndex.from_product([["A"], ["enter", "stop", "target"]]),
                     dtype=float)
    s[("A", "enter")] = 0.0
    s.iloc[at, s.columns.get_loc(("A", "enter"))] = 1.0
    s.iloc[at, s.columns.get_loc(("A", "stop"))] = stop
    s.iloc[at, s.columns.get_loc(("A", "target"))] = target
    return s


def test_the_crypto_model_reproduces_the_venue_functions_exactly():
    cm = costmodels.CryptoCosts(venues.get("binance"))
    got = cm.fill_price(100.0, +1, 500.0, bar_qv=1e7, median_bar_qv=1e7, median_daily_qv=1e9,
                        measured_half_spread=None)
    want = costs.fill_price(100.0, +1, 500.0, 1e7, 1e7, 1e9, venue=venues.get("binance"))
    assert got == pytest.approx(want)
    assert cm.commission(1000.0) == pytest.approx(costs.commission(1000.0, venues.get("binance")))


def test_the_forex_model_uses_the_measured_spread_and_ignores_volume():
    cm = costmodels.ForexCosts()
    a = cm.fill_price(1.08, +1, 500.0, bar_qv=1e3, median_bar_qv=1e3, median_daily_qv=1e3,
                      measured_half_spread=2e-5)
    b = cm.fill_price(1.08, +1, 500_000.0, bar_qv=1.0, median_bar_qv=1.0, median_daily_qv=1.0,
                      measured_half_spread=2e-5)
    assert a == pytest.approx(b), "a retail order does not move a major pair"
    assert a == pytest.approx(fxcosts.fill_price(1.08, +1, 2e-5))


def test_the_forex_model_refuses_to_treat_a_missing_spread_as_free():
    cm = costmodels.ForexCosts()
    got = cm.fill_price(1.08, +1, 500.0, 1e3, 1e3, 1e3, measured_half_spread=None)
    assert got > 1.08 * (1 + fxcosts.WORST_HALF_SPREAD * 0.99)


def test_forex_costs_are_far_below_crypto_costs_on_the_same_trade():
    fx = costmodels.ForexCosts()
    cr = costmodels.CryptoCosts(venues.get("okx"))
    f = fx.fill_price(100.0, +1, 500.0, 1e7, 1e7, 1e9, measured_half_spread=2e-5) - 100.0
    c = cr.fill_price(100.0, +1, 500.0, 1e7, 1e7, 1e9, measured_half_spread=None) - 100.0
    assert f < c / 3


# ---- the engine accepts either, and the crypto default is unchanged --------
def test_the_engine_default_is_still_the_crypto_model():
    b = _bars()
    idx = b["A"].index
    default = brackets.execute(b, _sig(idx, 40, 1.05, 1.12), start_equity=10_000.0, venue="binance")
    explicit = brackets.execute(b, _sig(idx, 40, 1.05, 1.12), start_equity=10_000.0,
                                cost_model=costmodels.CryptoCosts(venues.get("binance")))
    assert len(default.trades) == len(explicit.trades)
    assert default.equity.iloc[-1] == pytest.approx(explicit.equity.iloc[-1])


def test_the_engine_runs_forex_and_costs_less_than_the_crypto_path():
    b = _bars()
    idx = b["A"].index
    sig = _sig(idx, 40, 1.05, 1.12)
    fx = brackets.execute(b, sig, start_equity=10_000.0, cost_model=costmodels.ForexCosts())
    cr = brackets.execute(b, sig, start_equity=10_000.0, venue="okx")
    assert len(fx.trades) >= 1
    assert fx.total_costs < cr.total_costs


def test_financing_is_charged_for_holding_a_forex_position():
    """Unlike spot crypto, a forex position is borrowed. Holding must not be free."""
    b = _bars(n=400, spread=2e-5)
    idx = b["A"].index
    sig = _sig(idx, 40, 1.00, 5.00)              # a target that is never reached
    free = brackets.execute(b, sig, start_equity=10_000.0,
                            cost_model=costmodels.ForexCosts(financing_annual=0.0))
    charged = brackets.execute(b, sig, start_equity=10_000.0,
                               cost_model=costmodels.ForexCosts(financing_annual=0.03))
    assert charged.equity.iloc[-1] < free.equity.iloc[-1]
    assert charged.total_costs > free.total_costs


def test_the_rebalancing_engine_also_accepts_a_cost_model():
    """The seven weight-based families must run on forex too, through the same
    pluggable costs, so the crypto and forex results are comparable like for like."""
    from referee import replay
    n = 120
    idx = pd.date_range("2021-01-01", periods=n, freq="1D", tz="UTC")
    b = {"A": pd.DataFrame({"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.08 + np.linspace(0, 0.02, n),
                            "volume": 1e6, "quote_volume": 1e9, "half_spread": 2e-5,
                            "open_half_spread": 3e-5}, index=idx)}
    uni = pd.DataFrame(True, index=idx, columns=["A"])
    tgt = pd.DataFrame([0.3 if i % 10 < 5 else 0.0 for i in range(n)], index=idx, columns=["A"])
    fx = replay.execute(b, tgt, universe=uni, kill_switch=False, cost_model=costmodels.ForexCosts())
    cr = replay.execute(b, tgt, universe=uni, kill_switch=False, venue="okx")
    assert len(fx.trades) > 0
    assert fx.total_costs < cr.total_costs
    first = fx.trades.iloc[0]
    assert first["fill"] == pytest.approx(fxcosts.fill_price(1.08, +1, 3e-5)), "entries pay the OPEN spread"


def test_the_walk_forward_harness_threads_the_cost_model_through():
    """The families must be scored on forex by the SAME audited walk-forward that scored
    them on crypto, not by a copy of its selection logic living in a script."""
    from referee import validate
    from tests.conftest import synth_bars
    b = synth_bars(n=1500, seed=41, freq="1D", syms=("EURUSD", "GBPUSD", "USDJPY"))
    for s in b:
        b[s]["half_spread"] = 2e-5; b[s]["open_half_spread"] = 3e-5
    close = pd.concat({s: d["close"] for s, d in b.items()}, axis=1)
    uni = pd.DataFrame(True, index=close.index, columns=close.columns)
    def rule(c):
        on = (c > c.rolling(50).mean()).astype(float)
        return on.div(on.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    fx = validate.walk_forward(b, {"n50": rule}, bar="1d", n_trials=1, uni=uni,
                               cost_model=costmodels.ForexCosts())
    cr = validate.walk_forward(b, {"n50": rule}, bar="1d", n_trials=1, uni=uni, venue="okx")
    assert "eligible" in fx and fx["n_windows"] == cr["n_windows"]
    # Same signals, but cheaper fills leave slightly more cash, which changes what clears
    # the no-trade band, so counts drift by a few percent. They must not diverge wildly.
    assert fx["n_trades"] > 0 and abs(fx["n_trades"] - cr["n_trades"]) <= 0.2 * cr["n_trades"]
    assert fx["oos_net_ret"] >= cr["oos_net_ret"], "cheaper friction cannot produce a lower net return"
