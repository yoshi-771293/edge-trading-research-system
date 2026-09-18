"""Forex data layer, from Dukascopy's public feed.

Two things make this a better research setting than the crypto side:

1. NO SURVIVORSHIP BIAS TO RECONSTRUCT. EURUSD has never been delisted. The majors
   existed throughout the sample, so the universe is simply fixed.
2. REAL SPREADS, NOT MODELLED ONES. Dukascopy publishes bid and ask candles
   separately, so the actual historical spread is known at every bar instead of being
   estimated. That removes the largest guess in the whole project.

The file format has three traps, each pinned by a test below: the month in the URL is
ZERO-indexed, prices are integers in instrument points rather than floats, and the
field order is open, CLOSE, low, high.
"""
import lzma
import struct
import numpy as np
import pandas as pd
import pytest
from referee import forex


def _rec(offset_s, o, c, l, h, vol, scale):
    return struct.pack(">Iiiiif", offset_s, int(round(o * scale)), int(round(c * scale)),
                       int(round(l * scale)), int(round(h * scale)), vol)


# ---- decoding --------------------------------------------------------------
def test_decodes_the_documented_layout():
    blob = _rec(3600, 1.08462, 1.08466, 1.08453, 1.08495, 1357.71, 1e5)
    df = forex.decode(blob, "EURUSD", pd.Timestamp("2024-06-01", tz="UTC"))
    assert len(df) == 1
    row = df.iloc[0]
    assert row["open"] == pytest.approx(1.08462, abs=1e-6)
    assert row["close"] == pytest.approx(1.08466, abs=1e-6)
    assert row["low"] == pytest.approx(1.08453, abs=1e-6)
    assert row["high"] == pytest.approx(1.08495, abs=1e-6)
    assert df.index[0] == pd.Timestamp("2024-06-01 01:00", tz="UTC")


def test_field_order_is_open_close_low_high_not_ohlc():
    """Reading it as open/high/low/close silently swaps high and close."""
    blob = _rec(0, o=1.10, c=1.20, l=1.05, h=1.25, vol=100.0, scale=1e5)
    row = forex.decode(blob, "EURUSD", pd.Timestamp("2024-01-01", tz="UTC")).iloc[0]
    assert row["high"] == pytest.approx(1.25, abs=1e-6)
    assert row["close"] == pytest.approx(1.20, abs=1e-6)
    assert row["high"] >= row["close"] >= row["low"]


def test_zero_volume_records_are_dropped_as_market_closed():
    blob = _rec(0, 1.1, 1.1, 1.1, 1.1, 0.0, 1e5) + _rec(3600, 1.1, 1.1, 1.1, 1.1, 50.0, 1e5)
    df = forex.decode(blob, "EURUSD", pd.Timestamp("2024-01-01", tz="UTC"))
    assert len(df) == 1, "weekend and holiday gaps must not become flat bars"


def test_jpy_pairs_use_a_different_point_scale():
    assert forex.scale_for("USDJPY") != forex.scale_for("EURUSD")
    blob = _rec(0, 157.25, 157.30, 157.20, 157.40, 100.0, forex.scale_for("USDJPY"))
    row = forex.decode(blob, "USDJPY", pd.Timestamp("2024-06-01", tz="UTC")).iloc[0]
    assert row["open"] == pytest.approx(157.25, abs=1e-3)


def test_the_url_month_is_zero_indexed():
    u = forex.month_url("EURUSD", 2024, 6, "BID")
    assert "/2024/05/" in u, f"June must be month index 05, got {u}"
    assert u.endswith("BID_candles_hour_1.bi5")


# ---- measured spreads ------------------------------------------------------
def _pair_frames():
    idx = pd.date_range("2024-06-03 08:00", periods=5, freq="1h", tz="UTC")
    bid = pd.DataFrame({"open": 1.0840, "high": 1.0850, "low": 1.0835, "close": 1.0845,
                        "volume": 100.0}, index=idx)
    ask = bid + 0.0001
    ask["volume"] = 100.0
    return bid, ask


def test_mid_and_measured_spread_are_built_from_bid_and_ask():
    bid, ask = _pair_frames()
    df = forex.combine(bid, ask)
    assert df["close"].iloc[0] == pytest.approx(1.0845 + 0.00005, abs=1e-9)
    assert df["half_spread"].iloc[0] == pytest.approx(0.00005 / df["close"].iloc[0], rel=1e-6)
    assert (df["half_spread"] > 0).all()


def test_a_crossed_quote_is_rejected_rather_than_used():
    bid, ask = _pair_frames()
    ask["close"] = bid["close"] - 0.001          # ask below bid is impossible
    with pytest.raises(ValueError, match="ask below bid"):
        forex.combine(bid, ask)


def test_measured_spread_beats_the_modelled_one_for_majors():
    """The whole reason to come here: a real EURUSD half-spread is a fraction of a
    basis point, where our altcoin model charged five basis points and up."""
    bid, ask = _pair_frames()
    df = forex.combine(bid, ask)
    from referee import costs, venues
    modelled = costs.half_spread(1e9, venues.get("okx"))
    assert df["half_spread"].mean() < modelled / 10


# ---- resampling ------------------------------------------------------------
def test_daily_resample_is_causal_and_preserves_extremes():
    idx = pd.date_range("2024-06-02 22:00", periods=48, freq="1h", tz="UTC")   # forex day starts 22:00 UTC
    rng = np.random.default_rng(0)
    c = 1.08 + rng.normal(0, 0.001, 48)
    h = pd.DataFrame({"open": c, "high": c + 0.0005, "low": c - 0.0005, "close": c,
                      "volume": 100.0, "half_spread": 1e-5}, index=idx)
    d = forex.to_daily(h)
    assert len(d) == 2
    first = h.iloc[:24]
    assert d["open"].iloc[0] == first["open"].iloc[0]
    assert d["close"].iloc[0] == first["close"].iloc[-1]
    assert d["high"].iloc[0] == first["high"].max()
    assert d["low"].iloc[0] == first["low"].min()
    assert d.index[0] == idx[0]


def test_an_incomplete_trailing_day_is_dropped_not_traded():
    """A six-hour stub is not a session. It must not become a bar with a fill price."""
    idx = pd.date_range("2024-06-02 22:00", periods=30, freq="1h", tz="UTC")
    h = pd.DataFrame({"open": 1.08, "high": 1.081, "low": 1.079, "close": 1.08,
                      "volume": 100.0, "half_spread": 1e-5}, index=idx)
    d = forex.to_daily(h)
    assert len(d) == 1
    assert d["n_bars"].iloc[0] == 24


# ---- the universe ----------------------------------------------------------
def test_the_instrument_list_is_fixed_and_free_of_survivorship_bias():
    assert len(forex.INSTRUMENTS) >= 8
    assert "EURUSD" in forex.INSTRUMENTS and "USDJPY" in forex.INSTRUMENTS
    for s in forex.INSTRUMENTS:
        assert forex.scale_for(s) > 0
