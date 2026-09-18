"""Phase 2 live cycle over a point-in-time, survivorship-free universe.

SIMULATION ONLY. There is no exchange key, no signing code and no order-submission
path anywhere in this repository.

One cycle:
  1. verify referee integrity, or halt
  2. build the watchlist (most liquid current USDT spot pairs, leveraged tokens and
     stablecoin pairs excluded) and fetch their bars
  3. rebuild the point-in-time universe exactly as the backtest does
  4. add the monthly deposit if the calendar month has turned
  5. fill the order decided on the previous bar, at THIS bar's open
  6. mark, update the deposit-neutral return index, check tripwire and kill switch
  7. decide for the next bar and store it with its reasoning

Positions are keyed by symbol because universe membership churns.
"""
from __future__ import annotations
import concurrent.futures as cf
import json
import traceback
import urllib.request

import numpy as np
import pandas as pd

from referee import replay, risk, universe, validate
from player import families
from live import store, notify as _notify

START_EQUITY = 1000.0
MONTHLY_DEPOSIT = 100.0
VENUE = "mexc"                 # cheapest measured all-in cost; see referee/venues.py
ORDER_STYLE = "maker"          # passive limits; unfilled orders escalate to taker next bar
TOP_N = 30
MIN_HISTORY_DAYS = 90
VOLUME_WINDOW = 30
WATCHLIST_SIZE = 60
BARS_NEEDED = 420                      # covers the longest lookback (200) plus warm-up
REST = "https://api.binance.com/api/v3"


def months_between(last: str | None, now: str) -> int:
    """Whole calendar months from `last` ("YYYY-MM") to `now`. An outage must not
    silently skip contributions: three months offline owes three deposits."""
    if not last:
        return 0
    a = pd.Period(last, freq="M"); b = pd.Period(now, freq="M")
    return max(int((b - a).n), 0)


def notify(title, msg, **k):
    return _notify.alert(title, msg, **k)


def guard_check():
    from player import guard
    guard.enforce()


def _json(url: str):
    return json.loads(urllib.request.urlopen(url, timeout=30).read())


def watchlist(top: int = WATCHLIST_SIZE) -> list[str]:
    """The most liquid USDT spot pairs trading right now, after the referee's
    spot-only filter. A superset of the universe, so ranking has something to rank."""
    info = _json(f"{REST}/exchangeInfo?permissions=SPOT")
    live = {s["symbol"] for s in info["symbols"]
            if s["status"] == "TRADING" and s["quoteAsset"] == "USDT" and s.get("isSpotTradingAllowed")}
    tick = _json(f"{REST}/ticker/24hr")
    rows = [(t["symbol"], float(t["quoteVolume"])) for t in tick if t["symbol"] in live]
    ok = [(s, v) for s, v in rows if universe.is_spot_symbol(s, live)]
    ok.sort(key=lambda z: -z[1])
    return [s for s, _ in ok[:top]]


def _klines(symbol: str, interval: str, limit: int):
    try:
        raw = _json(f"{REST}/klines?symbol={symbol}&interval={interval}&limit={limit}")
    except Exception:
        return symbol, None
    rows = [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[7])) for k in raw]
    if not rows:
        return symbol, None
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume", "quote_volume"])
    df.index = pd.to_datetime(df.pop("t"), unit="ms", utc=True)
    df.index.name = "time"
    return symbol, df


def fetch_bars(symbols: list[str], bar: str, limit: int = BARS_NEEDED) -> dict[str, pd.DataFrame]:
    out = {}
    with cf.ThreadPoolExecutor(12) as ex:
        for sym, df in ex.map(lambda s: _klines(s, bar, limit), symbols):
            if df is not None and len(df) > 10:
                out[sym] = df
    return out


def _build_universe(bars: dict[str, pd.DataFrame], bar: str, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Same construction the search used: rank by trailing daily dollar volume."""
    if bar == "1d":
        return universe.build(bars, top_n=TOP_N, min_history_days=MIN_HISTORY_DAYS,
                              volume_window=VOLUME_WINDOW, index=index)
    daily = {s: d.resample("1D").agg({"open": "first", "high": "max", "low": "min",
                                      "close": "last", "volume": "sum", "quote_volume": "sum"}).dropna()
             for s, d in bars.items()}
    uni_d = universe.build(daily, top_n=TOP_N, min_history_days=MIN_HISTORY_DAYS, volume_window=VOLUME_WINDOW)
    return uni_d.reindex(uni_d.index.union(index)).ffill().reindex(index).fillna(False).astype(bool)


def cycle(db, sid: str) -> dict:
    guard_check()
    st = store.get_state(db, sid)
    if not st or not st.get("strategy"):
        return {"status": "no_strategy"}
    strat = st["strategy"]
    bar = strat["bar"]
    param = tuple(strat["param"]) if isinstance(strat["param"], (list, tuple)) else strat["param"]

    syms = watchlist()
    held = {s: u for s, u in (st.get("positions") or {}).items() if u > 1e-12}
    fetch_list = sorted(set(syms) | set(held))              # always able to price and sell what we own
    bars = fetch_bars(fetch_list, bar)
    if not bars:
        raise RuntimeError("no bars returned")
    close_all = pd.DataFrame({s: d["close"] for s, d in bars.items()}).sort_index()
    if len(close_all) < 3:
        return {"status": "insufficient_history"}
    latest_closed = close_all.index[-2]                      # the last row is still forming
    if st.get("last_bar") == str(latest_closed):
        return {"status": "no_new_bar", "bar": str(latest_closed)}

    cols = list(close_all.columns)
    uni = _build_universe(bars, bar, close_all.index)
    cash = float(st.get("cash", START_EQUITY)); cash_g = float(st.get("cash_g", START_EQUITY))
    units = np.array([float((st.get("positions") or {}).get(s, 0.0)) for s in cols])
    units_g = np.array([float((st.get("positions_g") or {}).get(s, 0.0)) for s in cols])
    contributed = float(st.get("contributed", START_EQUITY))
    twr = float(st.get("twr", 1.0)); peak_twr = float(st.get("peak_twr", 1.0))
    prev_equity = float(st.get("prev_equity", START_EQUITY))
    halted = bool(st.get("halted", False))

    # 4. monthly deposit
    this_month = latest_closed.strftime("%Y-%m")
    n_months = months_between(st.get("last_month"), this_month)
    dep = MONTHLY_DEPOSIT * n_months
    if dep:
        cash += dep; cash_g += dep; contributed += dep
        note = (f"Monthly deposit of ${MONTHLY_DEPOSIT:,.0f} added." if n_months == 1 else
                f"{n_months} monthly deposits of ${MONTHLY_DEPOSIT:,.0f} added after a gap.")
        store.journal(db, sid, latest_closed, f"{note} Total paid in: ${contributed:,.0f}.")

    # 5. fill the previous decision at THIS bar's open
    fills = []
    pend = st.get("pending")
    if pend:
        decided = pd.Timestamp(pend["decided_bar"])
        after = close_all.index[(close_all.index > decided) & (close_all.index <= latest_closed)]
        if len(after):
            fb = after[0]
            o = np.array([bars[s]["open"].get(fb, np.nan) for s in cols])
            qv = np.array([bars[s]["quote_volume"].get(fb, 0.0) for s in cols])
            mb, md = universe.liquidity(bars, close_all.index, cols)
            avail = np.isfinite(o)
            in_uni = uni.reindex(index=[fb], columns=cols).fillna(False).values[0]
            target = np.array([float(pend["usd"].get(s, 0.0)) for s in cols])
            hi = np.array([bars[s]["high"].get(fb, np.nan) for s in cols])
            lo = np.array([bars[s]["low"].get(fb, np.nan) for s in cols])
            esc = np.array([bool((st.get("escalate") or {}).get(s, False)) for s in cols])
            units, cash, fills, unfilled = replay.fill_bar(
                target, units, cash, o, qv, mb.loc[fb].values, md.loc[fb].values,
                can_buy=avail & in_uni, can_sell=avail, venue=VENUE, style=ORDER_STYLE,
                high=hi, low=lo, force_taker=esc)
            st["escalate"] = {cols[j]: True for j in unfilled}
            for f in fills:
                j = f["j"]
                units_g[j] += f["units"]; cash_g -= f["units"] * f["fill"]   # gross twin: same fill, no fee
                db.execute("INSERT INTO trades(strategy_id,time,symbol,side,usd,units,fill,ref_open,fee,slippage,style)"
                           " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (sid, str(fb), cols[j], f["side"], f["usd"], f["units"], f["fill"],
                            f["ref_open"], f["fee"], f["slippage"], f.get("style", ORDER_STYLE)))

    # 6. mark to the latest closed bar
    c = np.array([bars[s]["close"].get(latest_closed, np.nan) for s in cols])
    c = np.where(np.isfinite(c), c, 0.0)
    hold = units * c
    equity = float(cash + hold.sum())
    gross = float(cash_g + (units_g * c).sum())
    if prev_equity > 0:
        twr *= (equity - dep) / prev_equity
    peak_twr = max(peak_twr, twr)
    dd = twr / peak_twr - 1
    profit = equity - contributed
    db.execute("INSERT OR REPLACE INTO equity VALUES(?,?,?,?,?,?,?,?,?,?)",
               (sid, str(latest_closed), equity, gross, cash,
                float(hold.sum() / equity) if equity > 0 else 0.0, dd, contributed, profit, twr))

    # tripwire on the deposit-neutral series
    hist = pd.read_sql("SELECT time, twr, gross, contributed FROM equity WHERE strategy_id=? ORDER BY time",
                       db, params=(sid,))
    if len(hist) > 40:
        h = hist.set_index(pd.to_datetime(hist["time"], utc=True))
        ppy = {"1h": 24 * 365, "4h": 6 * 365, "1d": 365, "1w": 52}[bar]
        gdep = h["contributed"].diff().fillna(0.0)
        gtwr = ((h["gross"] - gdep) / h["gross"].shift(1)).fillna(1.0).cumprod()
        trip = validate.tripwire(h["twr"].pct_change().dropna(), ppy,
                                 level_violations=int((h["twr"] > gtwr * (1 + 1e-9)).sum()),
                                 benchmark_returns=validate.benchmark_daily_returns(bars))
        if trip.tripped and not st.get("anomaly"):
            st["anomaly"] = trip.reason; halted = True
            db.execute("INSERT INTO anomalies(time,strategy_id,reason) VALUES(?,?,?)",
                       (str(latest_closed), sid, trip.reason))
            notify("Edge Tournament ANOMALY", f"{sid}: {trip.reason}. Treated as a suspected bug and halted.")
            store.journal(db, sid, latest_closed, f"ANOMALY TRIPWIRE: {trip.reason}. Halted pending investigation.")

    status = "ok"
    if not halted and dd <= -risk.KILL_DRAWDOWN:
        halted = True; status = "killed"
        notify("Edge Tournament KILL SWITCH",
               f"{sid} down {dd:.1%} from its best (deposits excluded). Trading halted; the tournament continues.")
        store.journal(db, sid, latest_closed,
                      f"KILL SWITCH at {dd:.1%} below peak, excluding deposits. Account ${equity:,.2f}, "
                      f"paid in ${contributed:,.2f}. Flattening. Trading resumes only under a promoted challenger.")

    # 7. decide for the next bar
    if halted:
        pending = {"usd": {s: 0.0 for s in cols}, "decided_bar": str(latest_closed)} if hold.sum() > 25 else None
        reasoning = "Halted: flatten and hold cash."
    else:
        rule = families.make_rule(strat["family"], param, uni)
        w = rule(close_all.loc[:latest_closed]).iloc[-1]
        dollars = risk.apply_np(w.reindex(cols).fillna(0.0).values, equity, hold)
        pending = {"usd": {s: float(v) for s, v in zip(cols, dollars)}, "decided_bar": str(latest_closed)}
        want = {s: float(v) for s, v in zip(cols, dollars) if v > 1.0}
        in_uni_now = [s for s in cols if uni.reindex(index=[latest_closed], columns=cols).fillna(False).values[0][cols.index(s)]]
        reasoning = (f"{strat['family']}{param} on {bar} bars, closes through {latest_closed}. "
                     f"Universe: {len(in_uni_now)} coins. Wants: "
                     + (", ".join(f"{s.replace('USDT','')} ${v:,.0f}" for s, v in sorted(want.items(), key=lambda z: -z[1])) or "all cash")
                     + f". Account ${equity:,.2f}, paid in ${contributed:,.2f}, profit ${profit:,.2f}, "
                       f"{dd:+.1%} from peak. Fills at the next bar's open.")
    db.execute("INSERT OR REPLACE INTO decisions VALUES(?,?,?,?)",
               (sid, str(latest_closed), json.dumps(pending), reasoning))
    st.update({"cash": cash, "cash_g": cash_g,
               "positions": {s: float(u) for s, u in zip(cols, units) if abs(u) > 1e-12},
               "positions_g": {s: float(u) for s, u in zip(cols, units_g) if abs(u) > 1e-12},
               "contributed": contributed, "twr": twr, "peak_twr": peak_twr, "prev_equity": equity,
               "halted": halted, "pending": pending, "last_bar": str(latest_closed),
               "last_month": this_month, "equity": equity, "gross": gross, "profit": profit})
    store.set_state(db, sid, st)
    if fills or status != "ok":
        store.journal(db, sid, latest_closed, f"{len(fills)} trade(s). {reasoning}")
    db.commit()
    return {"status": status, "bar": str(latest_closed), "equity": equity, "profit": profit,
            "contributed": contributed, "fills": len(fills)}


def safe_cycle(db, sid: str) -> dict:
    try:
        return cycle(db, sid)
    except SystemExit:
        raise
    except Exception as e:
        db.execute("INSERT INTO errors(time,where_,message) VALUES(?,?,?)",
                   (str(pd.Timestamp.now(tz="UTC")), f"cycle:{sid}", traceback.format_exc()))
        db.commit()
        return {"status": "error", "message": str(e)}
