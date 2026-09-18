"""Bar-by-bar execution simulator for a many-coin spot account with cash deposits.

Timeline for each bar t (nothing from bar t's own prices reaches a decision made on
bar t; the decision is executed at the OPEN of t+1):
  1. deposit, on the first bar of a new calendar month
  2. force-exit any holding whose coin stopped trading (delisting), at a haircut
  3. fill orders decided at the close of t-1, at OPEN[t], worse by spread + impact
  4. mark to CLOSE[t]
  5. update the deposit-neutral return index, drawdown and kill switch
  6. read targets row t (a function of bars <= t only) -> pending for t+1

Accounting: `contributed` is money put in, `equity` is what the account is worth,
`profit` is the difference, and `twr` is a deposit-neutral return index. Drawdown and
the kill switch are measured on `twr`, so a fresh deposit can never hide a loss.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from . import costs, risk
from .venues import get as get_venue


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
    deposits: float = 0.0


TRADE_COLS = ["time", "symbol", "side", "usd", "units", "fill", "ref_open", "fee", "slippage", "style"]


def fill_bar(pending_usd, units, cash: float, open_px, bar_qv, median_bar_qv, median_daily_qv,
             can_buy, can_sell=None, venue=None, style: str = "taker", high=None, low=None,
             force_taker=None, cost_model=None, half_spread=None):
    """Fill a dollar-target vector at this bar's OPEN with the pessimistic cost model.
    THE single execution path: the backtester and the live agent both call this.

    Buying and selling are gated separately on purpose. The point-in-time universe
    restricts what may be BOUGHT; anything still trading may always be SOLD. Gating
    both would strand capital in coins that fall out of the universe.

    style="maker" rests a limit order half a spread on our own side of the open and
    fills ONLY if the bar's high/low actually reached it, which is what produces
    honest adverse selection. `force_taker` is a per-symbol mask used to escalate an
    order that failed passively on the previous bar, so nothing can be stranded."""
    units = np.array(units, dtype=float).copy()
    cash = float(cash)
    fills = []
    hold_open = units * np.nan_to_num(open_px)
    # only symbols with a real order are visited: identical results, far fewer iterations
    v = venue if hasattr(venue, "taker_fee") else get_venue(venue)
    buy_ok = np.asarray(can_buy, dtype=bool)
    sell_ok = buy_ok if can_sell is None else np.asarray(can_sell, dtype=bool)
    gap = np.asarray(pending_usd, dtype=float) - hold_open
    allowed = np.where(gap > 0, buy_ok, sell_ok)
    candidates = np.where((np.abs(gap) >= costs.MIN_TRADE_USD) & allowed)[0]
    unfilled = []
    for j in candidates:
        delta = float(gap[j])
        side = 1 if delta > 0 else -1
        as_taker = style != "maker" or (force_taker is not None and bool(force_taker[j]))
        if as_taker:
            if cost_model is not None:
                hs = float(half_spread[j]) if half_spread is not None else None
                px = cost_model.fill_price(float(open_px[j]), side, delta, float(bar_qv[j]),
                                           float(median_bar_qv[j]), float(median_daily_qv[j]), hs)
            else:
                px = costs.fill_price(float(open_px[j]), side, delta, float(bar_qv[j]),
                                      float(median_bar_qv[j]), float(median_daily_qv[j]), venue=v, style="taker")
            fill_style = "taker"
        else:
            px = costs.maker_fill(float(open_px[j]),
                                  float(high[j]) if high is not None else float("nan"),
                                  float(low[j]) if low is not None else float("nan"),
                                  side, float(median_daily_qv[j]), venue=v)
            if px is None:
                # A missed ENTRY is simply missed: that is the adverse-selection cost of
                # resting passively, and escalating it would just pay the taker fee
                # anyway. A missed EXIT is different, it must never strand capital, so
                # it is retried as a taker on the next bar.
                if side < 0:
                    unfilled.append(j)
                continue
            fill_style = "maker"
        rate = v.maker_fee if fill_style == "maker" else v.taker_fee
        if side > 0:
            delta = min(delta, cash / (1 + rate))
            if delta < costs.MIN_TRADE_USD:
                continue
        q = delta / px
        if side < 0:
            q = max(q, -units[j])
            delta = q * px
        fee = (cost_model.commission(delta) if (cost_model is not None and fill_style == "taker")
               else costs.commission(delta, venue=v, style=fill_style))
        units[j] += q
        cash -= q * px + fee
        fills.append({"j": j, "side": "BUY" if side > 0 else "SELL", "usd": abs(delta), "units": q,
                      "fill": px, "ref_open": float(open_px[j]), "fee": fee, "style": fill_style,
                      "slippage": abs(q) * (px - open_px[j]) * side})
    return units, cash, fills, unfilled


def execute(bars: dict[str, pd.DataFrame], targets: pd.DataFrame, universe: pd.DataFrame | None = None,
            start_equity: float = 1000.0, monthly_deposit: float = 0.0,
            start=None, end=None, kill_switch: bool = True, apply_risk: bool = True,
            venue=None, style: str = "taker", cost_model=None) -> Result:
    syms = list(targets.columns)
    idx = targets.index
    if start is not None:
        idx = idx[idx >= start]
    if end is not None:
        idx = idx[idx <= end]
    O = np.column_stack([bars[s]["open"].reindex(idx).values if s in bars else np.full(len(idx), np.nan) for s in syms])
    C = np.column_stack([bars[s]["close"].reindex(idx).values if s in bars else np.full(len(idx), np.nan) for s in syms])
    HI = np.column_stack([bars[s]["high"].reindex(idx).values if s in bars else np.full(len(idx), np.nan) for s in syms])
    LO = np.column_stack([bars[s]["low"].reindex(idx).values if s in bars else np.full(len(idx), np.nan) for s in syms])
    QV = np.column_stack([bars[s]["quote_volume"].reindex(idx).values if s in bars else np.zeros(len(idx)) for s in syms])
    from . import universe as _uni
    _mb, _md = _uni.liquidity(bars, idx, syms)          # one shared definition
    MBQ, MDQ = _mb.values, _md.values
    AV = np.isfinite(C) & np.isfinite(O)
    UNI = (universe.reindex(index=idx, columns=syms).fillna(False).values.astype(bool)
           if universe is not None else np.ones_like(AV, dtype=bool))
    T = targets.loc[idx].values
    n, m = len(idx), len(syms)
    months = idx.to_period("M")
    # measured spreads, when the market supplies them (forex); the OPEN hour's for fills
    HSO = np.column_stack([
        (bars[s]["open_half_spread"].reindex(idx).values if s in bars and "open_half_spread" in bars[s]
         else bars[s]["half_spread"].reindex(idx).values if s in bars and "half_spread" in bars[s]
         else np.full(len(idx), np.nan)) for s in syms])

    cash = float(start_equity); cash_g = float(start_equity); cash_p = float(start_equity)
    units = np.zeros(m); units_g = np.zeros(m); units_p = np.zeros(m)
    last_close = np.full(m, np.nan)
    pending = None
    eq = np.empty(n); eqg = np.empty(n); eqp = np.empty(n); contrib = np.empty(n); expo = np.empty(n)
    twr = np.empty(n); W = np.zeros((n, m))
    trades = []
    contributed = float(start_equity)
    peak_twr = 1.0; twr_level = 1.0; prev_equity = float(start_equity)
    killed_at = None; total_costs = 0.0; deposits_total = 0.0
    escalate = np.zeros(m, dtype=bool)          # orders that failed passively last bar
    v = venue if hasattr(venue, "taker_fee") else get_venue(venue)

    for t in range(n):
        o, c = O[t], C[t]
        # 1. monthly deposit
        dep = 0.0
        if monthly_deposit and t > 0 and months[t] != months[t - 1]:
            dep = float(monthly_deposit)
            cash += dep; cash_g += dep; cash_p += dep
            contributed += dep; deposits_total += dep
        # 2. delisting: force-exit anything that stopped trading
        for j in np.where(units > 0)[0]:
            if not AV[t, j] and np.isfinite(last_close[j]):
                px = last_close[j] * (1 - costs.DELIST_HAIRCUT)
                q = -units[j]
                cash += -q * px; units[j] = 0.0
                cash_g += -q * px; units_g[j] = 0.0
                cash_p += -q * last_close[j]; units_p[j] = 0.0
                trades.append({"time": idx[t], "symbol": syms[j], "side": "DELIST", "usd": abs(q * px),
                               "units": q, "fill": px, "ref_open": last_close[j], "fee": 0.0,
                               "style": "forced", "slippage": abs(q) * abs(px - last_close[j])})
        # 3. fill yesterday's decision at today's open
        if pending is not None:
            units, cash, fills, unfilled = fill_bar(
                pending, units, cash, o, QV[t], MBQ[t], MDQ[t],
                can_buy=AV[t] & UNI[t], can_sell=AV[t], venue=v, style=style,
                high=HI[t], low=LO[t], force_taker=escalate,
                cost_model=cost_model, half_spread=HSO[t])
            escalate = np.zeros(m, dtype=bool)
            for j in unfilled:
                escalate[j] = True
            for f in fills:
                j = f["j"]
                units_g[j] += f["units"]; cash_g -= f["units"] * f["fill"]   # gross twin: same fill, no fee
                units_p[j] += f["units"]; cash_p -= f["units"] * o[j]         # paper twin: reference price, no fee
                total_costs += f["fee"] + f["slippage"]
                trades.append({"time": idx[t], "symbol": syms[j], **{k: f[k] for k in
                              ("side", "usd", "units", "fill", "ref_open", "fee", "slippage", "style")}})
        pending = None
        # 4. financing (a forex position is borrowed; spot crypto charges nothing), then mark
        last_close = np.where(np.isfinite(c), c, last_close)
        if cost_model is not None and t > 0:
            bar_days = (idx[t] - idx[t - 1]).total_seconds() / 86400.0
            carry = cost_model.financing(float(np.abs(units * np.nan_to_num(last_close)).sum()), bar_days)
            if carry:
                cash -= carry; cash_g -= carry; total_costs += carry
        hold = units * np.nan_to_num(last_close)
        equity = cash + hold.sum()
        eq[t] = equity; eqg[t] = cash_g + (units_g * np.nan_to_num(last_close)).sum()
        eqp[t] = cash_p + (units_p * np.nan_to_num(last_close)).sum()
        contrib[t] = contributed
        expo[t] = hold.sum() / equity if equity > 0 else 0.0
        W[t] = hold / equity if equity > 0 else 0.0
        # 5. deposit-neutral return index, then drawdown on THAT
        if prev_equity > 0:
            twr_level *= (equity - dep) / prev_equity
        twr[t] = twr_level
        prev_equity = equity
        peak_twr = max(peak_twr, twr_level)
        if kill_switch and killed_at is None and twr_level < peak_twr * (1 - risk.KILL_DRAWDOWN):
            killed_at = idx[t]
        # 6. decide for the next bar
        row = T[t]
        if killed_at is None:
            if not np.isnan(row).all():
                # outside the universe the target is zero, which is an instruction to
                # exit; the sell itself is permitted by can_sell on the next bar.
                row = np.where(AV[t] & UNI[t], np.nan_to_num(row), 0.0)
                pending = risk.apply_np(row, equity, hold) if apply_risk else np.clip(row, 0, 1) * equity
        else:
            pending = np.zeros(m) if hold.sum() > costs.MIN_TRADE_USD else None

    equity_s = pd.Series(eq, index=idx, name="equity")
    contrib_s = pd.Series(contrib, index=idx, name="contributed")
    paper_s = pd.Series(eqp, index=idx, name="paper")
    _dep = contrib_s.diff().fillna(0.0)
    paper_twr = ((paper_s - _dep) / paper_s.shift(1)).fillna(1.0).cumprod()
    return Result(equity=equity_s, equity_gross=pd.Series(eqg, index=idx, name="gross"),
                  equity_paper=paper_s, paper_twr=paper_twr,
                  contributed=contrib_s, profit=(equity_s - contrib_s).rename("profit"),
                  twr=pd.Series(twr, index=idx, name="twr"),
                  trades=pd.DataFrame(trades, columns=TRADE_COLS) if trades else pd.DataFrame(columns=TRADE_COLS),
                  exposure=pd.Series(expo, index=idx), weights=pd.DataFrame(W, index=idx, columns=syms),
                  total_costs=total_costs, killed_at=killed_at, deposits=deposits_total)


def buy_and_hold_dca(bars: dict[str, pd.DataFrame], symbol: str, start_equity: float = 1000.0,
                     monthly_deposit: float = 0.0, start=None, end=None, venue=None) -> Result:
    """The fair benchmark: put everything in one coin and add the SAME deposits on the
    same schedule. Never sells. Pays the same friction on every purchase."""
    syms = [symbol]
    idx = bars[symbol].index
    tgt = pd.DataFrame(1.0, index=idx, columns=syms)
    uni = pd.DataFrame(True, index=idx, columns=syms)
    return execute({symbol: bars[symbol]}, tgt, universe=uni, start_equity=start_equity,
                   monthly_deposit=monthly_deposit, start=start, end=end,
                   kill_switch=False, apply_risk=False, venue=venue)


def buy_and_hold(bars, weights: dict[str, float], start_equity=1000.0, start=None, end=None) -> Result:
    """Single purchase at the first open, then hold. No deposits."""
    syms = list(bars)
    idx = bars[syms[0]].index
    tgt = pd.DataFrame(np.nan, index=idx, columns=syms)
    if start is not None:
        idx2 = idx[idx >= start]
        tgt.loc[idx2[0]] = [weights.get(s, 0.0) for s in syms]
    else:
        tgt.iloc[0] = [weights.get(s, 0.0) for s in syms]
    uni = pd.DataFrame(True, index=idx, columns=syms)
    return execute(bars, tgt, universe=uni, start_equity=start_equity, start=start, end=end,
                   kill_switch=False, apply_risk=False)


def strict_targets(close: pd.DataFrame, decide, sample_every: int = 1, min_history: int = 1) -> pd.DataFrame:
    """The literal 'see bar t, decide, then see t+1' loop: decide() receives ONLY
    close.iloc[:t+1]. Proves a vectorized rule is causal by construction."""
    rows, times = [], []
    for t in range(min_history - 1, len(close), sample_every):
        rows.append(decide(close.iloc[:t + 1]).values)
        times.append(close.index[t])
    return pd.DataFrame(rows, index=pd.DatetimeIndex(times), columns=close.columns)


def metrics(series: pd.Series, periods_per_year: float) -> dict:
    """Pass the TWR index (or an equity curve with no deposits)."""
    r = series.pct_change().dropna()
    if len(r) < 2 or r.std() == 0:
        return {"ret": float(series.iloc[-1] / series.iloc[0] - 1), "sharpe": 0.0, "max_dd": 0.0, "n": int(len(r))}
    return {"ret": float(series.iloc[-1] / series.iloc[0] - 1),
            "sharpe": float(r.mean() / r.std() * np.sqrt(periods_per_year)),
            "max_dd": float((series / series.cummax() - 1).min()), "n": int(len(r)),
            "vol": float(r.std() * np.sqrt(periods_per_year))}
