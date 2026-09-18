"""The trend-pullback-engulfing setup, as described in the MT5 tutorial.

Only the LONG half is testable here: the original sells in downtrends, which needs
shorting, and this project is spot-only with no leverage by its own specification.
"""
import numpy as np
import pandas as pd
import pytest
from player import setups


def _ohlc(rows, start="2021-01-01"):
    idx = pd.date_range(start, periods=len(rows), freq="1D", tz="UTC")
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "volume": 1e6, "quote_volume": 1e9}, index=idx)


# ---- the engulfing pattern -------------------------------------------------
def test_bullish_engulfing_is_detected():
    # bar 0 is a down candle, bar 1 is an up candle whose body swallows it
    df = _ohlc([(100, 101, 97, 98), (97, 104, 96, 103)])
    assert bool(setups.bullish_engulfing(df).iloc[1])


def test_an_up_candle_that_does_not_engulf_is_not_a_signal():
    df = _ohlc([(100, 101, 97, 98), (98.5, 100, 98, 99.5)])
    assert not bool(setups.bullish_engulfing(df).iloc[1])


def test_two_up_candles_are_not_an_engulfing():
    df = _ohlc([(98, 101, 97, 100), (97, 104, 96, 103)])
    assert not bool(setups.bullish_engulfing(df).iloc[1]), "the prior bar must be a down candle"


def test_the_pattern_never_fires_on_the_first_bar():
    df = _ohlc([(97, 104, 96, 103)])
    assert not bool(setups.bullish_engulfing(df).iloc[0])


def test_the_pattern_is_causal():
    rng = np.random.default_rng(0)
    rows = [(100 + rng.normal(), 102 + rng.normal(), 98 + rng.normal(), 100 + rng.normal()) for _ in range(300)]
    df = _ohlc(rows)
    base = setups.bullish_engulfing(df)
    tampered = df.copy()
    tampered.iloc[150:] = tampered.iloc[150:] * 5
    alt = setups.bullish_engulfing(tampered)
    pd.testing.assert_series_equal(base.iloc[:150], alt.iloc[:150])


# ---- ATR -------------------------------------------------------------------
def test_atr_is_causal_and_positive():
    rng = np.random.default_rng(1)
    rows = [(100, 103, 97, 100 + rng.normal()) for _ in range(200)]
    df = _ohlc(rows)
    a = setups.atr(df, 14)
    assert (a.dropna() > 0).all()
    tampered = df.copy(); tampered.iloc[100:] *= 4
    pd.testing.assert_series_equal(a.iloc[:100], setups.atr(tampered, 14).iloc[:100])


# ---- the full setup --------------------------------------------------------
def test_signal_frame_has_enter_stop_and_target_per_symbol():
    rng = np.random.default_rng(2)
    bars = {}
    for s in ("A", "B"):
        px = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 400)))
        bars[s] = _ohlc([(p, p * 1.02, p * 0.98, p * (1 + rng.normal(0, 0.005))) for p in px])
    sig = setups.trend_pullback_engulfing(bars, fast=20, slow=50, pullback_bars=5,
                                          atr_period=14, atr_mult=1.5, rr=2.0)
    assert set(sig.columns.get_level_values(0)) == {"A", "B"}
    assert set(sig.columns.get_level_values(1)) == {"enter", "stop", "target"}
    fired = sig[("A", "enter")] > 0
    if fired.any():
        i = fired.idxmax()
        assert sig.loc[i, ("A", "target")] > sig.loc[i, ("A", "stop")]


def test_the_target_is_exactly_the_risk_reward_multiple_of_the_risk():
    rng = np.random.default_rng(3)
    px = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.015, 500)))
    bars = {"A": _ohlc([(p, p * 1.03, p * 0.97, p * (1 + rng.normal(0, 0.004))) for p in px])}
    sig = setups.trend_pullback_engulfing(bars, rr=2.0)
    fired = sig[("A", "enter")] > 0
    assert fired.any(), "the setup never fired on 500 trending bars"
    i = fired.idxmax()
    ref = bars["A"]["close"].loc[i]
    stop, tgt = sig.loc[i, ("A", "stop")], sig.loc[i, ("A", "target")]
    assert (tgt - ref) == pytest.approx(2.0 * (ref - stop), rel=1e-6)


def test_no_signal_fires_against_the_trend():
    """Prices falling steadily: a long setup must never appear."""
    px = 100 * np.exp(np.cumsum(np.full(400, -0.01)))
    bars = {"A": _ohlc([(p, p * 1.001, p * 0.97, p * 0.99) for p in px])}
    sig = setups.trend_pullback_engulfing(bars)
    assert not (sig[("A", "enter")] > 0).any()


def test_the_whole_setup_is_causal():
    rng = np.random.default_rng(5)
    px = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 400)))
    rows = [(p, p * 1.02, p * 0.98, p * (1 + rng.normal(0, 0.005))) for p in px]
    bars = {"A": _ohlc(rows)}
    base = setups.trend_pullback_engulfing(bars)
    tam = {"A": bars["A"].copy()}
    tam["A"].iloc[200:] = tam["A"].iloc[200:] * 3
    alt = setups.trend_pullback_engulfing(tam)
    pd.testing.assert_frame_equal(base.iloc[:200], alt.iloc[:200])


def test_the_grid_is_declared_and_small():
    assert 1 <= len(setups.GRID) <= 12
    for p in setups.GRID:
        assert set(p) >= {"fast", "slow", "atr_mult", "rr"}


# ---- the short half, for markets where selling is natural ------------------
def test_bearish_engulfing_is_the_mirror_image():
    # bar 0 is an up candle, bar 1 is a down candle whose body swallows it
    df = _ohlc([(98, 101, 97, 100), (101, 102, 95, 96)])
    assert bool(setups.bearish_engulfing(df).iloc[1])
    assert not bool(setups.bullish_engulfing(df).iloc[1])


def test_short_signal_fires_only_in_a_downtrend_with_a_rally_into_the_band():
    """Prices falling steadily with a bounce: the short setup must appear, and it must
    carry a stop ABOVE and a target BELOW the reference price."""
    rng = np.random.default_rng(11)
    px = 100 * np.exp(np.cumsum(rng.normal(-0.002, 0.012, 500)))
    bars = {"A": _ohlc([(p, p * 1.03, p * 0.97, p * (1 + rng.normal(0, 0.006))) for p in px])}
    sig = setups.trend_pullback_engulfing(bars, both_sides=True)
    shorts = sig[("A", "enter")] < 0
    assert shorts.any(), "no short ever fired on 500 falling bars"
    i = shorts.idxmax()
    ref = bars["A"]["close"].loc[i]
    assert sig.loc[i, ("A", "stop")] > ref > sig.loc[i, ("A", "target")]


def test_short_target_is_the_risk_reward_multiple_below():
    rng = np.random.default_rng(12)
    px = 100 * np.exp(np.cumsum(rng.normal(-0.002, 0.012, 500)))
    bars = {"A": _ohlc([(p, p * 1.03, p * 0.97, p * (1 + rng.normal(0, 0.006))) for p in px])}
    sig = setups.trend_pullback_engulfing(bars, both_sides=True, rr=2.0)
    shorts = sig[("A", "enter")] < 0
    i = shorts.idxmax()
    ref = bars["A"]["close"].loc[i]
    assert (ref - sig.loc[i, ("A", "target")]) == pytest.approx(2.0 * (sig.loc[i, ("A", "stop")] - ref), rel=1e-6)


def test_long_only_is_still_the_default():
    rng = np.random.default_rng(13)
    px = 100 * np.exp(np.cumsum(rng.normal(-0.002, 0.012, 400)))
    bars = {"A": _ohlc([(p, p * 1.03, p * 0.97, p * (1 + rng.normal(0, 0.006))) for p in px])}
    sig = setups.trend_pullback_engulfing(bars)
    assert not (sig[("A", "enter")] < 0).any(), "crypto spot must never be handed a short"


def test_both_sides_setup_is_causal():
    rng = np.random.default_rng(14)
    px = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.015, 400)))
    rows = [(p, p * 1.02, p * 0.98, p * (1 + rng.normal(0, 0.005))) for p in px]
    bars = {"A": _ohlc(rows)}
    base = setups.trend_pullback_engulfing(bars, both_sides=True)
    tam = {"A": bars["A"].copy()}
    tam["A"].iloc[200:] = tam["A"].iloc[200:] * 3
    alt = setups.trend_pullback_engulfing(tam, both_sides=True)
    pd.testing.assert_frame_equal(base.iloc[:200], alt.iloc[:200])
