"""The trend-pullback-engulfing setup, as taught in the MT5 tutorial, ported honestly.

The original, translated:
  1. two EMAs, 20 and 50; above is an uptrend, below a downtrend
  2. wait for price to pull back into the band between them
  3. enter on an engulfing candle in the trend direction, at its close
  4. stop at a recent swing low or at 1.5 x ATR
  5. target at a fixed multiple of the risk, typically 2:1
  6. size by risking a fixed percentage of the account

What is faithfully reproduced: all of the above, for longs by default.

The short half (sell a bearish engulfing candle after a rally into the band, in a
downtrend) is available with both_sides=True. It is OFF by default because the crypto
account is spot-only with no leverage and must never be handed a short. In forex every
position is long one currency and short the other, so selling EURUSD is as natural as
buying it, and there the full strategy is tested as its author intended.

Everything is a function of bars up to and including the signal bar. The entry is
executed at the OPEN of the following bar, not at the close of the signal bar as the
tutorial says, because "enter at the close of the engulfing candle" is not achievable
by a system that only learns the close when the bar has ended.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

# Fixed before any result was seen. Deliberately small; every extra entry raises the
# multiple-testing bar the referee applies.
GRID = [
    {"fast": 20, "slow": 50, "pullback_bars": 5, "atr_period": 14, "atr_mult": 1.5, "rr": 2.0},
    {"fast": 20, "slow": 50, "pullback_bars": 5, "atr_period": 14, "atr_mult": 1.5, "rr": 3.0},
    {"fast": 20, "slow": 50, "pullback_bars": 3, "atr_period": 14, "atr_mult": 2.5, "rr": 2.0},
    {"fast": 10, "slow": 30, "pullback_bars": 5, "atr_period": 14, "atr_mult": 1.5, "rr": 2.0},
    {"fast": 50, "slow": 200, "pullback_bars": 10, "atr_period": 14, "atr_mult": 1.5, "rr": 2.0},
]


def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Previous bar closed down, this bar closed up, and this bar's body covers it."""
    o, c = df["open"], df["close"]
    prev_down = c.shift(1) < o.shift(1)
    this_up = c > o
    engulfs = (o <= c.shift(1)) & (c >= o.shift(1))
    return (prev_down & this_up & engulfs).fillna(False)


def bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Previous bar closed up, this bar closed down, and this bar's body covers it."""
    o, c = df["open"], df["close"]
    prev_up = c.shift(1) > o.shift(1)
    this_down = c < o
    engulfs = (o >= c.shift(1)) & (c <= o.shift(1))
    return (prev_up & this_down & engulfs).fillna(False)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average true range, Wilder-style, strictly backward-looking."""
    h, l, pc = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def trend_pullback_engulfing(bars: dict[str, pd.DataFrame], fast: int = 20, slow: int = 50,
                             pullback_bars: int = 5, atr_period: int = 14,
                             atr_mult: float = 1.5, rr: float = 2.0,
                             universe: pd.DataFrame | None = None,
                             both_sides: bool = False) -> pd.DataFrame:
    """Return a (symbol, field) frame with enter / stop / target per bar.
    `enter` is +1 for a long, -1 for a short (both_sides only), else 0."""
    out = {}
    for sym, df in bars.items():
        ef = df["close"].ewm(span=fast, adjust=False).mean()
        es = df["close"].ewm(span=slow, adjust=False).mean()
        a = atr(df, atr_period)
        ref = df["close"]
        elig = a.notna() & es.notna()
        if universe is not None and sym in universe.columns:
            elig = elig & universe[sym].reindex(df.index).fillna(False).astype(bool)

        # ---- long: uptrend, pullback into the band, bullish engulfing
        uptrend = ef > es
        in_band_up = (df["low"] <= ef) & (df["close"] >= es)
        pulled_back_up = in_band_up.rolling(pullback_bars, min_periods=1).max().astype(bool)
        long_on = uptrend & pulled_back_up & bullish_engulfing(df) & elig
        swing_low = df["low"].rolling(pullback_bars, min_periods=1).min()
        stop_l = pd.concat([ref - atr_mult * a, swing_low], axis=1).min(axis=1)
        risk_l = (ref - stop_l).where(lambda x: x > 0)
        long_on = long_on & risk_l.notna()
        tgt_l = ref + rr * risk_l

        # ---- short: the mirror image, only when asked for
        if both_sides:
            downtrend = ef < es
            in_band_dn = (df["high"] >= ef) & (df["close"] <= es)
            pulled_back_dn = in_band_dn.rolling(pullback_bars, min_periods=1).max().astype(bool)
            short_on = downtrend & pulled_back_dn & bearish_engulfing(df) & elig & ~long_on
            swing_high = df["high"].rolling(pullback_bars, min_periods=1).max()
            stop_s = pd.concat([ref + atr_mult * a, swing_high], axis=1).max(axis=1)
            risk_s = (stop_s - ref).where(lambda x: x > 0)
            short_on = short_on & risk_s.notna()
            tgt_s = ref - rr * risk_s
        else:
            short_on = pd.Series(False, index=df.index)
            stop_s = tgt_s = pd.Series(np.nan, index=df.index)

        enter = long_on.astype(float) - short_on.astype(float)
        stop = stop_l.where(long_on, stop_s.where(short_on))
        target = tgt_l.where(long_on, tgt_s.where(short_on))
        out[(sym, "enter")] = enter
        out[(sym, "stop")] = stop
        out[(sym, "target")] = target
    frame = pd.DataFrame(out)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    return frame.sort_index(axis=1)


def n_variants() -> int:
    return len(GRID)
