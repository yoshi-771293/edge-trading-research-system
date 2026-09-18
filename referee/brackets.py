"""Bracket-order execution: an entry, a stop, and a take-profit, sized by risk.

A different mechanism from the rest of the project. Everywhere else a strategy holds
target weights and the engine rebalances toward them. Here each position carries a stop
price and a target price, and the bar's own high and low decide which is reached.

Timeline per bar t:
  1. deposit, on the first bar of a new calendar month
  2. for every open position, test this bar's LOW against the stop and HIGH against the
     target, and close it if either is reached
  3. fill entries signalled at the close of t-1, at OPEN[t]
  4. test the freshly opened position against this same bar, because a bar can move
     against you immediately after you enter
  5. mark to CLOSE[t], update the deposit-neutral index and the kill switch
  6. read the signal row for t, which is a function of bars <= t, for tomorrow

THE ASSUMPTION THAT MATTERS: when one bar touches both the stop and the target, daily
OHLC cannot say which came first. This engine always assumes the STOP. Resolving that
ambiguity the other way is the standard method for making a bracket backtest print
money that never existed.

Fills are pessimistic on both sides. A triggered stop becomes a market order, so it
fills WORSE than the stop price by spread and impact. A take-profit is a resting limit,
so it fills AT the target and earns nothing extra.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import costs, risk
from .costmodels import CryptoCosts
from .venues import get as get_venue

MAX_POSITION_FRAC = 0.35       # mirrors risk.MAX_ASSET_FRAC, as a share of EQUITY x leverage
MAX_RETAIL_LEVERAGE = 30.0     # ESMA retail cap on major currency pairs
TRADE_COLS = ["time", "symbol", "side", "reason", "usd", "units", "fill", "ref_open", "fee", "slippage"]


@dataclass
class Result:
    equity: pd.Series
    equity_gross: pd.Series
    contributed: pd.Series
    profit: pd.Series
    twr: pd.Series
    trades: pd.DataFrame
    exposure: pd.Series
    weights: pd.DataFrame
    total_costs: float
    equity_paper: pd.Series = None      # same decisions, NO spread and NO commission
    paper_twr: pd.Series = None         # its deposit-neutral index
    killed_at: pd.Timestamp | None = None
    n_stops: int = 0
    n_targets: int = 0
    n_capped: int = 0                 # ENTRIES PLACED whose size the cap throttled
    effective_risk_frac: float = 0.0  # mean realised risk per entry, as a share of equity
    leverage: float = 1.0


def execute(bars: dict[str, pd.DataFrame], signals: pd.DataFrame, universe: pd.DataFrame | None = None,
            start_equity: float = 1000.0, monthly_deposit: float = 0.0, risk_frac: float = 0.01,
            venue=None, kill_switch: bool = True, start=None, end=None, cost_model=None,
            leverage: float = 1.0) -> Result:
    """`signals` is a frame with a (symbol, field) column index, fields enter/stop/target.
    `enter` is +1 for a long, -1 for a short, 0 for nothing.

    `cost_model` selects the market's friction. It defaults to the crypto venue model,
    so every result produced before cost models existed is reproduced exactly.

    Shorts: in forex every position is long one currency and short another, so a sell
    is as natural as a buy. A short's stop sits ABOVE the entry and is hit by the bar's
    HIGH; its target sits below and is hit by the LOW. Its exit is a buy-back, filled
    worse than the stop when stopped. When a bar touches both, the STOP is assumed,
    exactly as for longs.
    """
    if not (0 < leverage <= MAX_RETAIL_LEVERAGE):
        raise ValueError(f"leverage {leverage} outside 0 < x <= {MAX_RETAIL_LEVERAGE} "
                         f"(the ESMA retail cap on major pairs)")
    syms = sorted({c[0] for c in signals.columns})
    idx = signals.index
    if start is not None:
        idx = idx[idx >= start]
    if end is not None:
        idx = idx[idx <= end]
    v = venue if hasattr(venue, "taker_fee") else get_venue(venue)
    cm = cost_model if cost_model is not None else CryptoCosts(v)

    O = {s: bars[s]["open"].reindex(idx) for s in syms}
    H = {s: bars[s]["high"].reindex(idx) for s in syms}
    L = {s: bars[s]["low"].reindex(idx) for s in syms}
    C = {s: bars[s]["close"].reindex(idx) for s in syms}
    QV = {s: bars[s]["quote_volume"].reindex(idx) if "quote_volume" in bars[s] else pd.Series(0.0, index=idx) for s in syms}
    HS = {s: (bars[s]["half_spread"].reindex(idx) if "half_spread" in bars[s] else pd.Series(np.nan, index=idx)) for s in syms}
    HSO = {s: (bars[s]["open_half_spread"].reindex(idx) if "open_half_spread" in bars[s] else HS[s]) for s in syms}
    from . import universe as _uni
    mb, md = _uni.liquidity({s: bars[s] for s in syms if "quote_volume" in bars[s]} or bars, idx, syms) \
        if any("quote_volume" in bars[s] for s in syms) else (pd.DataFrame(0.0, index=idx, columns=syms),) * 2
    UNI = (universe.reindex(index=idx, columns=syms).fillna(False)
           if universe is not None else pd.DataFrame(True, index=idx, columns=syms))

    cash = cash_g = cash_p = float(start_equity)
    pos: dict[str, dict] = {}               # symbol -> signed units, stop, target, entry
    last_close: dict[str, float] = {}       # last FINITE close per symbol: a gap must not poison equity

    def _px(sym, t):
        """Price to value a holding at: this bar's close if it exists, else the last one seen."""
        c = C[sym].iloc[t]
        if np.isfinite(c):
            return float(c)
        return last_close.get(sym, np.nan)
    pending: list[dict] = []
    contributed = float(start_equity)
    twr = 1.0; peak = 1.0; prev_eq = float(start_equity)
    killed_at = None; total_costs = 0.0
    eq = []; eqg = []; eqp = []; contrib = []; expo = []; twrs = []; W = []
    trades = []
    months = idx.to_period("M")
    n_stop = n_tgt = n_capped = 0
    risk_taken = []

    def _liq(sym, t):
        return (float(QV[sym].iloc[t] or 0.0), float(mb.iloc[t][sym] or 0.0) if sym in mb else 0.0,
                float(md.iloc[t][sym] or 0.0) if sym in md else 0.0)

    def _close_pos(sym, p, price, when, reason, ref):
        """Exit a position of signed units at `price`. Long sells, short buys back."""
        nonlocal cash, cash_g, cash_p, total_costs
        u = p["units"]
        fee = cm.commission(abs(u) * price)
        cash += u * price - fee               # long: +proceeds; short (u<0): pays to buy back
        cash_g += u * price
        cash_p += u * ref                     # paper twin: the reference price, no friction
        total_costs += fee + abs(u) * abs(ref - price)
        trades.append({"time": when, "symbol": sym, "side": "SELL" if u > 0 else "BUY", "reason": reason,
                       "usd": abs(u) * price, "units": -u, "fill": price, "ref_open": ref,
                       "fee": fee, "slippage": abs(u) * abs(ref - price)})

    def _check_exit(sym, p, t, when):
        """Stop assumed when both are touched. Returns True if the position closed."""
        nonlocal n_stop, n_tgt
        lo, hi = L[sym].iloc[t], H[sym].iloc[t]
        if not (np.isfinite(lo) and np.isfinite(hi)):
            return False
        long = p["units"] > 0
        qv, mbq, mdq = _liq(sym, t)
        hs_day = float(HS[sym].iloc[t])
        stop_hit = (lo <= p["stop"]) if long else (hi >= p["stop"])
        tgt_hit = (hi >= p["target"] * (1 + costs.MAKER_QUEUE_MARGIN)) if long else \
                  (lo <= p["target"] * (1 - costs.MAKER_QUEUE_MARGIN))
        if stop_hit:
            px = cm.fill_price(p["stop"], -1 if long else +1, abs(p["units"]) * p["stop"], qv, mbq, mdq, hs_day)
            _close_pos(sym, p, px, when, "stop", p["stop"]); n_stop += 1
            return True
        if tgt_hit:
            _close_pos(sym, p, p["target"], when, "target", p["target"]); n_tgt += 1
            return True
        return False

    for t, when in enumerate(idx):
        # 1. deposit
        dep = 0.0
        if monthly_deposit and t > 0 and months[t] != months[t - 1]:
            dep = float(monthly_deposit)
            cash += dep; cash_g += dep; cash_p += dep; contributed += dep

        # 2. stops and targets on existing positions
        for sym in list(pos):
            if _check_exit(sym, pos[sym], t, when):
                del pos[sym]

        # 3. fill entries decided on the previous bar. Existing positions are valued at
        #    THIS bar's OPEN, because the fill happens at the open: using the close here
        #    would size an order with a price that does not exist yet.
        for order in pending:
            sym = order["symbol"]
            if sym in pos:
                continue
            o = O[sym].iloc[t]
            if not np.isfinite(o) or not bool(UNI.iloc[t][sym]):
                continue
            equity_open = cash + sum(
                pp["units"] * (float(O[s2].iloc[t]) if np.isfinite(O[s2].iloc[t]) else last_close.get(s2, 0.0))
                for s2, pp in pos.items())
            if not np.isfinite(equity_open) or equity_open <= 0:
                continue
            side = order["side"]
            dist = (o - order["stop"]) if side > 0 else (order["stop"] - o)
            if dist <= 0:
                continue
            wanted = risk_frac * equity_open / dist * o
            cap = min(MAX_POSITION_FRAC, risk.MAX_ORDER_FRAC) * equity_open * leverage
            notional = min(wanted, cap)
            was_capped = wanted > cap
            if notional < costs.MIN_TRADE_USD:
                continue
            qv, mbq, mdq = _liq(sym, t)
            px = cm.fill_price(float(o), side, notional, qv, mbq, mdq, float(HSO[sym].iloc[t]))
            if side > 0:
                notional = min(notional, leverage * cash / (1 + v.taker_fee))
                if notional < costs.MIN_TRADE_USD:
                    continue
            units = side * notional / px
            if was_capped:
                n_capped += 1          # count PLACED entries only, never rejected attempts
            fee = cm.commission(notional)
            cash -= units * px + fee              # short: units<0, cash rises by the sale
            cash_g -= units * px
            cash_p -= units * float(o)            # paper twin: filled at the reference open
            total_costs += fee + abs(units) * abs(px - o)
            risk_taken.append(abs(units) * dist / equity_open if equity_open > 0 else 0.0)
            trades.append({"time": when, "symbol": sym, "side": "BUY" if side > 0 else "SELL", "reason": "entry",
                           "usd": notional, "units": units, "fill": px, "ref_open": float(o),
                           "fee": fee, "slippage": abs(units) * abs(px - o)})
            pos[sym] = {"units": units, "stop": order["stop"], "target": order["target"], "entry": px}
            # 4. the same bar can already take it out
            if _check_exit(sym, pos[sym], t, when):
                del pos[sym]
        pending = []

        # 5. record finite closes, charge financing, then mark on last known prices
        for s2 in syms:
            c2 = C[s2].iloc[t]
            if np.isfinite(c2):
                last_close[s2] = float(c2)
        if pos:
            bar_days = ((idx[t] - idx[t - 1]).total_seconds() / 86400.0) if t > 0 else 1.0
            carry = sum(cm.financing(abs(pos[s]["units"]) * (last_close.get(s, 0.0) or 0.0), bar_days) for s in pos)
            if carry and np.isfinite(carry):
                cash -= carry; cash_g -= carry; total_costs += carry
        held = {s: pos[s]["units"] * (last_close.get(s, 0.0) or 0.0) for s in pos}
        equity = cash + sum(held.values())
        gross = cash_g + sum(held.values())
        eq.append(equity); eqg.append(gross); contrib.append(contributed)
        eqp.append(cash_p + sum(pos[s2]["units"] * (last_close.get(s2, 0.0) or 0.0) for s2 in pos))
        expo.append(sum(abs(x) for x in held.values()) / equity if equity > 0 else 0.0)
        W.append({s: (held.get(s, 0.0) / equity if equity > 0 else 0.0) for s in syms})
        if prev_eq > 0:
            twr *= (equity - dep) / prev_eq
        prev_eq = equity
        peak = max(peak, twr)
        twrs.append(twr)
        if kill_switch and killed_at is None and twr < peak * (1 - risk.KILL_DRAWDOWN):
            killed_at = when

        # 6. read today's signals for tomorrow
        if killed_at is None:
            for sym in syms:
                try:
                    on = float(signals.iloc[t][(sym, "enter")] or 0.0)
                except KeyError:
                    on = 0.0
                if on != 0 and sym not in pos:
                    st = signals.iloc[t][(sym, "stop")]
                    tg = signals.iloc[t][(sym, "target")]
                    side = 1 if on > 0 else -1
                    ok = (tg > st) if side > 0 else (tg < st)
                    if np.isfinite(st) and np.isfinite(tg) and ok:
                        pending.append({"symbol": sym, "stop": float(st), "target": float(tg), "side": side})

    eq_s = pd.Series(eq, index=idx, name="equity")
    con_s = pd.Series(contrib, index=idx, name="contributed")
    paper_s = pd.Series(eqp, index=idx, name="paper")
    _dep = con_s.diff().fillna(0.0)
    paper_twr = ((paper_s - _dep) / paper_s.shift(1)).fillna(1.0).cumprod()
    n_entries = int(sum(1 for x in trades if x["reason"] == "entry"))
    return Result(equity=eq_s, equity_gross=pd.Series(eqg, index=idx, name="gross"),
                  equity_paper=paper_s, paper_twr=paper_twr,
                  contributed=con_s, profit=(eq_s - con_s).rename("profit"),
                  twr=pd.Series(twrs, index=idx, name="twr"),
                  trades=pd.DataFrame(trades, columns=TRADE_COLS) if trades else pd.DataFrame(columns=TRADE_COLS),
                  exposure=pd.Series(expo, index=idx), weights=pd.DataFrame(W, index=idx).fillna(0.0),
                  total_costs=total_costs, killed_at=killed_at, n_stops=n_stop, n_targets=n_tgt,
                  n_capped=n_capped, leverage=float(leverage),
                  effective_risk_frac=float(np.mean(risk_taken)) if risk_taken else 0.0)
