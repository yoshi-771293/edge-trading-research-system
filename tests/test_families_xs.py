"""Cross-sectional families for a many-coin universe. Each must be causal, must only
ever hold coins inside the point-in-time universe, and must respect its position count."""
import numpy as np
import pandas as pd
import pytest
from referee import replay, validate
from player import families
from tests.conftest import synth_bars

BARS = synth_bars(n=900, seed=17, freq="1D", syms=tuple(f"C{i}" for i in range(12)))
CLOSE = pd.concat({s: d["close"] for s, d in BARS.items()}, axis=1)
UNI = pd.DataFrame(True, index=CLOSE.index, columns=CLOSE.columns)
UNI["C11"] = False                                     # C11 is never in the universe


def _variants():
    for fam, spec in families.FAMILIES.items():
        for p in spec["grid"]:
            yield fam, p


@pytest.mark.parametrize("fam,param", list(_variants()))
def test_variant_is_causal(fam, param):
    rule = families.make_rule(fam, param, UNI)
    assert validate.causality_battery(rule, CLOSE).passed


@pytest.mark.parametrize("fam,param", list(_variants()))
def test_variant_never_leaves_the_universe(fam, param):
    w = families.make_rule(fam, param, UNI)(CLOSE)
    assert (w["C11"].abs() < 1e-12).all(), f"{fam}{param} held a coin outside the universe"


@pytest.mark.parametrize("fam,param", list(_variants()))
def test_variant_is_long_only_and_fully_invested_at_most(fam, param):
    w = families.make_rule(fam, param, UNI)(CLOSE)
    assert (w >= -1e-12).all().all()
    assert (w.sum(axis=1) <= 1 + 1e-9).all()


@pytest.mark.parametrize("fam", list(families.FAMILIES))
def test_position_count_is_respected(fam):
    param = families.FAMILIES[fam]["grid"][0]
    w = families.make_rule(fam, param, UNI)(CLOSE)
    held = (w > 1e-9).sum(axis=1)
    assert held.max() <= families.max_positions(fam, param)


@pytest.mark.parametrize("fam", list(families.FAMILIES))
def test_matches_the_strict_bar_by_bar_loop(fam):
    param = families.FAMILIES[fam]["grid"][0]
    rule = families.make_rule(fam, param, UNI)
    strict = replay.strict_targets(CLOSE, lambda h: rule(h).iloc[-1], sample_every=163, min_history=400)
    pd.testing.assert_frame_equal(strict, rule(CLOSE).loc[strict.index], check_names=False)


def test_candidate_count_is_declared_and_modest():
    n = families.candidate_count()
    assert 50 <= n <= 400, n
