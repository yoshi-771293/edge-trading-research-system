import numpy as np
import pandas as pd
from referee import data


def test_resample_is_causal_and_aligned(bars):
    h = bars["BTCUSDT"]
    d4 = data.resample(h, "4h")
    assert len(d4) == len(h) // 4
    first = h.iloc[:4]
    assert d4["open"].iloc[0] == first["open"].iloc[0]
    assert d4["close"].iloc[0] == first["close"].iloc[-1]
    assert d4["high"].iloc[0] == first["high"].max()
    assert d4["quote_volume"].iloc[0] == first["quote_volume"].sum()
    # a 4h bar's timestamp is its OPEN time; it must not contain data after its close
    assert d4.index[0] == h.index[0]


def test_incomplete_trailing_bar_is_dropped(bars):
    h = bars["BTCUSDT"].iloc[:-2]      # 2 hours short of a full 4h bar
    d4 = data.resample(h, "4h")
    assert d4.index[-1] + pd.Timedelta(hours=4) <= h.index[-1] + pd.Timedelta(hours=1)


def test_holdout_gate_truncates_before_cutoff(bars, monkeypatch):
    monkeypatch.setattr(data, "HOLDOUT_START", "2020-03-01")
    gated = data.apply_gate(bars, allow_holdout=False)
    assert all(v.index.max() < pd.Timestamp("2020-03-01", tz="UTC") for v in gated.values())
    open_ = data.apply_gate(bars, allow_holdout=True)
    assert all(v.index.max() >= pd.Timestamp("2020-03-01", tz="UTC") for v in open_.values())
