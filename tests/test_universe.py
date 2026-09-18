"""Point-in-time universe: the top N coins by trailing dollar volume among everything
LISTED AT THAT MOMENT, including coins that later died. Membership on date D may use
only data strictly before D."""
import numpy as np
import pandas as pd
import pytest
from referee import universe


def _panel(spec, days=400, start="2021-01-01"):
    """spec: {symbol: (first_day_index, last_day_index, daily_dollar_volume)}"""
    idx = pd.date_range(start, periods=days, freq="1D", tz="UTC")
    out = {}
    for sym, (a, b, qv) in spec.items():
        d = pd.DataFrame(index=idx, columns=["open", "high", "low", "close", "volume", "quote_volume"], dtype=float)
        sl = slice(a, b)
        d.iloc[sl, d.columns.get_loc("close")] = 100.0
        d.iloc[sl, d.columns.get_loc("open")] = 100.0
        d.iloc[sl, d.columns.get_loc("high")] = 101.0
        d.iloc[sl, d.columns.get_loc("low")] = 99.0
        d.iloc[sl, d.columns.get_loc("quote_volume")] = qv
        d.iloc[sl, d.columns.get_loc("volume")] = qv / 100.0
        out[sym] = d.dropna(how="all")
    return out


def test_picks_top_n_by_trailing_dollar_volume():
    bars = _panel({"A": (0, 400, 900), "B": (0, 400, 800), "C": (0, 400, 700), "D": (0, 400, 100)})
    u = universe.build(bars, top_n=3, min_history_days=30, volume_window=30)
    row = u.loc[u.index[-1]]
    assert set(row[row].index) == {"A", "B", "C"}
    assert not row["D"]


def test_membership_is_causal():
    """Corrupting volumes AFTER a date must not change membership ON that date."""
    bars = _panel({"A": (0, 400, 500), "B": (0, 400, 400), "C": (0, 400, 300)})
    base = universe.build(bars, top_n=2, min_history_days=30, volume_window=30)
    cut = base.index[len(base) // 2]
    tampered = {s: d.copy() for s, d in bars.items()}
    tampered["C"].loc[tampered["C"].index > cut, "quote_volume"] = 1e12     # C becomes huge later
    alt = universe.build(tampered, top_n=2, min_history_days=30, volume_window=30)
    pd.testing.assert_frame_equal(base.loc[:cut], alt.loc[:cut])


def test_new_listings_are_excluded_until_they_have_history():
    bars = _panel({"OLD": (0, 400, 100), "NEW": (300, 400, 999_999)})
    u = universe.build(bars, top_n=5, min_history_days=90, volume_window=30)
    at_310 = u.index[u.index <= u.index[0] + pd.Timedelta(days=15)]
    assert not u.loc[at_310, "NEW"].any()
    assert u["NEW"].iloc[-1]                                     # eventually admitted


def test_dead_coins_are_in_the_universe_while_they_traded():
    """The whole point: a coin that dies must be selectable BEFORE it dies."""
    bars = _panel({"SURVIVOR": (0, 400, 100), "DOOMED": (0, 200, 5_000)})
    u = universe.build(bars, top_n=1, min_history_days=30, volume_window=30)
    early = u.index[u.index < bars["DOOMED"].index[-1]]
    assert u.loc[early, "DOOMED"].any(), "survivorship bias: dead coin never selected"
    assert not u["DOOMED"].iloc[-1]                              # gone after its data ends


def test_availability_mask_marks_last_tradable_bar():
    bars = _panel({"A": (0, 400, 100), "DOOMED": (0, 200, 100)})
    av = universe.availability(bars)
    assert av["DOOMED"].iloc[100]
    assert not av["DOOMED"].iloc[-1]
    assert universe.last_bar(bars)["DOOMED"] == bars["DOOMED"].index[-1]


def test_universe_never_exceeds_top_n():
    bars = _panel({f"S{i}": (0, 400, 1000 - i) for i in range(50)})
    u = universe.build(bars, top_n=30, min_history_days=30, volume_window=30)
    assert u.sum(axis=1).max() <= 30


def test_zero_volume_coins_excluded():
    bars = _panel({"A": (0, 400, 100), "DEADWEIGHT": (0, 400, 0)})
    u = universe.build(bars, top_n=10, min_history_days=30, volume_window=30)
    assert not u["DEADWEIGHT"].any()
