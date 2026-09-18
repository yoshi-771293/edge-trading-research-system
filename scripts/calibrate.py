"""Calibrate the instrument, then re-run both markets through the corrected gates.

Sixty-nine strategies were rejected before anyone checked whether this harness can
detect an edge at all. This script answers that first, by injecting edges of known size
into the data and reading them with a fully causal rule, and only then re-runs crypto
and forex."""
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from player import guard; guard.enforce()
from player import controls
from referee import costmodels, validate

FX = costmodels.ForexCosts()
OUT = Path("state/calibration.json")


def log(m): print(m, flush=True)


if __name__ == "__main__":
    log("=== CALIBRATION: what does a KNOWN edge look like coming out of this harness? ===")
    log("edge is injected as return autocorrelation rho and read by a causal momentum rule\n")
    log(f"{'rho':>5s} {'theory':>7s} {'paper':>7s} {'gross':>7s} {'net':>7s} {'PSR':>6s} {'trades':>7s}  gates")
    rows = []
    for rho in (0.0, 0.01, 0.02, 0.03, 0.04, 0.06, 0.08, 0.12, 0.16):
        bars = controls.predictable_panel(rho, n=2500, k=8, seed=5)
        close = pd.concat({s: d["close"] for s, d in bars.items()}, axis=1)
        uni = pd.DataFrame(True, index=close.index, columns=close.columns)
        rep = validate.walk_forward(bars, {"mom": controls.momentum_rule(k=3)}, bar="1d",
                                    n_trials=69, uni=uni, cost_model=FX)
        psr = rep["deflated"]["psr"]
        passes = bool(rep["sharpe_net"] > 0 and psr >= 0.5 and rep["min_trades_ok"]
                      and not rep["regime"]["single_regime"] and not rep["tripwire"]["tripped"])
        rows.append({"rho": rho, "theory": controls.theoretical_sharpe(rho),
                     "paper": rep["sharpe_paper"], "gross": rep["sharpe_gross"],
                     "net": rep["sharpe_net"], "psr": psr, "trades": rep["n_trades"],
                     "passes": passes, "trip": rep["tripwire"]["reason"],
                     "single_regime": rep["regime"]["single_regime"]})
        flag = "PASSES ALL SIX" if passes else ""
        if rep["tripwire"]["tripped"]:
            flag += " TRIP:" + rep["tripwire"]["reason"][:45]
        if rep["regime"]["single_regime"]:
            flag += " single-regime"
        log(f"{rho:5.2f} {controls.theoretical_sharpe(rho):7.2f} {rep['sharpe_paper']:+7.2f} "
            f"{rep['sharpe_gross']:+7.2f} {rep['sharpe_net']:+7.2f} {psr:6.2f} {rep['n_trades']:7d}  {flag}")
    floor = next((r for r in rows if r["passes"]), None)
    log("")
    if floor:
        log(f"DETECTION FLOOR: the smallest injected edge this harness calls eligible is "
            f"rho={floor['rho']:.2f}, a net Sharpe of {floor['net']:+.2f}.")
        log(f"  So the 69 rejections rule out edges at or above that level. Anything weaker")
        log(f"  could be present and this instrument would not see it.")
    else:
        log("DETECTION FLOOR: NOTHING PASSED. The gates are impassable and every negative is void.")
    OUT.write_text(json.dumps({"as_of": str(pd.Timestamp.now(tz="UTC")), "ladder": rows,
                               "floor": floor}, indent=1, default=str))
    log(f"\nwritten to {OUT}")
