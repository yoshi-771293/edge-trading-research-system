import numpy as np
import pandas as pd
import pytest
from referee import replay, risk, universe


def _targets(bars, fn):
    idx = bars["BTCUSDT"].index
    t = pd.DataFrame(0.0, index=idx, columns=list(bars))
    fn(t)
    return t


def test_decision_on_bar_t_fills_at_open_of_t_plus_1(bars):
    idx = bars["BTCUSDT"].index
    t = _targets(bars, lambda t: t.__setitem__("BTCUSDT", t["BTCUSDT"].mask(t.index >= t.index[100], 0.5)))
    r = replay.execute(bars, t, start_equity=1000.0)
    assert len(r.trades) >= 1                # later rebalances toward 50% are expected
    tr = r.trades.iloc[0]                    # the FIRST fill is the one that proves timing
    assert tr["time"] == idx[101]
    assert tr["ref_open"] == bars["BTCUSDT"]["open"].iloc[101]
    assert tr["fill"] > tr["ref_open"]


def test_fill_never_equals_any_price_of_decision_bar(bars):
    t = _targets(bars, lambda t: t.__setitem__("BTCUSDT", t["BTCUSDT"].mask(t.index >= t.index[100], 0.5)))
    r = replay.execute(bars, t, start_equity=1000.0)
    b = bars["BTCUSDT"].iloc[100]
    assert r.trades.iloc[0]["fill"] not in (b.open, b.high, b.low, b.close)


def test_net_is_worse_than_gross_on_every_trade(bars):
    t = _targets(bars, lambda t: None)
    t["BTCUSDT"] = [0.5 if (i // 50) % 2 else 0.0 for i in range(len(t))]   # in/out every 50 bars
    r = replay.execute(bars, t, start_equity=1000.0)
    assert len(r.trades) > 5
    assert (r.trades["fee"] > 0).all()
    assert (r.trades["slippage"] > 0).all()
    assert r.equity_gross.iloc[-1] > r.equity.iloc[-1]


def test_exposure_never_exceeds_100pct_and_asset_cap(bars):
    t = _targets(bars, lambda t: None); t[:] = 1.0                          # asks 200%
    r = replay.execute(bars, t, start_equity=1000.0, kill_switch=False)
    assert r.exposure.max() <= 1.0 + 1e-9
    assert r.weights.max().max() <= risk.MAX_ASSET_FRAC + 0.05


def test_kill_switch_halts_and_flattens():
    from tests.conftest import synth_bars
    b = synth_bars(n=2000, seed=7)
    b["BTCUSDT"]["close"] *= np.exp(np.linspace(0, -1.2, 2000))   # forced crash
    b["BTCUSDT"]["open"] *= np.exp(np.linspace(0, -1.2, 2000))
    t = pd.DataFrame(0.0, index=b["BTCUSDT"].index, columns=list(b)); t["BTCUSDT"] = 0.6
    r = replay.execute(b, t, start_equity=1000.0)
    assert r.killed_at is not None
    after = r.exposure[r.exposure.index > r.killed_at]
    assert (after.iloc[1:] < 0.01).all()
    assert (r.trades["time"] > r.killed_at + (t.index[1] - t.index[0])).sum() == 0


def test_buy_and_hold_parity_with_closed_form(bars):
    r = replay.buy_and_hold(bars, {"BTCUSDT": 1.0}, start_equity=1000.0)  # default venue
    px = bars["BTCUSDT"]
    # bought at open[1] (worse), held to last close: closed form ignoring costs
    naive = 1000.0 * px["close"].iloc[-1] / px["open"].iloc[1]
    assert r.equity.iloc[-1] < naive                      # costs make it worse
    assert r.equity.iloc[-1] > naive * (1 - 0.10)         # but only by the modelled friction
    assert len(r.trades) == 1


def test_strict_loop_matches_vectorized_targets(bars):
    """The referee's bar-by-bar loop (sees bar t, decides, then sees t+1) must produce
    exactly the frame a causal vectorized rule produces. This is how a family proves
    it is causal by construction."""
    def vectorized(close):
        on = (close > close.rolling(50).mean()).astype(float)
        return on.div(on.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

    def decide(history_close):          # only ever receives bars[:t+1]
        return vectorized(history_close).iloc[-1]

    close = pd.concat({s: d["close"] for s, d in bars.items()}, axis=1)
    strict = replay.strict_targets(close, decide, sample_every=97)
    vec = vectorized(close)
    pd.testing.assert_frame_equal(strict, vec.loc[strict.index], check_names=False)


def test_fill_bar_is_the_same_code_path_the_replay_uses(bars):
    """The live agent fills through replay.fill_bar. It must reproduce execute()'s
    first trade exactly, so live and backtest share one execution path."""
    t = _targets(bars, lambda t: t.__setitem__("BTCUSDT", t["BTCUSDT"].mask(t.index >= t.index[100], 0.5)))
    r = replay.execute(bars, t, start_equity=1000.0)
    first = r.trades.iloc[0]
    syms = list(bars)
    idx = bars[syms[0]].index
    o = np.array([bars[s]["open"].iloc[101] for s in syms])
    qv = np.array([bars[s]["quote_volume"].iloc[101] for s in syms])
    mb, md = universe.liquidity(bars, idx, syms)
    mqv, mdq = mb.iloc[101].values, md.iloc[101].values
    pending = risk.apply_np(np.array([0.5, 0.0]), 1000.0, np.zeros(2))   # engine's own sizing
    units, cash, fills, _ = replay.fill_bar(pending, np.zeros(2), 1000.0, o, qv, mqv, mdq,
                                            can_buy=np.array([True, True]), style="taker")
    assert len(fills) == 1
    assert abs(fills[0]["fill"] - first["fill"]) < 1e-9
    assert abs(units[0] - first["units"]) < 1e-12
    assert cash < 1000.0 - pending[0] * 0.99
