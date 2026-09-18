"""Calibration probes for the harness. NOT strategies, and never to be traded.

Sixty-nine strategies have been rejected by this harness. Every one of those verdicts
rests on an assumption that was never tested: that the harness can detect an edge when
one is genuinely present. An instrument that rejects everything, including things that
are true, is not strict but broken, and its negatives carry no information.

These probes inject edges of KNOWN size so the harness can be measured against them.

The design that works. A first attempt used a rule that peeked one bar ahead, and the
causality battery refused to score it, which was the guard doing its job. So the edge is
injected into the DATA instead: `predictable_panel` generates prices whose returns carry
a known autocorrelation rho, and `momentum_rule` reads only the past. The rule is
entirely causal, the edge is entirely real, and its size is set by a dial.

Theory gives the answer to check against. For returns with r_t = rho*r_{t-1} + noise, a
rule that is long after an up bar earns about rho*sqrt(2/pi) per bar, so its annualised
Sharpe should be near rho*0.798*sqrt(365). If the harness reports materially less than
that, it is losing real signal somewhere.

`oracle_rule` is retained ONLY as a tripwire on the guard itself: it peeks, and a test
asserts the causality battery rejects it.

`random_rule` is the opposite bound: causal, informationless, matched turnover. It must
score near zero and fail the gates.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

USES_FUTURE_INFORMATION = True          # the oracle only; random_rule is causal


def _normalise(w: pd.DataFrame) -> pd.DataFrame:
    tot = w.sum(axis=1)
    over = tot > 1.0
    if over.any():
        w.loc[over] = w.loc[over].div(tot[over], axis=0)
    return w.fillna(0.0)


def oracle_rule(accuracy: float = 0.75, seed: int = 0, k: int = 3):
    """PROBE ONLY. Holds k coins chosen with knowledge of tomorrow's return, correct
    `accuracy` of the time. accuracy=0.5 is a coin flip; 1.0 is perfect foresight."""
    def rule(close: pd.DataFrame) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        fwd = close.shift(-1) / close - 1                     # <-- the deliberate peek
        up = fwd > 0
        # flip each cell to the wrong answer with probability (1 - accuracy)
        keep = rng.random(up.shape) < accuracy
        view = pd.DataFrame(np.where(keep, up.values, ~up.values), index=close.index,
                            columns=close.columns)
        view = view & fwd.notna()
        # rank by how strongly we "believe", so the k held are a deterministic choice
        score = pd.DataFrame(rng.random(up.shape), index=close.index, columns=close.columns).where(view)
        rank = score.rank(axis=1, ascending=False, method="first")
        w = (rank <= k).astype(float) / float(k)
        return _normalise(w.where(view, 0.0))
    rule.__name__ = f"oracle:{accuracy}"
    return rule


_MAX_BARS = 200_000


def random_rule(rate: float = 0.3, seed: int = 0, k: int = 3, n_cols: int = 64):
    """Causal and informationless: holds k symbols picked at random, changing its mind at
    roughly `rate` per bar so turnover resembles a real strategy.

    The randomness is keyed to the ROW POSITION from a single pre-drawn table, not drawn
    sequentially. Sequential draws make the output depend on how much data was passed,
    so truncating the input changes earlier rows and the causality battery rejects the
    rule even though it never looks forward. Position-keyed draws are truncation-stable."""
    table = np.random.default_rng(seed).random((_MAX_BARS, n_cols + 1))

    def rule(close: pd.DataFrame) -> pd.DataFrame:
        n, m = close.shape
        score = table[:n, :m]
        switch = table[:n, -1] < rate
        switch[0] = True
        # carry the last chosen row forward: backward-looking only
        idx_of_choice = np.maximum.accumulate(np.where(switch, np.arange(n), 0))
        hold = score[idx_of_choice]
        s = pd.DataFrame(hold, index=close.index, columns=close.columns).where(close.notna())
        rank = s.rank(axis=1, ascending=False, method="first")
        return _normalise((rank <= k).astype(float) / float(k))
    rule.__name__ = f"random:{rate}"
    return rule


def predictable_panel(rho: float, n: int = 2000, k: int = 6, seed: int = 0,
                      vol: float = 0.012, half_spread: float = 2e-5,
                      start: str = "2018-01-01", freq: str = "1D") -> dict:
    """Prices whose returns carry a KNOWN autocorrelation rho. rho=0 is a random walk
    with no edge to find; rho>0 means yesterday's direction genuinely predicts today's.
    Everything a strategy needs is in the past, so a causal rule can capture it."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    out = {}
    for i in range(k):
        eps = rng.normal(0.0, vol, n)
        r = np.zeros(n)
        for t in range(1, n):
            r[t] = rho * r[t - 1] + eps[t]
        # Subtract the Jensen term so the ARITHMETIC return has zero mean. Without this
        # a zero-rho panel still drifts upward and any long-biased rule scores positive
        # on it, which would make the control read as an edge where none was injected.
        c = 100 * np.exp(np.cumsum(r - 0.5 * vol ** 2))
        o = np.concatenate([[c[0]], c[:-1]])
        out[f"S{i}"] = pd.DataFrame(
            {"open": o, "high": np.maximum(o, c) * 1.002, "low": np.minimum(o, c) * 0.998,
             "close": c, "volume": 1e6, "quote_volume": 1e9,
             "half_spread": half_spread, "open_half_spread": half_spread * 1.5}, index=idx)
    return out


def theoretical_sharpe(rho: float, periods_per_year: float = 365.0) -> float:
    """What a perfect reader of that autocorrelation should earn, before costs."""
    return float(rho * np.sqrt(2.0 / np.pi) * np.sqrt(periods_per_year))


def momentum_rule(k: int = 3, lookback: int = 1):
    """Fully causal: hold the k symbols with the strongest return over the last
    `lookback` bars. On a predictable panel this captures the injected edge."""
    def rule(close: pd.DataFrame) -> pd.DataFrame:
        past = close / close.shift(lookback) - 1
        elig = past.notna() & (past > 0)
        rank = past.where(elig).rank(axis=1, ascending=False, method="first")
        return _normalise((rank <= k).astype(float) / float(k))
    rule.__name__ = f"momentum:{lookback}:{k}"
    return rule


def detection_floor(n_trials: int = 69, bar: str = "1d", n: int = 2000, k: int = 6,
                    grid=(0.0, 0.02, 0.04, 0.06, 0.08, 0.12, 0.16), seed: int = 0,
                    half_spread: float = 2e-5, cost_model=None) -> dict:
    """The smallest REAL edge this harness will still call eligible. It bounds what the
    rejections actually rule out: anything weaker than this could be present and unseen."""
    from referee import validate
    rows, floor = [], None
    for rho in grid:
        bars = predictable_panel(rho, n=n, k=k, seed=seed, half_spread=half_spread)
        close = pd.concat({s: d["close"] for s, d in bars.items()}, axis=1)
        uni = pd.DataFrame(True, index=close.index, columns=close.columns)
        from referee import costmodels
        cm = cost_model if cost_model is not None else costmodels.ForexCosts()
        rep = validate.walk_forward(bars, {"mom": momentum_rule(k=3)}, bar=bar,
                                    n_trials=n_trials, uni=uni, cost_model=cm)
        ok = bool(rep.get("sharpe_net", 0) > 0 and rep.get("deflated", {}).get("psr", 0) >= 0.5
                  and rep.get("min_trades_ok"))
        rows.append({"rho": rho, "theoretical_sharpe": theoretical_sharpe(rho),
                     "measured_sharpe": rep.get("sharpe_net"), "gross": rep.get("sharpe_gross"),
                     "psr": rep.get("deflated", {}).get("psr"),
                     "trades": rep.get("n_trades"), "passes": ok})
        if ok and floor is None:
            floor = {"rho": rho, "sharpe_at_floor": rep["sharpe_net"],
                     "theoretical_at_floor": theoretical_sharpe(rho)}
    out = floor or {"rho": float("inf"), "sharpe_at_floor": 0.0, "theoretical_at_floor": float("inf")}
    out["ladder"] = rows
    return out
