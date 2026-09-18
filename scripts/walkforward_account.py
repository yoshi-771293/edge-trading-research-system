"""What the account would ACTUALLY have done, in dollars.

A true walk-forward deployment: on each training window the best parameter is chosen,
then the account carries on into the next unseen window using that parameter, with
$100 arriving every month throughout. One continuous account, parameters switching at
window boundaries, nothing chosen with hindsight.
"""
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from player import guard; guard.enforce()
from player import search, families
from referee import replay, validate

START, DEPOSIT = 1000.0, 100.0


def walkforward_targets(bars, variants, uni, bar):
    """Stitch per-window target frames using only train-window information."""
    close = validate._close(bars)
    ppy = {"4h": 6 * 365, "1d": 365, "1w": 52}[bar]
    runs = {p: replay.execute(bars, r(close), universe=uni, start_equity=START, kill_switch=False)
            for p, r in variants.items()}
    frames, chosen = [], []
    for tr0, tr1, te0, te1 in validate.windows(close.index):
        best, best_sh = None, -np.inf
        for p, r in runs.items():
            seg = r.twr[(r.twr.index >= tr0) & (r.twr.index <= tr1)]
            sh = replay.metrics(seg, ppy)["sharpe"] if len(seg) > 2 else -np.inf
            if sh > best_sh:
                best, best_sh = p, sh
        tg = variants[best](close)
        rows = tg[(tg.index >= te0) & (tg.index <= te1)]
        if len(rows):
            frames.append(rows); chosen.append((str(te0.date()), best))
    return (pd.concat(frames) if frames else pd.DataFrame()), chosen


def run_one(bars, uni, fam, bar):
    variants = {p: families.make_rule(fam, p, uni) for p in families.FAMILIES[fam]["grid"]}
    tgt, chosen = walkforward_targets(bars, variants, uni, bar)
    if not len(tgt):
        return None
    r = replay.execute(bars, tgt, universe=uni, start_equity=START, monthly_deposit=DEPOSIT)
    ppy = {"4h": 6 * 365, "1d": 365, "1w": 52}[bar]
    m = replay.metrics(r.twr, ppy)
    daily = r.equity.resample("1D").last().dropna()
    dd_dollars = float((r.equity - r.equity.cummax()).min())
    return {"family": fam, "bar": bar, "chosen": chosen,
            "paid_in": float(r.contributed.iloc[-1]), "final": float(r.equity.iloc[-1]),
            "profit": float(r.profit.iloc[-1]), "gross_final": float(r.equity_gross.iloc[-1]),
            "friction": float(r.total_costs), "trades": int(len(r.trades)),
            "sharpe": m["sharpe"], "worst_dip_pct": m["max_dd"], "worst_dip_dollars": dd_dollars,
            "killed_at": str(r.killed_at) if r.killed_at is not None else None,
            "equity": r.equity, "contributed": r.contributed, "gross": r.equity_gross,
            "winning_days": float((r.twr.pct_change().dropna() > 0).mean())}


if __name__ == "__main__":
    bars_d, uni_d = search.load_universe("1d")
    start = search.universe_start(uni_d)
    uni_d = uni_d.loc[uni_d.index >= start]
    sub_d = {s: d[d.index >= start] for s, d in bars_d.items()}
    used = search.ever_selected(uni_d)

    # Benchmark: the same money, the same days, into Bitcoin
    bh = replay.buy_and_hold_dca({"BTCUSDT": sub_d["BTCUSDT"]}, "BTCUSDT", START, monthly_deposit=DEPOSIT)
    print(f"PERIOD {start.date()} .. {uni_d.index[-1].date()}")
    print(f"BITCOIN (same deposits): paid ${bh.contributed.iloc[-1]:,.0f} -> ${bh.equity.iloc[-1]:,.0f} "
          f"profit ${bh.profit.iloc[-1]:+,.0f} | Sharpe {replay.metrics(bh.twr,365)['sharpe']:.2f} "
          f"| worst dip {replay.metrics(bh.twr,365)['max_dd']:.0%}")

    results = []
    for bar in ["1d", "1w", "4h"]:
        bars = sub_d if bar == "1d" else {s: d[d.index >= start] for s, d in
                                         search.load_bars(bar, used).items()}
        if not bars:
            continue
        idx = validate._close(bars).index
        uni = uni_d if bar == "1d" else search.project_universe(uni_d, idx)
        for fam in families.FAMILIES:
            out = run_one(bars, uni, fam, bar)
            if out:
                results.append(out)
                print(f"{bar:3s} {fam:19s} paid ${out['paid_in']:>7,.0f} -> ${out['final']:>9,.0f} "
                      f"profit ${out['profit']:>+9,.0f} | before costs ${out['gross_final']:>10,.0f} "
                      f"| friction ${out['friction']:>8,.0f} | {out['trades']:>6,d} trades "
                      f"| Sharpe {out['sharpe']:+.2f} | worst dip {out['worst_dip_pct']:.0%}"
                      f"{'  KILLED ' + out['killed_at'][:10] if out['killed_at'] else ''}", flush=True)

    payload = {"period": [str(start.date()), str(uni_d.index[-1].date())],
               "benchmark": {"paid_in": float(bh.contributed.iloc[-1]), "final": float(bh.equity.iloc[-1]),
                             "profit": float(bh.profit.iloc[-1]),
                             "sharpe": replay.metrics(bh.twr, 365)["sharpe"],
                             "worst_dip_pct": replay.metrics(bh.twr, 365)["max_dd"]},
               "results": [{k: v for k, v in r.items() if k not in ("equity", "contributed", "gross")}
                           for r in results]}
    Path("state/walkforward_accounts.json").write_text(json.dumps(payload, indent=1, default=str))
    # curves for the chart: the best by profit, plus benchmark and contributions
    best = max(results, key=lambda r: r["profit"])
    curves = pd.DataFrame({
        "paid_in": best["contributed"].resample("1D").last().ffill(),
        "best_net": best["equity"].resample("1D").last().ffill(),
        "best_gross": best["gross"].resample("1D").last().ffill(),
        "bitcoin": bh.equity.resample("1D").last().ffill(),
    }).dropna()
    curves.to_csv("state/walkforward_curves.csv")
    print(f"\nBEST BY PROFIT: {best['family']} on {best['bar']} -> ${best['final']:,.0f} "
          f"(profit ${best['profit']:+,.0f}) vs Bitcoin ${bh.equity.iloc[-1]:,.0f}")
