"""The full harness on forex: the seven weight-based families and the engulfing
bracket setup, walk-forward, on MEASURED spreads with commission and financing, $1,000
plus $100 a month, against cash and an equal-weight basket, through the six gates.

Why the benchmark is different here. Bitcoin had a huge positive drift, so "beat
buy-and-hold" was a high bar. Currencies have no such drift: a basket of majors held
against the dollar goes roughly nowhere over twenty years, and holding it costs
financing. So the honest benchmarks are CASH (a return of zero) and that basket, and
the real test is the six gates, above all the multiple-testing one.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from player import guard; guard.enforce()
from player import families, setups
from referee import brackets, costmodels, forex, replay, validate

START, DEPOSIT = 1000.0, 100.0
TOL = 0.15                     # share of expected months a pair may lack (earliest history)
CM = costmodels.ForexCosts()
OUT = Path("state/fx_results.json")


def log(msg):
    print(msg, flush=True)


def load_panel():
    """Hourly -> forex days, completeness-gated, aligned to the common date range."""
    hourly = forex.load(daily=False)
    now = pd.Timestamp.now(tz="UTC")
    daily = {}
    for s, h in hourly.items():
        rep = forex.completeness(h, 2005, now)
        try:
            forex.assert_complete(h, 2005, now, tolerance=TOL)
        except ValueError as e:
            log(f"  EXCLUDED {s}: {e}")
            continue
        d = forex.to_daily(h)
        d["quote_volume"] = d["volume"]
        daily[s] = d
        log(f"  {s}: {len(d):,} forex days {d.index[0].date()}..{d.index[-1].date()}, "
            f"coverage {rep['coverage']:.1%}, median half-spread {h['half_spread'].median()*1e4:.3f} bp, "
            f"open-hour {d['open_half_spread'].median()*1e4:.3f} bp")
    # UNION of dates, not intersection: one pair's gap must not delete those days for
    # every other pair. A missing bar is NaN, which both engines treat as untradable.
    idx = None
    for d in daily.values():
        idx = d.index if idx is None else idx.union(d.index)
    idx = idx.sort_values()
    return {s: d.reindex(idx) for s, d in daily.items()}, idx


def benchmarks(bars, idx):
    syms = list(bars)
    cash = pd.Series(1.0, index=idx)
    tgt = pd.DataFrame(np.nan, index=idx, columns=syms)
    tgt.iloc[0] = 1.0 / len(syms)
    uni = pd.DataFrame(True, index=idx, columns=syms)
    basket = replay.execute(bars, tgt, universe=uni, start_equity=START, monthly_deposit=DEPOSIT,
                            kill_switch=False, apply_risk=False, cost_model=CM)
    return cash, basket


def gates(net_r, n_trials, n_trades, ppy, bars, viol=0):
    d = validate.deflated_sharpe(net_r.values, n_trials=n_trials, periods_per_year=ppy)
    trip = validate.tripwire(net_r, ppy, level_violations=viol,
                             benchmark_returns=validate.benchmark_daily_returns(bars))
    seg = validate.segment_by_regime(net_r, validate._daily_labels(bars, net_r.index))
    sh = float(net_r.mean() / net_r.std() * np.sqrt(ppy)) if net_r.std() > 0 else 0.0
    return {"sharpe_net": sh, "psr": d["psr"], "luck_sharpe": d["expected_max_sharpe"],
            "n_trades": n_trades, "min_trades_ok": n_trades >= validate.MIN_TRADES,
            "single_regime": seg["single_regime"], "dominant": seg.get("dominant"),
            "dominant_share": seg.get("dominant_share", 0.0),
            "tripped": trip.tripped, "trip_reason": trip.reason,
            "eligible": bool(sh > 0 and d["psr"] >= 0.5 and n_trades >= validate.MIN_TRADES
                             and not seg["single_regime"] and not trip.tripped)}


def run_families(bars, idx, n_trials):
    uni = pd.DataFrame(True, index=idx, columns=list(bars))
    rows = []
    for fam, spec in families.FAMILIES.items():
        variants = {p: families.make_rule(fam, p, uni) for p in spec["grid"]}
        rep = validate.walk_forward(bars, variants, bar="1d", n_trials=n_trials, uni=uni,
                                    monthly_deposit=DEPOSIT, cost_model=CM)
        g = {k: rep.get(k) for k in ("sharpe_net", "sharpe_gross", "oos_net_ret", "oos_max_dd",
                                     "windows_positive", "n_windows", "n_trades", "eligible")}
        g["psr"] = rep.get("deflated", {}).get("psr")
        g["luck_sharpe"] = rep.get("deflated", {}).get("expected_max_sharpe")
        g["single_regime"] = rep.get("regime", {}).get("single_regime")
        g["dominant_share"] = rep.get("regime", {}).get("dominant_share")
        g["tripped"] = rep.get("tripwire", {}).get("tripped"); g["trip_reason"] = rep.get("tripwire", {}).get("reason")
        g["family"] = fam
        rows.append(g)
        log(f"  {fam:19s} netSh {g['sharpe_net'] or 0:+.2f} gross {g['sharpe_gross'] or 0:+.2f} "
            f"PSR {g['psr'] or 0:.2f} (luck {g['luck_sharpe'] or 0:+.2f}) trades {g['n_trades'] or 0:5d} "
            f"win% {(g['windows_positive'] or 0):.0%} DD {g['oos_max_dd'] or 0:+.0%} "
            f"{'ELIGIBLE' if g['eligible'] else ''}{' single-regime' if g['single_regime'] else ''}"
            f"{' TRIP:'+str(g['trip_reason'])[:40] if g['tripped'] else ''}")
    return rows


def run_engulfing(bars, idx, n_trials, risk_frac, both_sides, leverage=1.0):
    uni = pd.DataFrame(True, index=idx, columns=list(bars))
    wins = validate.windows(idx)
    runs = {}
    for i, g in enumerate(setups.GRID):
        sig = setups.trend_pullback_engulfing(bars, universe=uni, both_sides=both_sides, **g)
        runs[i] = brackets.execute(bars, sig, universe=uni, start_equity=START, risk_frac=risk_frac,
                                   cost_model=CM, kill_switch=False, leverage=leverage)
    frames, chosen = [], []
    for tr0, tr1, te0, te1 in wins:
        best, bs = None, -np.inf
        for i, r in runs.items():
            seg = r.twr[(r.twr.index >= tr0) & (r.twr.index <= tr1)]
            sh = replay.metrics(seg, 365)["sharpe"] if len(seg) > 2 else -np.inf
            if sh > bs:
                best, bs = i, sh
        sig = setups.trend_pullback_engulfing(bars, universe=uni, both_sides=both_sides, **setups.GRID[best])
        seg = sig[(sig.index >= te0) & (sig.index <= te1)]
        if len(seg):
            frames.append(seg); chosen.append(best)
    stitched = pd.concat(frames)
    r = brackets.execute(bars, stitched, universe=uni, start_equity=START, monthly_deposit=DEPOSIT,
                         risk_frac=risk_frac, cost_model=CM, kill_switch=True, leverage=leverage)
    r_nokill = brackets.execute(bars, stitched, universe=uni, start_equity=START, monthly_deposit=DEPOSIT,
                                risk_frac=risk_frac, cost_model=CM, kill_switch=False, leverage=leverage)
    net_r = r_nokill.twr.pct_change().dropna()
    viol = int((r_nokill.equity > r_nokill.equity_gross * (1 + 1e-9)).sum())
    ent = int((r_nokill.trades["reason"] == "entry").sum())
    g = gates(net_r, n_trials, ent, 365, bars, viol)
    active = (r.killed_at - r.equity.index[0]).days if r.killed_at is not None else (r.equity.index[-1] - r.equity.index[0]).days
    total = (r.equity.index[-1] - r.equity.index[0]).days
    out = {"risk_frac": risk_frac, "both_sides": both_sides, "leverage": leverage, "chosen": chosen,
           "paid_in": float(r.contributed.iloc[-1]), "value": float(r.equity.iloc[-1]),
           "profit": float(r.profit.iloc[-1]), "friction": float(r.total_costs),
           "killed_at": str(r.killed_at)[:10] if r.killed_at is not None else None,
           "days_active": active, "days_total": total,
           "entries": ent, "targets": int(r_nokill.n_targets), "stops": int(r_nokill.n_stops),
           "longs": int((r_nokill.trades.query("reason=='entry'")["units"] > 0).sum()),
           "shorts": int((r_nokill.trades.query("reason=='entry'")["units"] < 0).sum()),
           "n_capped": int(r_nokill.n_capped), "effective_risk": float(r_nokill.effective_risk_frac),
           "maxdd_nokill": float(replay.metrics(r_nokill.twr, 365)["max_dd"]),
           "value_nokill": float(r_nokill.equity.iloc[-1]), **g}
    wr = out["targets"] / max(out["targets"] + out["stops"], 1)
    log(f"  risk {risk_frac:.0%} {'both' if both_sides else 'long':4s} lev{leverage:>4.0f}: value ${out['value']:,.0f} "
        f"(no-kill ${out['value_nokill']:,.0f}) paid ${out['paid_in']:,.0f} | netSh {out['sharpe_net']:+.2f} "
        f"PSR {out['psr']:.2f} luck {out['luck_sharpe']:+.2f} | {ent} entries ({out['longs']}L/{out['shorts']}S) "
        f"win {wr:.0%} | DD {out['maxdd_nokill']:+.0%} | capped {out['n_capped']}/{ent} eff.risk {out['effective_risk']:.2%} "
        f"| {'KILLED '+out['killed_at'] if out['killed_at'] else 'never killed'} | "
        f"{'ELIGIBLE' if out['eligible'] else ''}{' single-regime' if out['single_regime'] else ''}"
        f"{' TRIP:'+out['trip_reason'][:40] if out['tripped'] else ''}")
    return out


if __name__ == "__main__":
    log("=== loading forex panel ===")
    bars, idx = load_panel()
    log(f"panel: {len(bars)} pairs x {len(idx):,} forex days, {idx[0].date()}..{idx[-1].date()}")
    cash, basket = benchmarks(bars, idx)
    mb = replay.metrics(basket.twr, 365)
    log(f"benchmark basket (equal-weight long all pairs, financed): value ${basket.equity.iloc[-1]:,.0f} "
        f"from ${basket.contributed.iloc[-1]:,.0f} paid in, Sharpe {mb['sharpe']:+.2f}, DD {mb['max_dd']:+.0%}")
    n_fam = families.candidate_count(bars=["1d"])
    n_eng = len(setups.GRID) * 2 * 2 * 2      # grid x risk levels x sides x leverage
    n_trials = n_fam + n_eng
    log(f"\n=== seven families, walk-forward, n_trials={n_trials} ===")
    fam_rows = run_families(bars, idx, n_trials)
    log(f"\n=== engulfing bracket setup, walk-forward, n_trials={n_trials} ===")
    eng_rows = [run_engulfing(bars, idx, n_trials, rf, bs, lev)
                for rf in (0.01, 0.02) for bs in (False, True) for lev in (1.0, 10.0)]
    OUT.write_text(json.dumps({"as_of": str(pd.Timestamp.now(tz='UTC')), "pairs": list(bars),
                               "period": [str(idx[0].date()), str(idx[-1].date())], "n_trials": n_trials,
                               "benchmark_basket": {"value": float(basket.equity.iloc[-1]),
                                                    "paid_in": float(basket.contributed.iloc[-1]), **mb},
                               "families": fam_rows, "engulfing": eng_rows}, indent=1, default=str))
    elig = [r for r in fam_rows + eng_rows if r.get("eligible")]
    log(f"\nELIGIBLE: {len(elig)} of {len(fam_rows) + len(eng_rows)}")
    log("DONE")
