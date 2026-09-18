"""Data-integrity gate. Two hazards that would manufacture enormous fake profits:

1. NOT-SPOT instruments. Binance leveraged tokens (BTCUP, ETHDOWN, XRPBULL) are
   derivatives with periodic redenominations, which show up as 100,000x one-day
   "gains". The spec is spot only, so they must be removed.
2. TICKER REUSE. Binance reassigned LUNAUSDT from Terra (which went to $0.00005) to
   Terra 2.0 (which opened near $8.87). Unhandled, that is a 177,399x single-bar gain
   for anyone holding the corpse. The series must be cut at the seam.
"""
import numpy as np
import pandas as pd
import pytest
from referee import universe

ALL = ["BTC", "ETH", "XRP", "EOS", "JUP", "SYRUP", "BTCUP", "BTCDOWN", "ETHDOWN",
       "XRPBULL", "EOSBEAR", "USDC", "BUSD", "EUR", "SOL", "LUNA"]
ALL_SYMS = [s + "USDT" for s in ALL]


@pytest.mark.parametrize("sym", ["BTCUPUSDT", "BTCDOWNUSDT", "ETHDOWNUSDT", "XRPBULLUSDT", "EOSBEARUSDT"])
def test_leveraged_tokens_are_rejected(sym):
    assert not universe.is_spot_symbol(sym, ALL_SYMS)


@pytest.mark.parametrize("sym", ["JUPUSDT", "SYRUPUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "LUNAUSDT"])
def test_real_coins_are_kept(sym):
    assert universe.is_spot_symbol(sym, ALL_SYMS), f"{sym} wrongly excluded"


@pytest.mark.parametrize("sym", ["USDCUSDT", "BUSDUSDT", "EURUSDT"])
def test_stablecoin_and_fiat_pairs_are_rejected(sym):
    """A near-constant 1.00 price with huge volume would rank top-30 and look like a
    magical zero-risk asset to any low-volatility rule."""
    assert not universe.is_spot_symbol(sym, ALL_SYMS)


def _series(vals, start="2022-01-01"):
    idx = pd.date_range(start, periods=len(vals), freq="1D", tz="UTC")
    v = np.asarray(vals, dtype=float)
    return pd.DataFrame({"open": v, "high": v, "low": v, "close": v,
                         "volume": 1e6, "quote_volume": 1e8}, index=idx)


def test_seam_detected_on_ticker_reuse():
    vals = [30.0, 10.0, 0.001, 0.00005, 8.87, 6.52, 5.0]     # the real LUNA shape
    seam = universe.first_seam(_series(vals)["close"])
    assert seam is not None
    assert seam == _series(vals).index[4]


def test_no_seam_on_a_violent_but_real_crash():
    vals = [30.0, 22.0, 9.0, 4.0, 1.2, 0.3, 0.05]            # -99% over days, all real
    assert universe.first_seam(_series(vals)["close"]) is None


def test_clean_truncates_at_the_seam_and_keeps_prior_history():
    bars = {"LUNAUSDT": _series([30.0, 10.0, 0.001, 0.00005, 8.87, 6.52])}
    out = universe.clean(bars, ALL_SYMS, min_bars=3)
    assert "LUNAUSDT" in out
    assert len(out["LUNAUSDT"]) == 4
    assert out["LUNAUSDT"]["close"].iloc[-1] == pytest.approx(0.00005)


def test_clean_removes_non_spot_and_stablecoins():
    bars = {s: _series([1.0, 1.01, 1.0]) for s in ["BTCUSDT", "ETHDOWNUSDT", "USDCUSDT", "JUPUSDT"]}
    out = universe.clean(bars, ALL_SYMS, min_bars=3)
    assert set(out) == {"BTCUSDT", "JUPUSDT"}


def test_clean_drops_series_too_short_to_use():
    bars = {"BTCUSDT": _series([1.0] * 200), "TINYUSDT": _series([1.0, 1.0])}
    out = universe.clean(bars, ALL_SYMS + ["TINYUSDT"], min_bars=50)
    assert set(out) == {"BTCUSDT"}
