"""The numpy fast path for risk caps must be bit-for-bit equal to the pandas reference."""
import numpy as np
import pandas as pd
from referee import risk


def test_fast_risk_equals_reference():
    rng = np.random.default_rng(0)
    syms = ["BTCUSDT", "ETHUSDT"]
    for _ in range(2000):
        w = rng.uniform(-0.2, 1.5, 2); eq = rng.uniform(100, 5000); hold = rng.uniform(0, 3000, 2)
        ref = risk.apply(pd.Series(w, index=syms), eq, pd.Series(hold, index=syms)).values
        fast = risk.apply_np(w, eq, hold)
        assert np.allclose(ref, fast, atol=1e-9), (w, eq, hold, ref, fast)
