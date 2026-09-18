"""Validation harness: walk-forward windows, deflated Sharpe, trade gate, regime
segmentation, tripwire, causality battery."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.stats import norm, skew, kurtosis

MIN_TRADES = 100
TRIP_SHARPE = 3.0
TRIP_SINGLE_BAR = 0.15
TRIP_STREAK = 10                # legacy floor; the live threshold scales with sample size
STREAK_MARGIN = 7               # days above the expected longest run before we call it a bug.
                                # Calibrated by simulation: the threshold then sits at
                                # about the 99.9th percentile of the longest run in pure
                                # noise (17/18/20 days at n=500/2,000/5,000), so the rule
                                # fires roughly once in a thousand honest runs instead of
                                # the 62% of the time the old fixed 10 did.
ROLLING_SHARPE_SIGMAS = 4.0     # how far a window may sit above the strategy's own level
SINGLE_REGIME_SHARE = 0.80


def windows(index: pd.DatetimeIndex, train_days=365, test_days=91, warmup_days=200):
    t0 = index[0] + pd.Timedelta(days=warmup_days)
    out = []
    while True:
        tr1 = t0 + pd.Timedelta(days=train_days - 1)
        te0 = tr1 + pd.Timedelta(days=1)
        te1 = te0 + pd.Timedelta(days=test_days - 1)
        if te1 > index[-1]:
            break
        out.append((t0, tr1, te0, te1))
        t0 += pd.Timedelta(days=test_days)
    return out


def deflated_sharpe(returns, n_trials: int, periods_per_year: float) -> dict:
    """Bailey & Lopez de Prado (2014). Returns the observed annualised Sharpe, the
    expected max Sharpe from n_trials of noise, and the probability the observed
    Sharpe exceeds it (PSR against that benchmark)."""
    r = np.asarray(returns, dtype=float); n = len(r)
    if n < 3 or r.std() == 0:
        return {"sharpe": 0.0, "expected_max_sharpe": 0.0, "psr": 0.0, "n": n}
    sr = r.mean() / r.std()                                   # per-period
    sk, ku = float(skew(r)), float(kurtosis(r, fisher=False))
    e_max = 0.0
    if n_trials > 1:
        gamma = 0.5772156649
        e_max = (1 - gamma) * norm.ppf(1 - 1 / n_trials) + gamma * norm.ppf(1 - 1 / (n_trials * np.e))
        e_max *= 1.0 / np.sqrt(n - 1)                          # scale by SR std under H0
    denom = np.sqrt(max(1 - sk * sr + (ku - 1) / 4 * sr ** 2, 1e-12) / (n - 1))
    psr = float(norm.cdf((sr - e_max) / denom))
    return {"sharpe": float(sr * np.sqrt(periods_per_year)), "expected_max_sharpe": float(e_max * np.sqrt(periods_per_year)),
            "psr": psr, "n": n}


def passes_min_trades(n_trades: int) -> bool:
    return n_trades >= MIN_TRADES


@dataclass
class Trip:
    tripped: bool
    reason: str = ""


def streak_threshold(n: int, p: float = 0.5, margin: int = STREAK_MARGIN) -> int:
    """Longest run of winning days that would be genuinely surprising in n days.

    The longest run in a series GROWS with the series: the expectation is about
    log(n)/log(1/p), which is roughly 11 for 2,000 fair days. A fixed threshold of 10
    therefore fired on pure noise 62% of the time and on any real edge as well, so it
    carried no information. This scales it and adds a margin."""
    n = max(int(n), 2)
    p = min(max(float(p), 0.05), 0.95)
    expected = np.log(n) / np.log(1.0 / p)
    return int(max(TRIP_STREAK, np.ceil(expected) + margin))


def tripwire(net: pd.Series, periods_per_year: float, level_violations: int = 0,
             asset_bound: pd.Series | None = None, benchmark_returns: pd.Series | None = None) -> Trip:
    """Plausibility checks on a NET return series (DatetimeIndex). Anything tripped is a
    suspected simulator bug until proven otherwise.
      sharpe:  full-sample (>= 180 days) or rolling-1y Sharpe > 3, UNLESS the benchmark
               (BTC buy-and-hold) itself exceeded 2 over the same window: a bull run is
               not a bug. (BTC's own 1y Sharpe passed 3 in 2020-21.)
      single:  any calendar DAY above +15% (bars are resampled to days first).
      streak:  a run of winning days longer than is surprising for a series of this
               length at this win rate. A FIXED threshold cannot work: the longest run
               grows with the sample, so 10 fired on 62% of 2,000-day noise runs.
      net>gross: the caller counted bars where net equity LEVEL exceeded gross level.
      asset:   a bar return above the best any asset offered from open/close prices
               (impossible for long-only spot without leverage).
    """
    net = net.dropna()
    if len(net) == 0:
        return Trip(False, "no data")
    reasons = []
    daily = net
    if isinstance(net.index, pd.DatetimeIndex) and periods_per_year > 365:
        daily = (1 + net).resample("1D").prod() - 1
        daily = daily[daily.index <= net.index[-1]]
    bench = None                      # DataFrame of candidate benchmarks (any column may exempt)
    if benchmark_returns is not None:
        bench = benchmark_returns.to_frame() if isinstance(benchmark_returns, pd.Series) else benchmark_returns
        bench = bench.reindex(daily.index).fillna(0.0)
    def _sh(x):
        return float(x.mean() / x.std() * np.sqrt(365)) if len(x) > 2 and x.std() > 0 else 0.0
    full = _sh(daily) if len(daily) >= 180 else 0.0
    if len(daily) >= 180:
        if full > TRIP_SHARPE and not (bench is not None and any(_sh(bench[c]) > 2.0 for c in bench)):
            reasons.append(f"sharpe {full:.2f} > {TRIP_SHARPE} sustained over the full sample "
                           f"({len(daily)} days)")
    # A single hot year is not a bug. A strategy whose true Sharpe is 1.2 throws one-year
    # windows above 3 by ordinary sampling, and the old absolute rule flagged exactly
    # that. What IS a bug is a window wildly out of line with the strategy's own level,
    # so the comparison is against `full` plus the sampling error of a one-year Sharpe.
    if len(daily) > 365 * 2:
        roll = daily.rolling(365)
        sh = (roll.mean() / roll.std() * np.sqrt(365)).dropna()
        se = np.sqrt((1.0 + 0.5 * full ** 2) / 365.0) * np.sqrt(365.0)
        ceiling = full + ROLLING_SHARPE_SIGMAS * max(se, 0.5)
        hot = sh[sh > ceiling]
        if bench is not None and len(hot):
            rb = bench.rolling(365)
            shb = (rb.mean() / rb.std() * np.sqrt(365)).reindex(hot.index)
            hot = hot[~(shb > 2.0).any(axis=1)]
        if len(hot):
            reasons.append(f"a 1y window reached sharpe {hot.max():.2f} against this strategy's own "
                           f"{full:.2f} (ceiling {ceiling:.2f}), which the benchmark did not")
    # A large day is only implausible if it exceeds what the market actually offered.
    # A concentrated position in a volatile altcoin really can gain 20% in a day.
    big = daily[daily > TRIP_SINGLE_BAR]
    if bench is not None and len(big):
        big = big[~(bench.reindex(big.index).ge(big, axis=0)).any(axis=1)]
    if asset_bound is not None and len(big):
        ab = asset_bound.reindex(net.index)
        ab_daily = ((1 + ab.fillna(0.0)).resample("1D").prod() - 1) if periods_per_year > 365 else ab
        big = big[~(ab_daily.reindex(big.index).fillna(0.0) >= big)]
    if len(big):
        reasons.append(f"single day return {big.max():.1%} > {TRIP_SINGLE_BAR:.0%}, "
                       f"more than any available coin offered that day")
    if level_violations > 0:
        reasons.append(f"net>gross (cost model bypassed) on {level_violations} bars")
    if asset_bound is not None:
        b = asset_bound.reindex(net.index)
        over = net > b + 1e-9
        if over.any():
            reasons.append(f"asset bound exceeded on {int(over.sum())} bars (max {float((net - b).max()):.2%} above best asset)")
    def _streaks(x):
        w = (x > 0).astype(int)
        return w.groupby((w != w.shift()).cumsum()).cumsum() if len(w) else w
    st = _streaks(daily)
    win_rate = float((daily > 0).mean()) if len(daily) else 0.5
    thresh = streak_threshold(len(daily), win_rate)
    hot = st[st >= thresh]
    if bench is not None and len(hot):
        bs = bench.apply(_streaks)
        hot = hot[~(bs.reindex(hot.index) >= thresh).any(axis=1)]   # some benchmark ran the same streak
    if len(hot):
        reasons.append(f"win streak {int(st.max())} >= {thresh}, the surprising level for "
                       f"{len(daily)} days at a {win_rate:.0%} win rate (benchmark did not)")
    return Trip(bool(reasons), "; ".join(reasons))


def asset_bound(bars: dict) -> pd.Series:
    """Per bar, the most a long-only spot account could have earned: the best asset's
    max of close/prev-close, close/open and open/prev-close, floored at zero."""
    parts = []
    for d in bars.values():
        c, o = d["close"], d["open"]; pc = c.shift(1)
        parts.append(pd.concat([c / pc, c / o, o / pc], axis=1).max(axis=1) - 1)
    return pd.concat(parts, axis=1).max(axis=1).clip(lower=0.0).fillna(0.0)


def benchmark_daily_returns(bars: dict) -> pd.DataFrame:
    """Daily returns of the things a long-only account could trivially have been:
    the majors, and an equal-weight basket of whatever is present."""
    cols = {}
    for s_ in ("BTCUSDT", "ETHUSDT"):
        if s_ in bars:
            cols[s_] = bars[s_]["close"].resample("1D").last().dropna().pct_change().fillna(0.0)
    cols["basket"] = market_proxy(bars).pct_change().fillna(0.0)
    return pd.DataFrame(cols).fillna(0.0)


def segment_by_regime(returns: pd.Series, labels: pd.DataFrame) -> dict:
    lab = labels.reindex(returns.index)
    out = {}
    pnl_by = {}
    for col in ["trend", "vol"]:
        for k, g in returns.groupby(lab[col]):
            if len(g) > 1 and g.std() > 0:
                out[f"{col}:{k}"] = {"n": int(len(g)), "mean": float(g.mean()), "sharpe_raw": float(g.mean() / g.std())}
            else:
                out[f"{col}:{k}"] = {"n": int(len(g)), "mean": float(g.mean()), "sharpe_raw": 0.0}
            pnl_by[f"{col}:{k}"] = float(g.sum())
    for k, g in returns.groupby(lab["chop"]):
        out[f"chop:{k}"] = {"n": int(len(g)), "mean": float(g.mean())}
    # Share of GROSS profit, so the ratio is bounded in [0, 1]. The old version divided
    # by the sum of positive returns only, which let the share exceed 1 and mislabel.
    trend_pnl = {k: x for k, x in pnl_by.items() if k.startswith("trend:")}
    gains = {k: max(x, 0.0) for k, x in trend_pnl.items()}
    total_gain = sum(gains.values())
    dominant = max(gains, key=gains.get) if gains else None
    share = (gains[dominant] / total_gain) if (dominant and total_gain > 0) else 0.0
    single = bool(dominant and total_gain > 0 and share >= SINGLE_REGIME_SHARE)
    return {"cells": out, "single_regime": single, "dominant_share": float(share),
            "dominant": dominant.split(":")[1] if dominant else None}


@dataclass
class Battery:
    passed: bool
    detail: str = ""


def causality_battery(rule, close: pd.DataFrame, cuts=(0.3, 0.6, 0.9), seed=0) -> Battery:
    """Shuffle / scale / truncate everything after a cut; rows <= cut must be identical."""
    base = rule(close)
    rng = np.random.default_rng(seed)
    n = len(close)
    for frac in cuts:
        cut = int(n * frac)
        fut = close.index[cut + 1:]
        variants = {}
        c1 = close.copy(); c1.loc[fut] = c1.loc[fut].values * rng.uniform(0.2, 5.0, (len(fut), close.shape[1])); variants["scaled"] = c1
        c2 = close.copy(); c2.loc[fut] = c2.loc[fut].sample(frac=1.0, random_state=int(rng.integers(1e9))).values; variants["shuffled"] = c2
        variants["truncated"] = close.iloc[:cut + 1]
        for name, v in variants.items():
            alt = rule(v)
            a = base.iloc[:cut + 1].fillna(-999).values; b = alt.iloc[:cut + 1].fillna(-999).values
            if a.shape != b.shape or not np.allclose(a, b, atol=1e-12):
                bad = int(np.argmax((np.abs(a - b) > 1e-12).any(axis=1))) if a.shape == b.shape else -1
                return Battery(False, f"{name} future at cut {cut} changed row {bad}")
    return Battery(True, "identical under scaled/shuffled/truncated future at 3 cuts")


# ---------------------------------------------------------------------------
# Audited entry points. The player scores candidates ONLY through these.
# ---------------------------------------------------------------------------
from . import data as _data, regimes as _regimes, replay as _replay


def _close(bars):
    return pd.concat({s: d["close"] for s, d in bars.items()}, axis=1)


def _gross_twr(r) -> pd.Series:
    """Deposit-neutral index for the friction-free twin, so net and gross compare
    like with like even when money is being paid in."""
    dep = r.contributed.diff().fillna(0.0)
    step = (r.equity_gross - dep) / r.equity_gross.shift(1)
    return step.fillna(1.0).cumprod()


def market_proxy(bars: dict) -> pd.Series:
    """Bitcoin when present, otherwise an equal-weight basket of what is. Used for
    regime labels and benchmark exemptions, so the referee never assumes a universe."""
    if "BTCUSDT" in bars:
        return bars["BTCUSDT"]["close"].resample("1D").last().dropna()
    daily = [d["close"].resample("1D").last().dropna() for d in list(bars.values())[:40]]
    r = pd.concat([x.pct_change() for x in daily], axis=1).mean(axis=1).fillna(0.0)
    return (1 + r).cumprod()


def _daily_labels(bars, index):
    return _regimes.daily_labels_for(index, market_proxy(bars))


def _oos_slices(index, wins):
    mask = pd.Series(False, index=index)
    for _, _, te0, te1 in wins:
        mask[(index >= te0) & (index <= te1)] = True
    return mask


def evaluate(bars: dict, rule, bar: str, n_trials: int, start_equity: float = 1000.0,
             uni=None, monthly_deposit: float = 0.0, venue=None, style: str = "taker",
             cost_model=None) -> dict:
    """Score ONE fixed rule (a function close_df -> target weights). Reports gross and
    net, per-window OOS results, deflated Sharpe against n_trials, trade gate, regime
    segmentation, tripwire and the causality battery. Kill switch is OFF here so the
    whole history is scored; drawdown is reported instead."""
    ppy = _data.PERIODS_PER_YEAR[bar]
    close = _close(bars)
    caus = causality_battery(rule, close)
    targets = rule(close)
    r = _replay.execute(bars, targets, universe=uni, start_equity=start_equity,
                        monthly_deposit=monthly_deposit, kill_switch=False, venue=venue, style=style,
                        cost_model=cost_model)
    wins = windows(close.index)
    oos = _oos_slices(close.index, wins)
    net_r = r.twr.pct_change().fillna(0.0)[oos]
    gross_r = _gross_twr(r).pct_change().fillna(0.0)[oos]
    per_window = []
    for i, (tr0, tr1, te0, te1) in enumerate(wins):
        gt = _gross_twr(r)
        e = r.twr[(r.twr.index >= te0) & (r.twr.index <= te1)]
        g = gt[(gt.index >= te0) & (gt.index <= te1)]
        if len(e) < 2:
            continue
        tr = r.trades[(r.trades["time"] >= te0) & (r.trades["time"] <= te1)] if len(r.trades) else r.trades
        per_window.append({"window": i + 1, "test": f"{te0.date()}..{te1.date()}",
                           "net_ret": float(e.iloc[-1] / e.iloc[0] - 1), "gross_ret": float(g.iloc[-1] / g.iloc[0] - 1),
                           "net_sharpe": _replay.metrics(e, ppy)["sharpe"], "n_trades": int(len(tr))})
    n_trades = int(sum(w["n_trades"] for w in per_window))
    dsr = deflated_sharpe(net_r.values, n_trials, ppy)
    viol = int((r.twr > _gross_twr(r) * (1 + 1e-9)).sum())
    trip = tripwire(net_r, ppy, level_violations=viol, asset_bound=asset_bound(bars), benchmark_returns=benchmark_daily_returns(bars))
    labels = _daily_labels(bars, net_r.index)
    seg = segment_by_regime(net_r, labels)
    net_sh = float(net_r.mean() / net_r.std() * np.sqrt(ppy)) if net_r.std() > 0 else 0.0
    gross_sh = float(gross_r.mean() / gross_r.std() * np.sqrt(ppy)) if gross_r.std() > 0 else 0.0
    eligible = bool(caus.passed and passes_min_trades(n_trades) and not trip.tripped and net_sh > 0)
    return {"bar": bar, "n_windows": len(per_window), "windows": per_window,
            "net": _replay.metrics(r.twr, ppy), "gross": _replay.metrics(_gross_twr(r), ppy),
            "final_equity": float(r.equity.iloc[-1]), "contributed": float(r.contributed.iloc[-1]),
            "profit": float(r.profit.iloc[-1]),
            "sharpe_net": net_sh, "sharpe_gross": gross_sh, "oos_net_ret": float((1 + net_r).prod() - 1),
            "oos_gross_ret": float((1 + gross_r).prod() - 1),
            "windows_positive": float(np.mean([w["net_ret"] > 0 for w in per_window])) if per_window else 0.0,
            "deflated": dsr, "n_trades": n_trades, "min_trades_ok": passes_min_trades(n_trades),
            "regime": seg, "tripwire": {"tripped": trip.tripped, "reason": trip.reason},
            "causality": {"passed": caus.passed, "detail": caus.detail}, "total_costs": float(r.total_costs),
            "avg_exposure": float(r.exposure.mean()), "eligible": eligible}


def walk_forward(bars: dict, variants: dict, bar: str, n_trials: int, start_equity: float = 1000.0,
                 uni=None, monthly_deposit: float = 0.0, venue=None, style: str = "taker",
                 cost_model=None) -> dict:
    """Selection-honest walk-forward for a FAMILY: `variants` maps param -> rule.
    On each train window the best variant by net Sharpe is chosen; only its next test
    window counts. The stitched OOS series is the family's honest expectation."""
    ppy = _data.PERIODS_PER_YEAR[bar]
    close = _close(bars)
    runs = {}
    for p, rule in variants.items():
        caus = causality_battery(rule, close)
        if not caus.passed:
            return {"eligible": False, "causality": {"passed": False, "detail": f"param {p}: {caus.detail}"}}
        runs[p] = _replay.execute(bars, rule(close), universe=uni, start_equity=start_equity,
                                  monthly_deposit=monthly_deposit, kill_switch=False,
                                  venue=venue, style=style, cost_model=cost_model)
    wins = windows(close.index)
    chosen, net_parts, gross_parts, paper_parts, per_window, n_trades, viol = [], [], [], [], [], 0, 0
    for i, (tr0, tr1, te0, te1) in enumerate(wins):
        best, best_sh = None, -np.inf
        for p, r in runs.items():
            e = r.twr[(r.twr.index >= tr0) & (r.twr.index <= tr1)]
            sh = _replay.metrics(e, ppy)["sharpe"] if len(e) > 2 else -np.inf
            if sh > best_sh:
                best, best_sh = p, sh
        r = runs[best]
        gt = _gross_twr(r)
        pt = r.paper_twr if r.paper_twr is not None else gt
        m = (r.twr.index >= te0) & (r.twr.index <= te1)
        e, g, pp = r.twr[m], gt[m], pt[m]
        if len(e) < 2:
            continue
        net_parts.append(e.pct_change().fillna(0.0)); gross_parts.append(g.pct_change().fillna(0.0))
        paper_parts.append(pp.pct_change().fillna(0.0))
        viol += int((e > g * (1 + 1e-9)).sum())
        tr = r.trades[(r.trades["time"] >= te0) & (r.trades["time"] <= te1)] if len(r.trades) else r.trades
        n_trades += int(len(tr)); chosen.append(best)
        per_window.append({"window": i + 1, "test": f"{te0.date()}..{te1.date()}", "param": best,
                           "net_ret": float(e.iloc[-1] / e.iloc[0] - 1), "gross_ret": float(g.iloc[-1] / g.iloc[0] - 1),
                           "net_sharpe": _replay.metrics(e, ppy)["sharpe"], "n_trades": int(len(tr))})
    if not per_window:
        return {"eligible": False, "causality": {"passed": True}, "n_windows": 0, "windows": []}
    net_r, gross_r = pd.concat(net_parts), pd.concat(gross_parts)
    paper_r = pd.concat(paper_parts) if paper_parts else gross_r
    dsr = deflated_sharpe(net_r.values, n_trials, ppy)
    trip = tripwire(net_r, ppy, level_violations=viol, asset_bound=asset_bound(bars), benchmark_returns=benchmark_daily_returns(bars))
    seg = segment_by_regime(net_r, _daily_labels(bars, net_r.index))
    net_sh = float(net_r.mean() / net_r.std() * np.sqrt(ppy)) if net_r.std() > 0 else 0.0
    gross_sh = float(gross_r.mean() / gross_r.std() * np.sqrt(ppy)) if gross_r.std() > 0 else 0.0
    eq = start_equity * (1 + net_r).cumprod()
    eligible = bool(passes_min_trades(n_trades) and not trip.tripped and net_sh > 0)
    paper_sh = float(paper_r.mean() / paper_r.std() * np.sqrt(ppy)) if paper_r.std() > 0 else 0.0
    return {"bar": bar, "n_windows": len(per_window), "windows": per_window, "chosen_params": chosen,
            "last_param": chosen[-1], "sharpe_net": net_sh, "sharpe_gross": gross_sh,
            "sharpe_paper": paper_sh,
            "oos_net_ret": float((1 + net_r).prod() - 1), "oos_gross_ret": float((1 + gross_r).prod() - 1),
            "oos_max_dd": float((eq / eq.cummax() - 1).min()),
            "windows_positive": float(np.mean([w["net_ret"] > 0 for w in per_window])),
            "deflated": dsr, "n_trades": n_trades, "min_trades_ok": passes_min_trades(n_trades),
            "regime": seg, "tripwire": {"tripped": trip.tripped, "reason": trip.reason},
            "causality": {"passed": True}, "eligible": eligible, "oos_index": [str(net_r.index[0]), str(net_r.index[-1])]}
