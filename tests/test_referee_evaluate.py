"""The single audited entry point the player must use to score a candidate."""
import numpy as np
import pandas as pd
from referee import validate
from tests.conftest import synth_bars


def _daily():
    return synth_bars(n=3000, seed=5, freq="1D")


def _trend(close, n=50):
    on = (close > close.rolling(n).mean()).astype(float)
    return on.div(on.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)


def test_evaluate_reports_gross_and_net_walk_forward_and_flags():
    bars = _daily()
    rep = validate.evaluate(bars, _trend, bar="1d", n_trials=500)
    assert rep["gross"]["ret"] >= rep["net"]["ret"]
    assert rep["n_windows"] >= 1
    assert len(rep["windows"]) == rep["n_windows"]
    for k in ["sharpe_net", "deflated", "n_trades", "min_trades_ok", "regime", "tripwire", "causality"]:
        assert k in rep
    assert rep["causality"]["passed"] is True
    assert rep["deflated"]["n"] > 0
    assert "net>gross" not in rep["tripwire"]["reason"]
    assert "asset" not in rep["tripwire"]["reason"]


def test_evaluate_rejects_leaky_rule(bars):
    def leaky(c):
        on = (c.shift(-1) > c).astype(float)
        return on.div(on.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    rep = validate.evaluate(bars, leaky, bar="1h", n_trials=1)
    assert rep["causality"]["passed"] is False
    assert rep["eligible"] is False


def test_walk_forward_selects_on_train_and_scores_on_test():
    bars = _daily()
    variants = {n: (lambda c, n=n: _trend(c, n)) for n in (20, 50, 100)}
    rep = validate.walk_forward(bars, variants, bar="1d", n_trials=3)
    assert rep["n_windows"] >= 1
    assert all(w["param"] in variants for w in rep["windows"])
    assert rep["gross" if "gross" in rep else "sharpe_gross"] is not None
    assert rep["sharpe_gross"] >= rep["sharpe_net"] - 1e-9 or rep["oos_gross_ret"] >= rep["oos_net_ret"]
    assert rep["deflated"]["n"] > 0
    assert "single_regime" in rep["regime"]
