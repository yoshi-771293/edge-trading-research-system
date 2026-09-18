"""Weekly: re-search on all data to date, propose ONE challenger, and judge
challenger vs incumbent on forward data only, with margins fixed in advance."""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from referee import data as refdata
from live import store

MIN_WEEKS = 8
MIN_TRADES = 30
SHARPE_MARGIN = 0.30


def _forward(db, sid, since: pd.Timestamp, now: pd.Timestamp):
    eq = pd.read_sql("SELECT time, twr AS equity FROM equity WHERE strategy_id=? AND time>=? AND time<=? ORDER BY time", db,
                     params=(sid, str(since), str(now)))
    n_tr = db.execute("SELECT count(*) FROM trades WHERE strategy_id=? AND time>=? AND time<=?", (sid, str(since), str(now))).fetchone()[0]
    if len(eq) < 3:
        return {"sharpe": 0.0, "ret": 0.0, "n": len(eq), "trades": n_tr}
    e = eq.set_index(pd.to_datetime(eq["time"], utc=True))["equity"]
    daily = e.resample("1D").last().dropna()
    r = daily.pct_change().dropna()
    sh = float(r.mean() / r.std() * np.sqrt(365)) if len(r) > 2 and r.std() > 0 else 0.0
    return {"sharpe": sh, "ret": float(e.iloc[-1] / e.iloc[0] - 1), "n": int(len(daily)), "trades": int(n_tr)}


def decide(db, now: pd.Timestamp) -> dict:
    champ, chall = store.get_state(db, "champion"), store.get_state(db, "challenger")
    if not chall:
        return {"action": "hold", "reason": "no challenger"}
    since = pd.Timestamp(chall["started"], tz="UTC") if pd.Timestamp(chall["started"]).tzinfo is None else pd.Timestamp(chall["started"])
    weeks = (now - since).days / 7
    a, b = _forward(db, "champion", since, now), _forward(db, "challenger", since, now)
    if weeks < MIN_WEEKS:
        return {"action": "hold", "reason": f"{weeks:.1f} of {MIN_WEEKS} weeks of shared forward data", "incumbent": a, "challenger": b}
    if a["trades"] < MIN_TRADES or b["trades"] < MIN_TRADES:
        if weeks < MIN_WEEKS * 2:
            return {"action": "hold", "reason": f"trades {a['trades']}/{b['trades']} < {MIN_TRADES}", "incumbent": a, "challenger": b}
    reason = (f"forward window {since.date()}..{now.date()} ({weeks:.1f} weeks): incumbent net Sharpe {a['sharpe']:+.2f} "
              f"({a['trades']} trades, {a['ret']:+.1%}); challenger net Sharpe {b['sharpe']:+.2f} ({b['trades']} trades, {b['ret']:+.1%}); "
              f"required margin +{SHARPE_MARGIN}")
    if b["sharpe"] >= a["sharpe"] + SHARPE_MARGIN and b["trades"] >= MIN_TRADES:
        store.lineage(db, now, "demote", champ["strategy"], "beaten: " + reason)
        store.lineage(db, now, "promote", chall["strategy"], reason)
        new = {"strategy": chall["strategy"], "started": str(now), "promoted_from": champ["strategy"].get("file"),
               "cash": champ.get("cash"), "cash_g": champ.get("cash_g"), "units": champ.get("units"), "units_g": champ.get("units_g"),
               "peak": champ.get("peak"), "halted": False, "pending": None, "last_bar": champ.get("last_bar"), "symbols": champ.get("symbols")}
        store.set_state(db, "champion", new); store.set_state(db, "challenger", None)
        store.journal(db, "champion", now, "PROMOTION: " + reason)
        return {"action": "promote", "reason": reason, "incumbent": a, "challenger": b}
    store.lineage(db, now, "demote_challenger", chall["strategy"], "failed to clear margin: " + reason)
    store.set_state(db, "challenger", None)
    store.journal(db, "challenger", now, "CHALLENGER DEMOTED: " + reason)
    return {"action": "demote_challenger", "reason": reason, "incumbent": a, "challenger": b}


def _search_top(now: pd.Timestamp, verbose: bool = False):
    """Re-run the search on all data to date; return (frozen top eligible, n_trials).
    Split out so the tournament logic can be tested without a 7-minute search."""
    from player import search
    out = search.run(now=now, allow_holdout=True, monthly_deposit=100.0, verbose=verbose)
    top = next((r for r in out["shortlist"] if r["eligible"]), None)
    if top is None:
        return None, out["n_trials"]
    return search.freeze_champion(top, out["n_trials"], now), out["n_trials"]


def propose(db, now: pd.Timestamp, verbose=False) -> dict:
    """Weekly. With an empty champion slot, the first eligible candidate is SEATED as
    champion (there is no incumbent to beat). With a champion in place, the top
    eligible non-incumbent becomes the single challenger."""
    champ = store.get_state(db, "champion")
    if champ and store.get_state(db, "challenger"):
        return {"action": "none", "reason": "challenger slot occupied"}
    frozen, n_trials = _search_top(now, verbose=verbose)
    if frozen is None:
        store.lineage(db, now, "no_champion" if not champ else "no_challenger", {},
                      f"no eligible candidate this week out of {n_trials} tried")
        return {"action": "none", "reason": "no eligible candidate"}
    inc = (champ or {}).get("strategy", {})
    if not champ:
        store.set_state(db, "champion", {"strategy": frozen, "started": str(now)})
        store.lineage(db, now, "seated", frozen,
                      f"champion slot was empty; first eligible candidate seated out of {n_trials} tried")
        store.journal(db, "champion", now, f"SEATED: {frozen['family']} on {frozen['bar']} bars becomes champion.")
        return {"action": "seated", "strategy": frozen}
    if (frozen["family"], str(frozen["param"]), frozen["bar"]) == (inc.get("family"), str(inc.get("param")), inc.get("bar")):
        store.lineage(db, now, "no_challenger", {}, "best candidate is the incumbent")
        return {"action": "none", "reason": "best candidate is the incumbent"}
    store.set_state(db, "challenger", {"strategy": frozen, "started": str(now)})
    store.lineage(db, now, "challenger_proposed", frozen,
                  f"top eligible non-incumbent out of {n_trials} tried")
    return {"action": "proposed", "strategy": frozen}
