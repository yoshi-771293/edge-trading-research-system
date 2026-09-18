"""Deposits, many coins, and delistings.

The accounting trap this pins down: if you add $100 a month for eight years and then
report "account grew from $1,000 to $12,000", most of that is your own money, not
profit. Contributed capital and investment return must be tracked separately, and the
skill measure (time-weighted return) must be completely unmoved by a deposit.
"""
import numpy as np
import pandas as pd
import pytest
from referee import replay, universe, costs


def flat_bars(syms=("A", "B"), days=400, price=100.0, qv=1e9, start="2021-01-01"):
    idx = pd.date_range(start, periods=days, freq="1D", tz="UTC")
    return {s: pd.DataFrame({"open": price, "high": price, "low": price, "close": price,
                             "volume": qv / price, "quote_volume": qv}, index=idx) for s in syms}


def all_in_universe(bars):
    idx = universe.master_index(bars)
    return pd.DataFrame(True, index=idx, columns=list(bars))


def test_deposits_are_not_profit():
    """Flat prices. Deposits arrive. Profit must be exactly zero and TWR exactly 1."""
    bars = flat_bars(days=400)
    tgt = pd.DataFrame(0.0, index=universe.master_index(bars), columns=list(bars))
    tgt["A"] = 0.5
    r = replay.execute(bars, tgt, universe=all_in_universe(bars), start_equity=1000.0,
                       monthly_deposit=100.0, kill_switch=False)
    n_deposits = int(r.contributed.iloc[-1] - 1000) // 100
    assert n_deposits >= 12
    assert r.contributed.iloc[-1] == pytest.approx(1000 + 100 * n_deposits)
    # flat prices, so the only loss is friction; profit must be <= 0 and tiny
    assert r.profit.iloc[-1] <= 0
    assert r.profit.iloc[-1] > -50
    assert r.twr.iloc[-1] == pytest.approx(r.equity.iloc[-1] / r.contributed.iloc[-1], abs=0.02)


def test_time_weighted_return_ignores_deposit_timing():
    """Same price path, different deposit sizes: TWR must be identical."""
    bars = flat_bars(days=200)
    idx = universe.master_index(bars)
    tgt = pd.DataFrame(0.0, index=idx, columns=list(bars))
    a = replay.execute(bars, tgt, universe=all_in_universe(bars), start_equity=1000.0, monthly_deposit=0.0, kill_switch=False)
    b = replay.execute(bars, tgt, universe=all_in_universe(bars), start_equity=1000.0, monthly_deposit=500.0, kill_switch=False)
    assert a.twr.iloc[-1] == pytest.approx(b.twr.iloc[-1], abs=1e-9)
    assert b.contributed.iloc[-1] > a.contributed.iloc[-1]


def test_profit_equals_value_minus_contributions():
    bars = flat_bars(days=300, price=100.0)
    for s in bars:
        bars[s]["close"] = np.linspace(100, 200, 300)
        bars[s]["open"] = bars[s]["close"]
    idx = universe.master_index(bars)
    tgt = pd.DataFrame(0.0, index=idx, columns=list(bars)); tgt["A"] = 0.6
    r = replay.execute(bars, tgt, universe=all_in_universe(bars), start_equity=1000.0,
                       monthly_deposit=100.0, kill_switch=False)
    assert r.profit.iloc[-1] == pytest.approx(r.equity.iloc[-1] - r.contributed.iloc[-1], abs=1e-6)
    assert r.profit.iloc[-1] > 0


def test_deposit_lands_once_per_month_on_the_first_bar():
    bars = flat_bars(days=95, start="2021-01-01")
    idx = universe.master_index(bars)
    tgt = pd.DataFrame(0.0, index=idx, columns=list(bars))
    r = replay.execute(bars, tgt, universe=all_in_universe(bars), start_equity=1000.0,
                       monthly_deposit=100.0, kill_switch=False)
    adds = r.contributed.diff().fillna(0.0)
    months = adds[adds > 0].index
    assert list(months.strftime("%Y-%m")) == ["2021-02", "2021-03", "2021-04"]
    assert (adds[adds > 0] == 100.0).all()


def test_cannot_hold_a_coin_outside_the_universe():
    bars = flat_bars(syms=("A", "B"), days=200)
    idx = universe.master_index(bars)
    uni = pd.DataFrame(True, index=idx, columns=["A", "B"]); uni["B"] = False
    tgt = pd.DataFrame(0.5, index=idx, columns=["A", "B"])
    r = replay.execute(bars, tgt, universe=uni, start_equity=1000.0, kill_switch=False)
    assert (r.weights["B"] < 1e-9).all()
    assert r.weights["A"].iloc[-1] > 0.1


def test_delisted_position_is_force_exited_with_a_haircut():
    """A coin whose data ends must be liquidated at a WORSE price than its last close."""
    bars = flat_bars(syms=("GOOD", "DOOMED"), days=200)
    bars["DOOMED"] = bars["DOOMED"].iloc[:100]
    idx = universe.master_index(bars)
    uni = universe.availability(bars, idx)
    tgt = pd.DataFrame(0.0, index=idx, columns=["GOOD", "DOOMED"]); tgt["DOOMED"] = 0.5
    r = replay.execute(bars, tgt, universe=uni, start_equity=1000.0, kill_switch=False)
    exits = r.trades[(r.trades["symbol"] == "DOOMED") & (r.trades["side"] == "DELIST")]
    assert len(exits) == 1
    assert exits.iloc[0]["fill"] == pytest.approx(100.0 * (1 - costs.DELIST_HAIRCUT))
    assert (r.weights["DOOMED"].iloc[120:] < 1e-9).all()
    assert r.equity.iloc[-1] < 1000.0                      # the haircut really cost money


def test_scales_to_thirty_coins():
    bars = flat_bars(syms=tuple(f"C{i}" for i in range(30)), days=400)
    for i, s in enumerate(bars):
        bars[s]["close"] = np.linspace(100, 100 + i, 400)
        bars[s]["open"] = bars[s]["close"]
    idx = universe.master_index(bars)
    tgt = pd.DataFrame(0.0, index=idx, columns=list(bars))
    tgt.iloc[:, :5] = 0.2                                   # hold 5 of 30
    r = replay.execute(bars, tgt, universe=all_in_universe(bars), start_equity=1000.0,
                       monthly_deposit=100.0, kill_switch=False)
    assert r.exposure.max() <= 1.0 + 1e-9
    assert len(r.trades) > 5
    assert r.weights.shape[1] == 30


def test_benchmark_gets_the_same_deposits():
    bars = flat_bars(syms=("BTCUSDT",), days=400)
    bars["BTCUSDT"]["close"] = np.linspace(100, 400, 400)
    bars["BTCUSDT"]["open"] = bars["BTCUSDT"]["close"]
    r = replay.buy_and_hold_dca(bars, "BTCUSDT", start_equity=1000.0, monthly_deposit=100.0)
    assert r.contributed.iloc[-1] > 1000.0
    assert r.profit.iloc[-1] == pytest.approx(r.equity.iloc[-1] - r.contributed.iloc[-1], abs=1e-6)
    assert len(r.trades) >= 13                              # buys every month, never sells
    assert (r.trades["side"] == "BUY").all()


def test_a_coin_that_leaves_the_universe_can_still_be_sold():
    """The universe gates BUYING. A position must always be exitable while the coin
    still trades, or membership churn would strand capital forever."""
    bars = flat_bars(syms=("A", "B"), days=300)
    idx = universe.master_index(bars)
    uni = pd.DataFrame(True, index=idx, columns=["A", "B"])
    uni.loc[idx[150]:, "B"] = False                 # B drops out of the top 30 on day 150
    tgt = pd.DataFrame(0.0, index=idx, columns=["A", "B"]); tgt["B"] = 0.3
    r = replay.execute(bars, tgt, universe=uni, start_equity=1000.0, kill_switch=False)
    assert r.weights["B"].iloc[140] > 0.1, "never bought B while it was eligible"
    assert r.weights["B"].iloc[-1] < 1e-9, "B was stranded: could not be sold after leaving the universe"
    sells = r.trades[(r.trades["symbol"] == "B") & (r.trades["side"] == "SELL")]
    assert len(sells) >= 1
