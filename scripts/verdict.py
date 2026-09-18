"""Phase 3: the year-end verdict. Equity vs BTC buy-and-hold net of costs, champion
lineage, and for every champion the gap between backtest expectation and live result."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from player import guard; guard.enforce()
from live import store, dashboard
from referee import data as refdata, replay

db = store.connect()
eq = pd.read_sql("SELECT time, equity, gross FROM equity WHERE strategy_id='champion' ORDER BY time", db)
if len(eq) < 2:
    print("No live history yet."); sys.exit(0)
eq["time"] = pd.to_datetime(eq["time"], utc=True); eq = eq.set_index("time")
daily = eq["equity"].resample("1D").last().dropna()
bars = refdata.load("1d", allow_holdout=True)
b0, b1 = daily.index[0], daily.index[-1]
bh = replay.buy_and_hold({s: d[(d.index >= b0) & (d.index <= b1)] for s, d in bars.items()}, {"BTCUSDT": 1.0}, 1000.0)
ma, mb = replay.metrics(daily, 365), replay.metrics(bh.equity, 365)
lineage = pd.read_sql("SELECT time, event, strategy, reason FROM lineage ORDER BY id", db)
gaps = dashboard.backtest_vs_live(db)
out = ["# Edge Tournament verdict", f"Period {b0.date()} to {b1.date()} ({len(daily)} days), net of all modelled costs.", "",
       "| | Agent (champion lineage) | BTC buy-and-hold |", "|---|---|---|",
       f"| Return | {ma['ret']:+.1%} | {mb['ret']:+.1%} |", f"| Sharpe | {ma['sharpe']:.2f} | {mb['sharpe']:.2f} |",
       f"| Max drawdown | {ma['max_dd']:.1%} | {mb['max_dd']:.1%} |",
       f"| Gross (before costs) | {eq['gross'].iloc[-1] / eq['gross'].iloc[0] - 1:+.1%} | |", "",
       "## Backtest expectation vs live (the honest number)", "", "| Champion | Expected net Sharpe | Live net Sharpe | Gap | Live days |", "|---|---|---|---|---|"]
for g in gaps:
    out.append(f"| {g['name']} | {g['expected']:+.2f} | {g['live']:+.2f} | {g['gap']:+.2f} | {g['days']} |")
out += ["", "## Champion lineage", ""]
for _, r in lineage.iterrows():
    s = json.loads(r["strategy"]) if r["strategy"] else {}
    out.append(f"- {r['time'][:10]} **{r['event']}** {s.get('family','')}({s.get('param','')}) on {s.get('bar','')}: {r['reason']}")
beat = ma["ret"] > mb["ret"]
out += ["", "## Verdict", "", ("The agent beat BTC buy-and-hold net of costs." if beat else "The agent did NOT beat BTC buy-and-hold net of costs."),
        "Judge it on the gap table: a strategy whose live Sharpe lands far below its backtest expectation had no edge, whatever the equity curve did."]
Path("docs").mkdir(exist_ok=True); Path("docs/VERDICT.md").write_text("\n".join(out)); print("\n".join(out))
