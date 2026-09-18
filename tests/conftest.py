import numpy as np
import pandas as pd
import pytest


def synth_bars(n=3000, seed=0, start="2020-01-01", freq="1h", syms=("BTCUSDT", "ETHUSDT")):
    """Deterministic synthetic OHLCV for referee unit tests ONLY (never for research)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    out = {}
    for k, s in enumerate(syms):
        r = rng.normal(0.0002, 0.01, n)
        close = 100 * (k + 1) * np.exp(np.cumsum(r))
        open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.001, n))
        high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.005, n))
        low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.005, n))
        qv = rng.uniform(5e6, 5e7, n)
        out[s] = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                               "volume": qv / close, "quote_volume": qv}, index=idx)
    return out


@pytest.fixture
def bars():
    return synth_bars()
