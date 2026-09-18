"""Calibrating the instrument.

Sixty-nine strategies have now been rejected by this harness. Every one of those
verdicts rests on an assumption never tested: that the harness CAN detect an edge when
one is present. An instrument that says "no" to everything, including things that are
genuinely true, is not a strict instrument, it is a broken one, and all of its negatives
are worthless.

So: inject edges of known size and check the harness recovers them.

  * A POSITIVE CONTROL whose truth is set by a dial. The edge is injected into the
    DATA, as a known return autocorrelation rho, and read by a fully CAUSAL momentum
    rule. rho=0 is a random walk with nothing to find. As rho rises the measured Sharpe
    must rise with it, must track the theoretical value, and the gates must eventually
    pass. (A first attempt used a rule that peeked instead; the causality battery
    refused to score it, which is the guard working as designed.)
  * A NEGATIVE CONTROL: random entries at matched turnover. Must score around zero and
    must fail the gates.

If the positive control cannot pass, no negative from this harness means anything.
"""
import numpy as np
import pandas as pd
import pytest
from player import controls
from referee import costmodels, validate

FX = costmodels.ForexCosts()   # calibration runs on forex-grade friction, stated explicitly


def _panel(n=1600, k=6, seed=0, vol=0.012):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-01", periods=n, freq="1D", tz="UTC")
    out = {}
    for i in range(k):
        r = rng.normal(0.0002, vol, n)
        c = 100 * np.exp(np.cumsum(r))
        out[f"S{i}"] = pd.DataFrame({"open": c, "high": c * 1.004, "low": c * 0.996, "close": c,
                                     "volume": 1e6, "quote_volume": 1e9,
                                     "half_spread": 2e-5, "open_half_spread": 3e-5}, index=idx)
    return out


def _close(bars):
    return pd.concat({s: d["close"] for s, d in bars.items()}, axis=1)


# ---- the probe is honest about what it is ---------------------------------
def test_the_oracle_is_labelled_as_using_future_information():
    assert controls.USES_FUTURE_INFORMATION is True
    assert "probe" in controls.__doc__.lower() or "calibration" in controls.__doc__.lower()


def test_the_causality_battery_rejects_the_oracle():
    """This proves two things at once: the probe really does peek, and the battery that
    guards every real strategy actually catches peeking."""
    bars = _panel()
    rule = controls.oracle_rule(accuracy=0.9, seed=1, k=2)
    assert not validate.causality_battery(rule, _close(bars)).passed


def test_a_random_control_is_causal():
    bars = _panel()
    rule = controls.random_rule(rate=0.3, seed=2, k=2)
    assert validate.causality_battery(rule, _close(bars)).passed


# ---- the oracle's accuracy is what it claims ------------------------------
def test_a_zero_edge_panel_really_has_no_drift_to_harvest():
    """Without the Jensen correction a zero-rho panel drifts up and any long-biased rule
    scores positive on it, which would read as an edge where none was injected."""
    bars = controls.predictable_panel(0.0, n=4000, k=4, seed=99)
    arith = np.mean([d["close"].pct_change().mean() for d in bars.values()])
    assert abs(arith) < 2e-5, f"mean arithmetic return {arith:.2e} is not flat enough"


def test_the_injected_autocorrelation_is_really_present():
    for rho in (0.0, 0.08, 0.16):
        bars = controls.predictable_panel(rho, n=4000, k=3, seed=3)
        got = np.mean([d["close"].pct_change().autocorr(1) for d in bars.values()])
        assert got == pytest.approx(rho, abs=0.035), f"asked for rho={rho}, data has {got:.3f}"


def test_the_momentum_rule_reading_it_is_causal():
    bars = controls.predictable_panel(0.10, n=1200, k=4, seed=4)
    assert validate.causality_battery(controls.momentum_rule(k=2), _close(bars)).passed


# ---- detection power: the measured Sharpe must track the injected edge -----
def test_measured_sharpe_rises_with_the_injected_edge():
    got = []
    for rho in (0.0, 0.04, 0.08, 0.16):
        bars = controls.predictable_panel(rho, n=2000, k=6, seed=5)
        uni = pd.DataFrame(True, index=_close(bars).index, columns=list(bars))
        rep = validate.walk_forward(bars, {"mom": controls.momentum_rule(k=3)},
                                    bar="1d", n_trials=1, uni=uni, cost_model=FX)
        got.append(rep["sharpe_net"])
    assert got == sorted(got), f"Sharpe did not rise with the edge: {[round(x,2) for x in got]}"
    assert got[-1] > got[0] + 1.0, f"a large edge moved Sharpe only {got[-1]-got[0]:.2f}"


def test_a_real_edge_passes_the_gates_the_strategies_failed():
    """The decisive calibration. If a genuine, sizeable edge cannot clear these gates,
    the gates are not strict but impassable, and every rejection so far is void."""
    bars = controls.predictable_panel(0.16, n=2000, k=6, seed=7)
    uni = pd.DataFrame(True, index=_close(bars).index, columns=list(bars))
    rep = validate.walk_forward(bars, {"mom": controls.momentum_rule(k=3)},
                                bar="1d", n_trials=69, uni=uni, cost_model=FX)
    assert rep["sharpe_net"] > 1.0
    assert rep["deflated"]["psr"] >= 0.5, f"PSR {rep['deflated']['psr']:.2f} on a genuine edge"
    assert rep["n_trades"] >= validate.MIN_TRADES


def test_the_measurement_tracks_theory_rather_than_merely_being_positive():
    """Not just 'detects something', but 'detects about the right amount'."""
    bars = controls.predictable_panel(0.12, n=3000, k=6, seed=12)
    uni = pd.DataFrame(True, index=_close(bars).index, columns=list(bars))
    rep = validate.walk_forward(bars, {"mom": controls.momentum_rule(k=3)},
                                bar="1d", n_trials=1, uni=uni, cost_model=FX)
    theory = controls.theoretical_sharpe(0.12)
    assert rep["sharpe_gross"] > 0.4 * theory, (
        f"measured {rep['sharpe_gross']:.2f} against a theoretical {theory:.2f}: signal is being lost")


def test_the_random_control_shows_no_edge_and_fails_the_gates():
    """An informationless rule must show nothing on the friction-free curve and must be
    rejected. Its NET number is allowed to be well negative: that is turnover being
    charged, which is a real cost and not a measurement artefact."""
    bars = controls.predictable_panel(0.0, n=2000, k=6, seed=9)
    uni = pd.DataFrame(True, index=_close(bars).index, columns=list(bars))
    rep = validate.walk_forward(bars, {"rand": controls.random_rule(0.3, seed=10, k=3)},
                                bar="1d", n_trials=69, uni=uni, cost_model=FX)
    assert rep["sharpe_paper"] < 0.6, "an informationless rule showed signal before costs"
    assert rep["sharpe_net"] < rep["sharpe_paper"], "turnover must cost something"
    assert rep["deflated"]["psr"] < 0.5
    assert not rep["eligible"]


# ---- the smallest edge the harness can still see --------------------------
def test_detection_floor_is_measured_and_reported():
    """How big must a real edge be before this harness will call it? A number worth
    knowing, because it bounds what the 69 rejections actually rule out."""
    floor = controls.detection_floor(n_trials=69, n=1500, k=5, seed=11)
    assert 0.0 < floor["rho"] < 0.20, f"floor at rho={floor['rho']}"
    assert floor["sharpe_at_floor"] > 0
    assert len(floor["ladder"]) >= 3
