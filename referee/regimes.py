"""Fixed, causal regime labels on BTC daily closes.
trend: bull if close > SMA200 else bear
vol:   30-day realised vol tercile against history-to-date (expanding quantiles)
chop:  60-day range < 15% and |close/SMA50 - 1| < 3%
"""
import numpy as np
import pandas as pd


def label(close: pd.Series) -> pd.DataFrame:
    sma200 = close.rolling(200).mean()
    sma50 = close.rolling(50).mean()
    rv = close.pct_change().rolling(30).std() * np.sqrt(365)
    q1 = rv.expanding(min_periods=60).quantile(1 / 3)
    q2 = rv.expanding(min_periods=60).quantile(2 / 3)
    trend = pd.Series(np.where(close > sma200, "bull", "bear"), index=close.index, dtype=object)
    trend[sma200.isna()] = None
    vol = pd.Series(np.select([rv <= q1, rv <= q2], ["low", "mid"], "high"), index=close.index, dtype=object)
    vol[q2.isna()] = None
    rng = (close.rolling(60).max() / close.rolling(60).min() - 1)
    chop = ((rng < 0.15) & ((close / sma50 - 1).abs() < 0.03)).fillna(False).astype(bool)
    return pd.DataFrame({"trend": trend, "vol": vol, "chop": chop})


def daily_labels_for(index: pd.DatetimeIndex, close_daily: pd.Series) -> pd.DataFrame:
    """Map labels computed on daily closes onto any bar index, using the label of the
    last COMPLETED day (never the current one)."""
    lab = label(close_daily).shift(1)
    return lab.reindex(index, method="ffill")
