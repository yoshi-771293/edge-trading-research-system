"""Weekly digest text (< 1,200 chars) for the phone."""
import numpy as np, pandas as pd
from live import store, dashboard


def btc_daily_close():
    return dashboard.btc_daily_close()


def compose(db, now: pd.Timestamp) -> str:
    champ = store.get_state(db, "champion") or {}; s = champ.get("strategy", {})
    eq = dashboard._equity(db)
    if not len(eq):
        return "Edge Tournament: no live bars yet."
    daily = eq["equity"].resample("1D").last().dropna()
    week = daily[daily.index >= now - pd.Timedelta(days=7)]
    btc = btc_daily_close(); b = btc.reindex(daily.index, method="ffill")
    bh_ret = b.iloc[-1] / b.iloc[0] - 1; ret = daily.iloc[-1] / 1000 - 1
    wk = week.iloc[-1] / week.iloc[0] - 1 if len(week) > 1 else 0.0
    r = daily.pct_change().dropna(); sharpe = float(r.mean() / r.std() * np.sqrt(365)) if len(r) > 2 and r.std() > 0 else 0.0
    n_tr = db.execute("SELECT count(*) FROM trades WHERE strategy_id='champion' AND time>=?", (str(now - pd.Timedelta(days=7)),)).fetchone()[0]
    exp = float((s.get("expectation") or {}).get("sharpe_net") or 0)
    chall = store.get_state(db, "challenger")
    last_j = db.execute("SELECT entry FROM journal WHERE strategy_id='champion' ORDER BY id DESC LIMIT 1").fetchone()
    lin = db.execute("SELECT event FROM lineage WHERE time>=? ORDER BY id", (str(now - pd.Timedelta(days=7)),)).fetchall()
    paid_in = float(eq["contributed"].iloc[-1])
    pnl = daily.iloc[-1] - paid_in
    bh_val = paid_in * (1 + bh_ret)
    txt = (f"Trading bot, week to {now.date()}\n"
           f"Account: ${daily.iloc[-1]:,.0f}. You paid in ${paid_in:,.0f}, so profit is "
           f"{'+' if pnl >= 0 else '-'}${abs(pnl):,.0f} ({wk:+.1%} this week). "
           f"The same money in Bitcoin: ${bh_val:,.0f}.\n"
           f"Strategy: {s.get('family')} on {s.get('bar')} bars. Steadiness score {sharpe:+.2f} vs {exp:+.2f} promised by history. "
           f"{'STOPPED by the safety brake. ' if champ.get('halted') else ''}{n_tr} buys/sells this week.\n"
           f"Contender practising alongside: {chall['strategy']['family'] if chall else 'none'}. "
           f"Changes this week: {', '.join(e for (e,) in lin) or 'none'}.\n"
           f"Bot's note: {(last_j[0] if last_j else 'nothing recorded yet')[:250]}")
    return txt[:1190]
