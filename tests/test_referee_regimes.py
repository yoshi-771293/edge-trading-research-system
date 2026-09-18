import numpy as np
import pandas as pd
from referee import regimes


def test_labels_are_causal(bars):
    close = bars["BTCUSDT"]["close"].resample("1D").last().dropna()
    base = regimes.label(close)
    cut = len(close) // 2
    corrupted = close.copy()
    corrupted.iloc[cut + 1:] *= np.random.default_rng(1).uniform(0.2, 5, len(close) - cut - 1)
    alt = regimes.label(corrupted)
    pd.testing.assert_frame_equal(base.iloc[:cut + 1], alt.iloc[:cut + 1])


def test_every_bar_gets_exactly_one_trend_and_one_vol_label(bars):
    close = bars["BTCUSDT"]["close"].resample("1D").last().dropna()
    lab = regimes.label(close).dropna()
    assert set(lab["trend"].unique()) <= {"bull", "bear"}
    assert set(lab["vol"].unique()) <= {"low", "mid", "high"}
    assert lab["chop"].dtype == bool
