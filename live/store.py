"""SQLite state for the live tournament. Two strategy slots: 'champion' (scored)
and 'challenger' (shadow)."""
import json, sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "state" / "tournament.sqlite"
SCHEMA = """
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS equity (strategy_id TEXT, time TEXT, equity REAL, gross REAL, cash REAL, exposure REAL, drawdown REAL, contributed REAL, profit REAL, twr REAL, PRIMARY KEY(strategy_id, time));
CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_id TEXT, time TEXT, symbol TEXT, side TEXT, usd REAL, units REAL, fill REAL, ref_open REAL, fee REAL, slippage REAL, style TEXT);
CREATE TABLE IF NOT EXISTS decisions (strategy_id TEXT, time TEXT, targets TEXT, reasoning TEXT, PRIMARY KEY(strategy_id, time));
CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, strategy_id TEXT, entry TEXT);
CREATE TABLE IF NOT EXISTS lineage (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, event TEXT, strategy TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS errors (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, where_ TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS anomalies (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, strategy_id TEXT, reason TEXT);
"""


def connect(path=None):
    p = Path(path or DB_PATH); p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p)); con.executescript(SCHEMA)
    return con


def get_state(con, key, default=None):
    row = con.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_state(con, key, value):
    if value is None:
        con.execute("DELETE FROM state WHERE key=?", (key,))
    else:
        con.execute("INSERT OR REPLACE INTO state(key,value) VALUES(?,?)", (key, json.dumps(value, default=str)))
    con.commit()


def journal(con, sid, time, entry):
    con.execute("INSERT INTO journal(time,strategy_id,entry) VALUES(?,?,?)", (str(time), sid, entry)); con.commit()


def lineage(con, time, event, strategy, reason):
    con.execute("INSERT INTO lineage(time,event,strategy,reason) VALUES(?,?,?,?)", (str(time), event, json.dumps(strategy, default=str), reason)); con.commit()
