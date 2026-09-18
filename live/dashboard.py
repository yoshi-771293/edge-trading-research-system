"""Static HTML dashboard from the tournament database. No external assets."""
from __future__ import annotations
import html, json, math
import numpy as np
import pandas as pd
from referee import data as refdata, regimes
from live import store

OUT = store.DB_PATH.parent / "dashboard.html"


def btc_daily_close() -> pd.Series:
    return refdata.load("1d", allow_holdout=True)["BTCUSDT"]["close"]


def _equity(db, sid="champion") -> pd.DataFrame:
    e = pd.read_sql("SELECT time, equity, gross, exposure, drawdown, contributed, profit, twr"
                    " FROM equity WHERE strategy_id=? ORDER BY time", db, params=(sid,))
    if len(e):
        e["time"] = pd.to_datetime(e["time"], utc=True); e = e.set_index("time")
    return e


def backtest_vs_live(db) -> list[dict]:
    """For each champion in the lineage: expected net Sharpe (from its frozen file) vs
    realised live net Sharpe over the period it was champion."""
    lin = pd.read_sql("SELECT time, event, strategy FROM lineage WHERE event IN ('freeze','promote') ORDER BY id", db)
    eq = _equity(db)
    out = []
    cur = store.get_state(db, "champion")
    rows = [(pd.Timestamp(r["time"]), json.loads(r["strategy"])) for _, r in lin.iterrows()]
    if not rows and cur:
        rows = [(pd.Timestamp(cur.get("started") or eq.index[0] if len(eq) else pd.Timestamp.now(tz="UTC")), cur["strategy"])]
    for i, (t0, s) in enumerate(rows):
        t1 = rows[i + 1][0] if i + 1 < len(rows) else None
        t0 = t0.tz_localize("UTC") if t0.tzinfo is None else t0
        seg = eq[(eq.index >= t0) & ((eq.index < (t1.tz_localize("UTC") if t1 is not None and t1.tzinfo is None else t1)) if t1 is not None else True)] if len(eq) else eq
        d = seg["equity"].resample("1D").last().dropna() if len(seg) else pd.Series(dtype=float)
        r = d.pct_change().dropna()
        live = float(r.mean() / r.std() * np.sqrt(365)) if len(r) > 2 and r.std() > 0 else 0.0
        expected = float((s.get("expectation") or {}).get("sharpe_net") or 0.0)
        out.append({"name": f"{s.get('family')}({s.get('param')}) {s.get('bar')}", "expected": expected, "live": live, "gap": live - expected, "days": int(len(d))})
    return out


def _svg(series: dict[str, pd.Series], w=960, h=320) -> str:
    pad_l, pad_r, pad_t, pad_b = 60, 110, 14, 26
    df = pd.concat(series, axis=1).dropna()
    if len(df) < 2:
        return "<p>Not enough data yet.</p>"
    x0, x1, y0, y1 = pad_l, w - pad_r, pad_t, h - pad_b
    vmin, vmax = df.min().min(), df.max().max(); vmax = vmax if vmax > vmin else vmin + 1
    xs = [x0 + (x1 - x0) * i / (len(df) - 1) for i in range(len(df))]
    y = lambda v: y1 - (y1 - y0) * (v - vmin) / (vmax - vmin)
    parts = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    for k in range(5):
        gv = vmin + (vmax - vmin) * k / 4
        parts.append(f'<line x1="{x0}" x2="{x1}" y1="{y(gv):.1f}" y2="{y(gv):.1f}" class="grid"/><text x="{x0-6}" y="{y(gv)+4:.1f}" class="tick" text-anchor="end">${gv:,.0f}</text>')
    for i in range(1, len(df)):
        if df.index[i].month != df.index[i - 1].month:
            parts.append(f'<text x="{xs[i]:.1f}" y="{h-8}" class="tick" text-anchor="middle">{df.index[i].strftime("%b %y")}</text>')
    for j, (name, col) in enumerate(df.items()):
        pts = " ".join(f"{xs[i]:.1f},{y(col.iloc[i]):.1f}" for i in range(len(df)))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="var(--s{j+1})" stroke-width="2" stroke-linejoin="round"/>')
        parts.append(f'<text x="{x1+6}" y="{y(col.iloc[-1])+4:.1f}" class="dl" fill="var(--s{j+1})">{html.escape(str(name))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _tile(label, value, sub="", cls=""):
    return f'<div class="tile {cls}"><div class="tl">{label}</div><div class="tv">{value}</div><div class="ts">{sub}</div></div>'


PLAIN = {
    "pullback": "buys Bitcoin or Ethereum when the price is in an uptrend but has just dipped for a few hours, and sells when the uptrend breaks",
    "sma_trend": "holds Bitcoin or Ethereum while the price is above its recent average, and sits in cash when it is below",
    "donchian": "buys when the price breaks above its recent high, sells when it falls below its recent low",
    "ema_cross": "buys when a fast price average crosses above a slow one, sells when it crosses back",
    "vol_trend": "like the trend rule, but buys less when the market is wild and more when it is calm",
    "rsi_meanrev": "buys short sharp dips inside an uptrend and sells after the bounce",
    "xs_mom": "holds whichever of Bitcoin or Ethereum has risen more lately, or cash if both are falling",
}
NAMES = {"BTCUSDT": "Bitcoin", "ETHUSDT": "Ethereum"}


def _money(x):
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def build(db) -> str:
    champ = store.get_state(db, "champion") or {}
    chall = store.get_state(db, "challenger")
    eq = _equity(db); ceq = _equity(db, "challenger")
    strat = champ.get("strategy", {})
    btc = btc_daily_close()
    START = 1000.0
    value = float(champ.get("equity") or (eq["equity"].iloc[-1] if len(eq) else START))
    paid_in = float(champ.get("contributed") or (eq["contributed"].iloc[-1] if len(eq) else START))
    pnl = value - paid_in
    fees = db.execute("SELECT coalesce(sum(fee+slippage),0) FROM trades WHERE strategy_id='champion'").fetchone()[0]
    n_trades = db.execute("SELECT count(*) FROM trades WHERE strategy_id='champion'").fetchone()[0]
    if len(eq) >= 2:
        daily = eq["equity"].resample("1D").last().dropna()
        contrib_d = eq["contributed"].resample("1D").last().ffill().reindex(daily.index).ffill()
        b = btc[(btc.index >= daily.index[0])].reindex(daily.index, method="ffill")
        # Bitcoin benchmark receives the SAME deposits on the same days, or the
        # comparison would be rigged in the bot's favour.
        add = contrib_d.diff().fillna(0.0); add.iloc[0] = contrib_d.iloc[0]
        bh = ((add / b).cumsum() * b) * (1 - 0.0016)
        series = {"This bot": daily, "Just buying Bitcoin": bh, "Money you paid in": contrib_d}
        if len(ceq) >= 2:
            series["Contender (practice only)"] = ceq["equity"].resample("1D").last().dropna()
        chart = _svg(series)
        twr_d = eq["twr"].resample("1D").last().dropna()
        r = twr_d.pct_change().dropna()
        sharpe = float(r.mean() / r.std() * np.sqrt(365)) if len(r) > 2 and r.std() > 0 else 0.0
        dd = float((twr_d / twr_d.cummax() - 1).min())
        last = eq.iloc[-1]
        bh_val = float(bh.iloc[-1]); bh_profit = bh_val - paid_in
        bh_line = (f"Putting the same money into Bitcoin instead would be worth {_money(bh_val)} today, "
                   f"a profit of {_money(bh_profit)}. This bot: {_money(value)}, profit {_money(pnl)}.")
        lab = regimes.label(btc).reindex(daily.index, method="ffill")
        reg_rows = []
        for k, g in r.groupby(lab["trend"].reindex(r.index)):
            reg_rows.append(f"<tr><td>{'Bitcoin rising (above its 200-day average)' if k == 'bull' else 'Bitcoin falling (below its 200-day average)'}</td><td>{len(g)}</td><td class='{'pos' if g.sum() >= 0 else 'neg'}'>{g.sum():+.1%}</td></tr>")
    else:
        chart = "<p>The chart appears after the first full day of trading.</p>"; sharpe = dd = 0.0; bh_line = "Bitcoin comparison appears after the first full day."; reg_rows = []
    has_strategy = bool(strat)
    if not has_strategy:
        status = ("<b>Not trading.</b> No strategy has passed the tests, so the account is deliberately "
                  "sitting in cash rather than trading something the evidence says does not work. "
                  "The search re-runs every Sunday and will start trading only if a strategy clears the bar.")
    elif champ.get("halted"):
        status = ("STOPPED: it lost 25% from its best point, so the safety brake is on. It will only "
                  "trade again under a new strategy that proves itself.")
    else:
        status = "Trading normally."
    if champ.get("anomaly"):
        status = "STOPPED: its results looked too good to be true, so it was halted as a suspected bug. " + str(champ.get("anomaly"))
    syms = champ.get("symbols", ["BTCUSDT", "ETHUSDT"]); units = champ.get("units", [0, 0])
    last_close = {}
    try:
        bars = refdata.load("4h", allow_holdout=True)
        last_close = {sy: float(bars[sy]["close"].iloc[-1]) for sy in syms}
    except Exception:
        pass
    holdings = []
    for sy, u in zip(syms, units):
        if u > 1e-9:
            holdings.append(f"{_money(u * last_close.get(sy, 0))} in {NAMES.get(sy, sy)}")
    cash = float(champ.get("cash", START))
    if holdings:
        holding_txt = ", ".join(holdings) + f", and {_money(cash)} in cash"
    elif has_strategy:
        holding_txt = f"Everything is in cash ({_money(cash)}). The strategy is waiting for a buy signal."
    else:
        holding_txt = f"{_money(cash)} in cash. Nothing is being traded."
    exp = float((strat.get("expectation") or {}).get("sharpe_net") or 0)
    gaps = backtest_vs_live(db)
    gap_rows = "".join(f"<tr><td>{g['name']}</td><td>{g['expected']:+.2f}</td><td>{g['live']:+.2f}</td><td class='{'neg' if g['gap'] < 0 else 'pos'}'>{g['gap']:+.2f}</td><td>{g['days']}</td></tr>" for g in gaps)
    trade_rows = []
    for t, sy, side, usd, fill in db.execute("SELECT time, symbol, side, usd, fill FROM trades WHERE strategy_id='champion' ORDER BY id DESC LIMIT 30"):
        verb = "Bought" if side == "BUY" else "Sold"
        trade_rows.append(f"<tr><td>{t[:16]}</td><td>{verb} {_money(usd)} of {NAMES.get(sy, sy)}</td><td>at ${fill:,.2f}</td></tr>")
    lin = []
    for t, e, sj, rz in db.execute("SELECT time,event,strategy,reason FROM lineage ORDER BY id"):
        sd = json.loads(sj) if sj else {}
        what = {"freeze": "Started with", "promote": "Switched to", "demote": "Retired", "challenger_proposed": "Began testing contender", "demote_challenger": "Contender failed, dropped", "no_challenger": "No contender found"}.get(e, e)
        lin.append(f"<li><b>{t[:10]}</b> {what} {sd.get('family','')} on {sd.get('bar','')} bars. <span class='muted'>{html.escape(rz)}</span></li>")
    jour = "".join(f"<li><b>{t[:16]}</b> {html.escape(e)}</li>" for t, s_, e in db.execute("SELECT time,strategy_id,entry FROM journal WHERE strategy_id='champion' ORDER BY id DESC LIMIT 20"))
    errors = db.execute("SELECT count(*) FROM errors").fetchone()[0]
    tiles = "".join([
        _tile("Profit or loss so far", f"{'+' if pnl >= 0 else '-'}${abs(pnl):,.2f}",
              f"Account is worth {_money(value)}. You have paid in {_money(paid_in)} (the $1,000 start plus $100 a month).",
              "pos" if pnl >= 0 else "neg"),
        _tile("Fees and slippage paid", _money(fees), f"across {n_trades} buys and sells. This is money the exchange keeps."),
        _tile("Worst dip", f"{dd:.1%}", "the biggest fall from the account's highest value. The brake triggers at -25%."),
        _tile("Steadiness score", f"{sharpe:.2f}", f"return per unit of wobble (traders call it Sharpe). Above 1 is good, below 0 means losing. History promised {exp:+.2f}."),
    ])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Trading Bot Report</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>:root{{--bg:#fcfcfb;--bg2:#f1f0ec;--t:#0b0b0b;--t2:#52514e;--grid:#e3e2dc;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--pos:#008300;--neg:#e34948}}
@media(prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#1a1a19;--bg2:#242422;--t:#fff;--t2:#c3c2b7;--grid:#3a3a37;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--pos:#5cc45c;--neg:#e66767}}}}
:root[data-theme=dark]{{--bg:#1a1a19;--bg2:#242422;--t:#fff;--t2:#c3c2b7;--grid:#3a3a37;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--pos:#5cc45c;--neg:#e66767}}
body{{margin:0;padding:24px 16px;background:var(--bg);color:var(--t);font:16px/1.5 -apple-system,system-ui,sans-serif;max-width:960px;margin-inline:auto}}
h1{{font-size:24px;margin:0 0 6px}}h2{{font-size:18px;margin:30px 0 8px}}p{{margin:6px 0}}.sub,.muted{{color:var(--t2)}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:16px 0}}.tile{{background:var(--bg2);border-radius:10px;padding:14px 16px}}.tl{{font-size:13px;color:var(--t2)}}.tv{{font-size:28px;font-weight:650;margin:2px 0}}.ts{{font-size:13px;color:var(--t2)}}
.tile.pos .tv{{color:var(--pos)}}.tile.neg .tv{{color:var(--neg)}}
.chart{{width:100%;height:auto}}.grid{{stroke:var(--grid)}}.tick{{fill:var(--t2);font-size:11px}}.dl{{font-size:12px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid)}}th{{color:var(--t2);font-weight:500}}
.pos{{color:var(--pos)}}.neg{{color:var(--neg)}}li{{margin:6px 0}}.status{{background:var(--bg2);border-radius:10px;padding:12px 16px;margin:12px 0}}</style></head><body>
<h1>Trading Bot Report</h1>
<p class="sub">A practice account that started with $1,000, receives $100 every month, and may trade the 30 most heavily traded crypto coins. No real money is involved. Every number already includes the fees and price slippage a real exchange would charge.</p>
<div class="status"><b>Status:</b> {status}<br><b>Right now it holds:</b> {holding_txt}</div>
<div class="tiles">{tiles}</div>
<h2>Account value over time</h2>
<p class="sub">Blue is this bot. Orange is what the very same money, including every $100 monthly top-up on the same day, would be worth if it had simply been put into Bitcoin. Beating orange is the whole point.</p>
{chart}<p>{bh_line}</p>
<h2>The strategy it is using</h2>
{(f"<p><b>{strat.get('family','-')}</b>: it {PLAIN.get(strat.get('family',''), 'follows a fixed rule')}. It looks at the market every {strat.get('bar','1d').replace('4h','4 hours').replace('1d','day').replace('1w','week')} and decides. Chosen on {str(strat.get('frozen_at',''))[:10]} after testing {strat.get('n_trials','many')} rule variations against 7 years of history.</p>") if has_strategy else "<p><b>None.</b> Every strategy tested so far lost money once real trading costs were subtracted, or could not be told apart from luck. Rather than trade one anyway, the account holds cash. See the written verdict in docs/VERDICT_PHASE1.md for what was tried and what killed it.</p>"}
<p><b>Contender:</b> {("<b>" + chall['strategy']['family'] + "</b> has been practising alongside since " + chall['started'][:10] + ". It replaces the current strategy only if it does clearly better for 8 weeks.") if chall else "none yet. Every Sunday the bot re-examines history and may pick one to practise alongside; it takes over only if it does clearly better for 8 weeks."}</p>
<h2>Did it do as well as history promised?</h2>
<p class="sub">Every strategy is chosen because it looked good in the past. This table shows the steadiness score history promised versus what actually happened live. A big negative gap means the past was flattering it. This is the most honest number on the page.</p>
<table><tr><th>Strategy</th><th>Promised</th><th>Actual</th><th>Gap</th><th>Days live</th></tr>{gap_rows or "<tr><td colspan=5>Needs a few days of live trading.</td></tr>"}</table>
<h2>How it does when Bitcoin is rising vs falling</h2>
<table><tr><th>Market condition</th><th>Days</th><th>Bot's result</th></tr>{"".join(reg_rows) or "<tr><td colspan=3>Needs a few days of live trading.</td></tr>"}</table>
<h2>Recent buys and sells</h2>
<table><tr><th>When (UTC)</th><th>What</th><th>Price</th></tr>{"".join(trade_rows) or "<tr><td colspan=3>No trades yet.</td></tr>"}</table>
<h2>History of strategy changes</h2><ul>{"".join(lin) or "<li>none yet</li>"}</ul>
<h2>The bot's own notes</h2><ul>{jour or "<li>empty</li>"}</ul>
<p class="muted">Technical errors logged: {errors}. Times are UTC.</p>
</body></html>"""


def write(db=None) -> str:
    db = db or store.connect()
    OUT.write_text(build(db)); return str(OUT)
