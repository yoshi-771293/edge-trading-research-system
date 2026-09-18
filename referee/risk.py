"""Hard limits. Not parameters. The player cannot import-and-override these because
the referee package is read-only and checksummed."""
import pandas as pd

MAX_ORDER_FRAC = 0.50
MAX_ASSET_FRAC = 0.35          # tightened from 0.60: a 30-coin universe holding 4-5 must not put 60% in one altcoin
MAX_TOTAL_EXPOSURE = 1.00
KILL_DRAWDOWN = 0.25


def apply(target_w: pd.Series, equity: float, holdings_usd: pd.Series) -> pd.Series:
    tgt = target_w.clip(lower=0.0, upper=MAX_ASSET_FRAC) * equity
    total = tgt.sum()
    if total > MAX_TOTAL_EXPOSURE * equity and total > 0:
        tgt = tgt * (MAX_TOTAL_EXPOSURE * equity / total)
    delta = (tgt - holdings_usd).clip(lower=-MAX_ORDER_FRAC * equity, upper=MAX_ORDER_FRAC * equity)
    return holdings_usd + delta


def apply_np(target_w, equity: float, holdings_usd):
    """Same rule as apply(), on numpy arrays. Bit-for-bit equal (tested)."""
    import numpy as np
    tgt = np.clip(np.asarray(target_w, dtype=float), 0.0, MAX_ASSET_FRAC) * equity
    total = tgt.sum()
    if total > MAX_TOTAL_EXPOSURE * equity and total > 0:
        tgt = tgt * (MAX_TOTAL_EXPOSURE * equity / total)
    h = np.asarray(holdings_usd, dtype=float)
    delta = np.clip(tgt - h, -MAX_ORDER_FRAC * equity, MAX_ORDER_FRAC * equity)
    return h + delta
