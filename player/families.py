"""Strategy families for a many-coin, point-in-time universe.

Every family is long-only, holds at most K coins, and may only ever hold coins that
were in the universe on that bar. All are pure functions of closes up to and
including the current bar, so the referee's causality battery can verify them.

Lookbacks are in BARS, so the same family runs on daily, 4-hour and weekly data.
Grids were fixed before any result was seen and are deliberately small: every extra
variant raises the multiple-testing bar the referee applies.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


# ---------- helpers -------------------------------------------------------
def _hold_top(score: pd.DataFrame, eligible: pd.DataFrame, k: int) -> pd.DataFrame:
    """Equal-weight the k best-scoring eligible coins at 1/k each. Fewer than k
    qualifiers means the rest stays in cash, which de-risks by construction.

    `score` must be a real, differentiating quantity. A constant score would make
    pandas fall back to column order, so holdings would depend on ticker spelling.
    """
    s = score.where(eligible)
    rank = s.rank(axis=1, ascending=False, method="first")
    return (rank <= k).astype(float) / float(k)


def _state(entry: pd.DataFrame, exit_: pd.DataFrame) -> pd.DataFrame:
    """Vectorised, causal state machine. Exit wins ties; state carries forward."""
    s = pd.DataFrame(np.where(exit_.values, 0.0, np.where(entry.values, 1.0, np.nan)),
                     index=entry.index, columns=entry.columns)
    return s.ffill().fillna(0.0)


def _market(close: pd.DataFrame, eligible: pd.DataFrame) -> pd.Series:
    """Equal-weight index of the eligible coins. Used as a risk-on/risk-off gauge."""
    r = close.pct_change().where(eligible)
    return (1 + r.mean(axis=1).fillna(0.0)).cumprod()


# ---------- families ------------------------------------------------------
def xs_momentum(close, elig, p):
    """Hold the k coins with the strongest trailing return, if that return is positive."""
    n, k = p
    ret = close / close.shift(n) - 1
    return _hold_top(ret, elig & (ret > 0), k)


def xs_momentum_gated(close, elig, p):
    """Cross-sectional momentum, but only while the whole market is in an uptrend."""
    n, k, gate = p
    ret = close / close.shift(n) - 1
    mkt = _market(close, elig)
    on = (mkt > mkt.rolling(gate).mean())
    return _hold_top(ret, elig & (ret > 0) & on.values[:, None], k)


def trend_basket(close, elig, p):
    """Hold the k coins furthest above their own moving average."""
    n, k = p
    ma = close.rolling(n).mean()
    dist = close / ma - 1
    return _hold_top(dist, elig & (close > ma), k)


def breakout(close, elig, p):
    """Buy an n-bar high, sell an n/2-bar low, hold at most k.

    When more than k coins are in a breakout, they are ranked by how far price sits
    above the n-bar average. The earlier version scored every candidate 1.0, so
    pandas broke the tie by column order and holdings depended on ticker spelling.
    """
    n, k = p
    hi = close.rolling(n).max()
    lo = close.rolling(max(n // 2, 2)).min()
    st = _state(close >= hi, close <= lo)
    st[hi.isna()] = 0.0
    strength = close / close.rolling(n).mean() - 1
    return _hold_top(strength, elig & (st > 0), k)


def xs_reversal(close, elig, p):
    """Buy the k worst recent performers, but only while the market is rising."""
    n, k, gate = p
    ret = close / close.shift(n) - 1
    mkt = _market(close, elig)
    on = (mkt > mkt.rolling(gate).mean())
    return _hold_top(-ret, elig & (ret < 0) & on.values[:, None], k)


def low_vol_trend(close, elig, p):
    """Among coins in an uptrend, hold the k calmest ones."""
    n, k, vn = p
    ma = close.rolling(n).mean()
    vol = close.pct_change().rolling(vn).std()
    return _hold_top(-vol, elig & (close > ma) & vol.notna(), k)


def vol_target_trend(close, elig, p):
    """Trend basket, each position shrunk when that coin is unusually volatile."""
    n, k, vn = p
    ma = close.rolling(n).mean()
    dist = close / ma - 1
    base = _hold_top(dist, elig & (close > ma), k)
    vol = close.pct_change().rolling(vn).std()
    ref = vol.rolling(vn * 5, min_periods=vn).median()
    return base * (ref / vol).clip(upper=1.0).fillna(0.0)


FAMILIES = {
    "xs_momentum":        {"fn": xs_momentum,        "grid": [(20, 3), (20, 5), (60, 3), (60, 5), (120, 5)]},
    "xs_momentum_gated":  {"fn": xs_momentum_gated,  "grid": [(20, 5, 100), (60, 5, 100), (60, 3, 200), (120, 5, 200)]},
    "trend_basket":       {"fn": trend_basket,       "grid": [(20, 5), (50, 5), (100, 5), (100, 3), (200, 5)]},
    "breakout":           {"fn": breakout,           "grid": [(20, 5), (55, 5), (55, 3), (100, 5)]},
    "xs_reversal":        {"fn": xs_reversal,        "grid": [(5, 5, 100), (10, 5, 100), (5, 3, 200), (20, 5, 200)]},
    "low_vol_trend":      {"fn": low_vol_trend,      "grid": [(100, 5, 20), (200, 5, 20), (100, 3, 30), (50, 5, 20)]},
    "vol_target_trend":   {"fn": vol_target_trend,   "grid": [(100, 5, 20), (200, 5, 20), (100, 3, 20)]},
}
BARS = ["4h", "1d", "1w"]


def max_positions(family: str, param) -> int:
    return int(param[1])


def make_rule(family: str, param, uni: pd.DataFrame):
    """Bind a family, its parameters and the point-in-time universe into a single
    causal function close -> target weights."""
    fn = FAMILIES[family]["fn"]

    def rule(close: pd.DataFrame) -> pd.DataFrame:
        elig = uni.reindex(index=close.index, columns=close.columns).fillna(False).astype(bool)
        elig = elig & close.notna()
        w = fn(close, elig, param)
        w = w.where(elig, 0.0).clip(0.0, 1.0).fillna(0.0)
        tot = w.sum(axis=1)
        over = tot > 1.0
        if over.any():
            w.loc[over] = w.loc[over].div(tot[over], axis=0)
        return w

    rule.__name__ = f"{family}:{param}"
    return rule


def candidate_count(bars=None) -> int:
    return sum(len(v["grid"]) for v in FAMILIES.values()) * len(bars or BARS)
