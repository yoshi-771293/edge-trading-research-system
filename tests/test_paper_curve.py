"""A genuinely friction-free reference curve.

`equity_gross` removes the COMMISSION but still pays the spread, because it reprices the
same fills. Reporting it as "gross" implied "before costs", and that was misleading in a
way that nearly produced a false conclusion: the seven forex families showed gross -0.5,
which I was about to read as the signals being anti-predictive. An informationless rule
with the same turnover shows gross -0.5 on a panel with NO edge in it at all. The whole
of that -0.5 is spread.

So the engines now also carry `equity_paper`: the same decisions, filled at the
reference price with no commission and no spread. That is the number that answers "does
the signal contain anything", and it must be reported beside the other two.
"""
import numpy as np
import pandas as pd
import pytest
from player import controls
from referee import brackets, costmodels, replay


def _panel(rho=0.0, n=900, k=4, seed=0):
    return controls.predictable_panel(rho, n=n, k=k, seed=seed)


def _uni(bars):
    idx = list(bars.values())[0].index
    return pd.DataFrame(True, index=idx, columns=list(bars))


def test_paper_is_free_of_both_commission_and_spread():
    bars = _panel()
    close = pd.concat({s: d["close"] for s, d in bars.items()}, axis=1)
    w = controls.momentum_rule(k=2)(close)
    r = replay.execute(bars, w, universe=_uni(bars), start_equity=1000.0, kill_switch=False,
                       cost_model=costmodels.ForexCosts())
    assert r.equity_paper.iloc[-1] >= r.equity_gross.iloc[-1] >= r.equity.iloc[-1] - 1e-9
    assert r.equity_paper.iloc[-1] > r.equity_gross.iloc[-1], "paper must also drop the spread"


def test_the_same_rule_scores_near_zero_without_an_edge_and_high_with_one():
    """The property the old `gross` could not show. One rule, two panels: flat when the
    data holds nothing, strongly positive when it holds something. The residual on the
    flat panel is the no-trade band and cash sequencing, not signal."""
    def paper_sharpe(rho, seed):
        bars = _panel(rho=rho, n=2000, k=6, seed=seed)
        close = pd.concat({s: d["close"] for s, d in bars.items()}, axis=1)
        r = replay.execute(bars, controls.momentum_rule(k=3)(close), universe=_uni(bars),
                           start_equity=1000.0, kill_switch=False, cost_model=costmodels.ForexCosts())
        return replay.metrics(r.paper_twr, 365)["sharpe"]
    flat = paper_sharpe(0.0, 9)
    edged = paper_sharpe(0.12, 5)
    assert abs(flat) < 0.6, f"paper Sharpe {flat:+.2f} on a panel with no edge in it"
    assert edged > 2.0, f"paper Sharpe only {edged:+.2f} on a panel with a real edge"
    assert edged - flat > 2.5


def test_an_informationless_rule_never_looks_like_an_edge_on_paper():
    bars = _panel(rho=0.12, n=2000, k=6, seed=5)
    close = pd.concat({s: d["close"] for s, d in bars.items()}, axis=1)
    r = replay.execute(bars, controls.random_rule(0.3, seed=10, k=3)(close), universe=_uni(bars),
                       start_equity=1000.0, kill_switch=False, cost_model=costmodels.ForexCosts())
    assert replay.metrics(r.paper_twr, 365)["sharpe"] < 0.6, "random picked up the edge it cannot see"


def test_a_real_edge_shows_up_on_paper():
    bars = _panel(rho=0.12, n=2000, k=6, seed=5)
    close = pd.concat({s: d["close"] for s, d in bars.items()}, axis=1)
    w = controls.momentum_rule(k=3)(close)
    r = replay.execute(bars, w, universe=_uni(bars), start_equity=1000.0, kill_switch=False,
                       cost_model=costmodels.ForexCosts())
    assert replay.metrics(r.paper_twr, 365)["sharpe"] > 1.0


def test_the_bracket_engine_carries_the_same_reference():
    bars = _panel(rho=0.10, n=900, k=3, seed=3)
    idx = list(bars.values())[0].index
    sig = pd.DataFrame(index=idx, columns=pd.MultiIndex.from_product([list(bars), ["enter", "stop", "target"]]),
                       dtype=float)
    for s in bars:
        sig[(s, "enter")] = 0.0
    first = list(bars)[0]
    c = bars[first]["close"]
    sig.iloc[400, sig.columns.get_loc((first, "enter"))] = 1.0
    sig.iloc[400, sig.columns.get_loc((first, "stop"))] = float(c.iloc[400]) * 0.97
    sig.iloc[400, sig.columns.get_loc((first, "target"))] = float(c.iloc[400]) * 1.06
    r = brackets.execute(bars, sig, universe=_uni(bars), start_equity=10_000.0,
                         cost_model=costmodels.ForexCosts(), kill_switch=False)
    assert len(r.trades) >= 1
    assert r.equity_paper.iloc[-1] >= r.equity.iloc[-1] - 1e-9


def test_walk_forward_reports_all_three_levels():
    bars = _panel(rho=0.10, n=1600, k=5, seed=6)
    from referee import validate
    rep = validate.walk_forward(bars, {"mom": controls.momentum_rule(k=3)}, bar="1d",
                                n_trials=1, uni=_uni(bars), cost_model=costmodels.ForexCosts())
    assert "sharpe_paper" in rep
    assert rep["sharpe_paper"] >= rep["sharpe_gross"] >= rep["sharpe_net"] - 1e-9
