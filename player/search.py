"""Phase 1 search over a point-in-time, survivorship-free universe.

Loads every archived USDT pair, builds the top-N-by-dollar-volume universe as it
existed on each date (dead coins included for as long as they really traded), scores
every family through the referee's selection-honest walk-forward, corrects for the
number of variants tried, ranks, and FREEZES the champion to a read-only file.
"""
from __future__ import annotations
import glob
import json
import os
import stat
from pathlib import Path

import numpy as np
import pandas as pd

from referee import archive, universe, validate
from player import families

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
BARS = list(families.BARS)
TOP_N = 30
MIN_HISTORY_DAYS = 90
VOLUME_WINDOW = 30
MIN_PSR = 0.50
HOLDOUT_START = "2026-09-16"          # live forward test begins here; the search never sees it


def cached_symbols(bar: str) -> list[str]:
    return sorted(Path(p).name.replace(f"_{bar}.csv.gz", "")
                  for p in glob.glob(str(archive.BARS_DIR / f"*_{bar}.csv.gz")))


def load_bars(bar: str, symbols: list[str] | None = None, allow_holdout: bool = False,
              clean: bool = True) -> dict[str, pd.DataFrame]:
    """Load cached bars, apply the holdout gate, then the referee's integrity gate
    (spot only, no trading across a reused ticker)."""
    syms = symbols if symbols is not None else cached_symbols(bar)
    cutoff = pd.Timestamp(HOLDOUT_START, tz="UTC")
    all_syms = cached_symbols(bar) or syms
    out = {}
    for s in syms:
        p = archive.BARS_DIR / f"{s}_{bar}.csv.gz"
        if not p.exists():
            continue
        d = pd.read_csv(p, index_col="time", parse_dates=["time"])
        if d.index.tz is None:
            d.index = d.index.tz_localize("UTC")
        if not allow_holdout:
            d = d[d.index < cutoff]
        if len(d) > 5:
            out[s] = d
    if clean:
        min_bars = {"1h": 2000, "4h": 500, "1d": 120, "1w": 30}.get(bar, 120)
        out = universe.clean(out, all_syms, min_bars=min_bars)
    return out


def load_universe(bar: str = "1d", top_n: int = TOP_N, allow_holdout: bool = False,
                  symbols: list[str] | None = None):
    bars = load_bars(bar, symbols, allow_holdout)
    uni = universe.build(bars, top_n=top_n, min_history_days=MIN_HISTORY_DAYS,
                         volume_window=VOLUME_WINDOW)
    return bars, uni


def project_universe(uni_daily: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Carry the daily membership decision onto a faster or slower bar index.
    Row D of the daily universe was decided from data < D, so forward-filling it
    within day D introduces no look-ahead."""
    return uni_daily.reindex(uni_daily.index.union(index)).ffill().reindex(index).fillna(False).astype(bool)


def universe_start(uni: pd.DataFrame, top_n: int = TOP_N, fill: float = 0.8) -> pd.Timestamp:
    """First date from which the universe stays at least `fill` of its target size."""
    size = uni.sum(axis=1)
    ok = size >= top_n * fill
    if not ok.any():
        return uni.index[0]
    # earliest date after which it never drops below the threshold again
    bad = size[~ok]
    return uni.index[0] if len(bad) == 0 else (bad.index[-1] + pd.Timedelta(days=1))


def ever_selected(uni: pd.DataFrame) -> list[str]:
    return sorted(uni.columns[uni.any()].tolist())


def _why(rep) -> str:
    r = []
    if not rep.get("causality", {}).get("passed", True):
        r.append("FAILED CAUSALITY: " + rep["causality"].get("detail", ""))
    if rep.get("tripwire", {}).get("tripped"):
        r.append("TRIPWIRE: " + rep["tripwire"]["reason"])
    if not rep.get("min_trades_ok", False):
        r.append(f"trades {rep.get('n_trades', 0)} < {validate.MIN_TRADES}")
    if rep.get("sharpe_net", 0) <= 0:
        r.append("net Sharpe <= 0")
    d = rep.get("deflated", {})
    if d.get("psr", 0) < MIN_PSR:
        r.append(f"deflated: PSR {d.get('psr', 0):.2f} < {MIN_PSR} (expected max noise Sharpe {d.get('expected_max_sharpe', 0):.2f})")
    if rep.get("regime", {}).get("single_regime"):
        r.append(f"single-regime: earns only in {rep['regime']['dominant']}")
    return "; ".join(r) or "eligible"


def run(now: pd.Timestamp | None = None, allow_holdout: bool = False, monthly_deposit: float = 0.0,
        bars_to_try: list[str] | None = None, verbose: bool = True,
        venue: str | None = None, style: str = "taker") -> dict:
    now = now or pd.Timestamp.now(tz="UTC")
    bar_list = bars_to_try or BARS
    n_trials = families.candidate_count(bars=bar_list)

    if verbose:
        print(f"building point-in-time universe (top {TOP_N} by 30d dollar volume) ...", flush=True)
    daily_bars, uni_daily = load_universe("1d", allow_holdout=allow_holdout)
    used = ever_selected(uni_daily)
    start = universe_start(uni_daily)
    if verbose:
        print(f"  {len(daily_bars)} pairs loaded, {len(used)} ever selected, "
              f"universe full from {start.date()}, last bar {uni_daily.index[-1].date()}", flush=True)

    rows = []
    for bar in bar_list:
        bars = daily_bars if bar == "1d" else load_bars(bar, used, allow_holdout)
        if not bars:
            continue
        idx = universe.master_index(bars)
        idx = idx[idx >= start]
        uni = uni_daily if bar == "1d" else project_universe(uni_daily, idx)
        if bar == "1d":
            uni = uni.loc[uni.index >= start]
        close_index = idx
        for fam, spec in families.FAMILIES.items():
            variants = {p: families.make_rule(fam, p, uni) for p in spec["grid"]}
            sub = {s: d[d.index >= start] for s, d in bars.items()}
            rep = validate.walk_forward(sub, variants, bar=bar, n_trials=n_trials, uni=uni,
                                        monthly_deposit=monthly_deposit, venue=venue, style=style)
            psr = rep.get("deflated", {}).get("psr", 0.0)
            eligible = bool(rep.get("eligible") and psr >= MIN_PSR
                            and not rep.get("regime", {}).get("single_regime"))
            row = {"family": fam, "bar": bar, "param": rep.get("last_param"), "eligible": eligible,
                   "rank_score": psr + (0.0 if eligible else -1.0) + 0.001 * (rep.get("sharpe_net") or 0.0),
                   "why": _why(rep) if not eligible else "eligible",
                   **{k: rep.get(k) for k in ["sharpe_net", "sharpe_gross", "oos_net_ret", "oos_gross_ret", "min_trades_ok",
                                              "oos_max_dd", "windows_positive", "n_windows", "n_trades",
                                              "deflated", "regime", "tripwire", "causality", "chosen_params",
                                              "oos_index"]}}
            rows.append(row)
            if verbose:
                print(f"{bar:3s} {fam:19s} net Sh {row['sharpe_net'] or 0:+.2f} gross {row['sharpe_gross'] or 0:+.2f} "
                      f"PSR {psr:.2f} trades {row['n_trades'] or 0:5d} win% {(row['windows_positive'] or 0):.0%}  {row['why']}", flush=True)

    rows.sort(key=lambda r: -r["rank_score"])
    ts = now.strftime("%Y%m%d_%H%M%S")
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / f"shortlist_{ts}.json").write_text(json.dumps(
        {"as_of": str(now), "n_trials": n_trials, "top_n": TOP_N, "universe_start": str(start),
         "venue": venue or "binance", "style": style,
         "symbols_ever_selected": used, "shortlist": rows}, indent=1, default=str))
    top = next((r for r in rows if r["eligible"]), None)
    champion = freeze_champion(top, n_trials, now, used) if top else None
    if not top:
        (STATE_DIR / f"no_champion_{ts}.json").write_text(json.dumps(
            {"as_of": str(now), "reason": "no eligible candidate"}, indent=1))
    return {"n_trials": n_trials, "shortlist": rows, "champion": champion, "universe_start": str(start)}


def freeze_champion(row: dict, n_trials: int, now: pd.Timestamp, symbols: list[str] | None = None) -> dict:
    """Write an immutable, read-only champion file. Never edited afterwards."""
    ts = now.strftime("%Y%m%d_%H%M%S")
    champion = {"frozen_at": str(now), "family": row["family"], "param": row["param"], "bar": row["bar"],
                "n_trials": n_trials, "top_n": TOP_N,
                "expectation": {k: row.get(k) for k in ["sharpe_net", "sharpe_gross", "oos_net_ret",
                                                        "oos_max_dd", "windows_positive", "n_trades", "deflated"]},
                "regime": row.get("regime"),
                "data_end": row["oos_index"][1] if row.get("oos_index") else None,
                "symbols_ever_selected": symbols or []}
    STATE_DIR.mkdir(exist_ok=True)
    f = STATE_DIR / f"champion_{ts}.json"
    f.write_text(json.dumps(champion, indent=1, default=str))
    os.chmod(f, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    champion["file"] = str(f)
    return champion
