"""Defects found in the 2026-09-16 audit. Each test fails before its fix.

1. universe.build computed bars-per-day with round(), which collapses weekly bars
   (0.143/day) to 1/day. The weekly universe therefore demanded 90 WEEKS of history
   instead of 90 days, silently shrinking the most promising horizon by 7x.
2. The breakout family broke ties by column order, so which coins it held depended on
   ticker spelling rather than on any signal.
3. segment_by_regime divided regime profit by the sum of POSITIVE returns only, so the
   share could exceed 1 and mislabel strategies. It gates eligibility.
4. The live agent added one deposit per cycle regardless of how many calendar months
   had passed, so an outage silently skipped contributions.
"""
import numpy as np
import pandas as pd
import pytest
from referee import universe, validate
from player import families


# ---- 1. weekly universe history requirement ------------------------------
def _weekly_bars(n=200, syms=("A", "B", "C", "D")):
    idx = pd.date_range("2021-01-04", periods=n, freq="7D", tz="UTC")
    return {s: pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
                             "volume": 1e6, "quote_volume": 1e8 - i * 1e6}, index=idx)
            for i, s in enumerate(syms)}


def test_bars_per_day_survives_weekly_data():
    idx = pd.date_range("2021-01-04", periods=50, freq="7D", tz="UTC")
    assert universe.bars_per_day(idx) == pytest.approx(1 / 7)


def test_weekly_universe_admits_coins_after_90_days_not_90_weeks():
    bars = _weekly_bars(n=60)
    uni = universe.build(bars, top_n=4, min_history_days=90, volume_window=30)
    # 90 days is about 13 weekly bars, so membership must begin well before bar 90
    first = uni.index[uni.any(axis=1)]
    assert len(first), "weekly universe never filled at all"
    assert uni.index.get_loc(first[0]) < 20, (
        f"first admission at bar {uni.index.get_loc(first[0])}: still using 90 weeks, not 90 days")


# ---- 2. breakout tiebreak --------------------------------------------------
def test_breakout_tiebreak_does_not_depend_on_ticker_spelling():
    """Two identical price series named differently must produce the same holdings.
    Column order must never decide which coin is bought."""
    n = 80
    idx = pd.date_range("2021-01-01", periods=n, tz="UTC")
    ramp = np.linspace(1, 3, n)
    strong = np.linspace(1, 6, n)
    a = pd.DataFrame({"AAA": ramp, "ZZZ": strong}, index=idx)
    b = pd.DataFrame({"ZZZ": strong, "AAA": ramp}, index=idx)
    ua = pd.DataFrame(True, index=idx, columns=a.columns)
    ub = pd.DataFrame(True, index=idx, columns=b.columns)
    wa = families.make_rule("breakout", (20, 1), ua)(a).iloc[-1]
    wb = families.make_rule("breakout", (20, 1), ub)(b).iloc[-1]
    held_a = set(wa[wa > 1e-9].index)
    held_b = set(wb[wb > 1e-9].index)
    assert held_a == held_b, f"holdings changed with column order: {held_a} vs {held_b}"
    assert held_a == {"ZZZ"}, f"should hold the stronger breakout, held {held_a}"


# ---- 3. regime share maths -------------------------------------------------
def _labels(idx, seq):
    return pd.DataFrame({"trend": seq, "vol": "mid", "chop": False}, index=idx)


def test_regime_share_is_bounded_and_uses_gross_profit():
    idx = pd.date_range("2021-01-01", periods=300, tz="UTC")
    ret = pd.Series(0.0, index=idx)
    ret.iloc[:100] = 0.01          # bull: +1.0 total
    ret.iloc[100:200] = -0.02      # bear: -2.0 total
    seg = validate.segment_by_regime(ret, _labels(idx, ["bull"] * 100 + ["bear"] * 100 + ["bull"] * 100))
    assert 0.0 <= seg["dominant_share"] <= 1.0, seg["dominant_share"]


def test_strategy_earning_in_both_regimes_is_not_flagged():
    idx = pd.date_range("2021-01-01", periods=300, tz="UTC")
    ret = pd.Series(0.0, index=idx)
    ret.iloc[:150] = 0.01          # bull
    ret.iloc[150:] = 0.008         # bear, nearly as much
    seg = validate.segment_by_regime(ret, _labels(idx, ["bull"] * 150 + ["bear"] * 150))
    assert seg["single_regime"] is False


def test_strategy_earning_only_in_one_regime_is_flagged():
    idx = pd.date_range("2021-01-01", periods=300, tz="UTC")
    ret = pd.Series(0.0, index=idx)
    ret.iloc[:150] = 0.01          # all the profit in bull
    seg = validate.segment_by_regime(ret, _labels(idx, ["bull"] * 150 + ["bear"] * 150))
    assert seg["single_regime"] is True
    assert seg["dominant"] == "bull"


# ---- 4. live agent deposits across an outage ------------------------------
def test_months_elapsed_counts_every_missed_month():
    from live import agent
    assert agent.months_between("2026-09", "2026-10") == 1
    assert agent.months_between("2026-09", "2026-12") == 3
    assert agent.months_between("2026-11", "2027-02") == 3
    assert agent.months_between("2026-09", "2026-09") == 0
    assert agent.months_between(None, "2026-09") == 0
