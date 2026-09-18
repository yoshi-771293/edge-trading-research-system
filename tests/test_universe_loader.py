"""Loading the real cached archive into a universe. Uses whatever is on disk."""
import pandas as pd
import pytest
from player import search


def test_daily_universe_has_dead_coins_and_a_sane_size():
    bars, uni = search.load_universe("1d", top_n=30)
    assert len(bars) > 50
    assert uni.sum(axis=1).max() <= 30
    dead = [s for s in ("LUNAUSDT", "FTTUSDT") if s in uni.columns]
    assert dead, "delisted coins missing from the loaded universe"
    for d in dead:
        assert uni[d].any(), f"{d} never entered the universe: survivorship bias"
        assert not uni[d].iloc[-1], f"{d} is still in the universe today"


def test_universe_reindexes_onto_a_faster_bar_without_peeking():
    bars, uni_d = search.load_universe("1d", top_n=30)
    idx = pd.date_range(uni_d.index[0], uni_d.index[-1], freq="4h", tz="UTC")
    uni_4 = search.project_universe(uni_d, idx)
    assert uni_4.sum(axis=1).max() <= 30
    day = uni_d.index[len(uni_d) // 2]
    same_day = uni_4.loc[(uni_4.index >= day) & (uni_4.index < day + pd.Timedelta(days=1))]
    for _, row in same_day.iterrows():
        assert list(row[row].index) == list(uni_d.loc[day][uni_d.loc[day]].index)


def test_start_date_is_when_the_universe_is_first_full():
    bars, uni = search.load_universe("1d", top_n=30)
    start = search.universe_start(uni, top_n=30)
    assert uni.loc[start:].sum(axis=1).min() >= 30 * 0.8
    assert pd.Timestamp("2018-01-01", tz="UTC") < start < pd.Timestamp("2022-01-01", tz="UTC")
