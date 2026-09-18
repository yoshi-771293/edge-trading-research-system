"""launchd entry points. `python -m live.run hourly|weekly|status|bootstrap`."""
import glob, json, sys
import pandas as pd
from player import guard
guard.enforce()                                            # referee integrity first, always
from live import agent, dashboard, digest, notify, store
from player import tournament


def bootstrap(db):
    """Seed the champion slot from the newest frozen champion file (Phase 1 output)."""
    files = sorted(glob.glob(str(store.DB_PATH.parent / "champion_*.json")))
    if not files:
        print("no champion file"); return
    strat = json.loads(open(files[-1]).read()); strat["file"] = files[-1]
    now = pd.Timestamp.now(tz="UTC")
    store.set_state(db, "champion", {"strategy": strat, "started": str(now)})
    store.lineage(db, now, "freeze", strat, f"initial champion from Phase 1 search: expected net Sharpe {strat['expectation']['sharpe_net']:+.2f}, PSR {strat['expectation']['deflated']['psr']:.2f}, {strat['expectation']['n_trades']} OOS trades over {strat['n_trials']} trials")
    print("champion seeded:", strat["family"], strat["param"], strat["bar"])


def hourly(db):
    for sid in ["champion", "challenger"]:
        if store.get_state(db, sid):
            print(sid, json.dumps(agent.safe_cycle(db, sid), default=str))
    print(dashboard.write(db))


def weekly(db):
    now = pd.Timestamp.now(tz="UTC")
    print("judge:", json.dumps(tournament.decide(db, now), default=str))
    try:
        print("propose:", json.dumps(tournament.propose(db, now), default=str)[:300])
    except Exception as e:
        db.execute("INSERT INTO errors(time,where_,message) VALUES(?,?,?)", (str(now), "weekly:propose", repr(e))); db.commit()
        print("propose failed:", e)
    text = digest.compose(db, now)
    notify.digest("Edge Tournament weekly", text)
    store.journal(db, "champion", now, "WEEKLY DIGEST SENT: " + text.replace("\n", " ")[:500])
    print(dashboard.write(db))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "hourly"
    db = store.connect()
    {"hourly": hourly, "weekly": weekly, "bootstrap": bootstrap,
     "status": lambda db: print(store.get_state(db, "champion"))}[cmd](db)
