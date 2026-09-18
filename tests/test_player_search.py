"""Phase 1 search driver over a point-in-time universe."""
import json, os
import numpy as np
import pandas as pd
import pytest
from player import search, families
from tests.conftest import synth_bars


@pytest.fixture
def small(monkeypatch, tmp_path):
    bars = synth_bars(n=1200, seed=31, freq="1D", syms=tuple(f"C{i}" for i in range(8)))
    monkeypatch.setattr(search, "STATE_DIR", tmp_path)
    monkeypatch.setattr(search, "BARS", ["1d"])
    monkeypatch.setattr(search, "TOP_N", 5)
    monkeypatch.setattr(search, "load_bars", lambda bar, symbols=None, allow_holdout=False, clean=True: bars)
    monkeypatch.setattr(search.families, "FAMILIES",
                        {k: v for k, v in list(families.FAMILIES.items())[:2]})
    return tmp_path


def test_search_ranks_every_candidate_with_a_reason(small):
    out = search.run(now=pd.Timestamp("2024-06-01", tz="UTC"), bars_to_try=["1d"],
                     monthly_deposit=100.0, verbose=False)
    assert out["n_trials"] == search.families.candidate_count(bars=["1d"])
    assert len(out["shortlist"]) == 2
    assert out["shortlist"] == sorted(out["shortlist"], key=lambda r: -r["rank_score"])
    for r in out["shortlist"]:
        assert r["why"]
        for k in ["family", "bar", "sharpe_net", "sharpe_gross", "deflated", "regime", "n_trades", "eligible"]:
            assert k in r
    assert len(list(small.glob("shortlist_*.json"))) == 1


def test_random_walk_data_yields_no_champion(small):
    out = search.run(now=pd.Timestamp("2024-06-01", tz="UTC"), bars_to_try=["1d"], verbose=False)
    assert out["champion"] is None
    assert len(list(small.glob("no_champion_*.json"))) == 1


def test_freeze_champion_writes_an_immutable_file(small):
    row = {"family": "trend_basket", "param": (50, 5), "bar": "1d", "sharpe_net": 1.0, "sharpe_gross": 1.2,
           "oos_net_ret": 0.5, "oos_max_dd": -0.2, "windows_positive": 0.6, "n_trades": 400,
           "deflated": {"psr": 0.7}, "regime": {}, "oos_index": ["a", "2026-08-31"]}
    champ = search.freeze_champion(row, 87, pd.Timestamp("2026-09-16", tz="UTC"), ["BTCUSDT"])
    f = list(small.glob("champion_*.json"))
    assert len(f) == 1
    loaded = json.loads(f[0].read_text())
    assert loaded["family"] == "trend_basket" and loaded["bar"] == "1d" and loaded["top_n"] == 5
    assert loaded["expectation"]["sharpe_net"] == 1.0 and loaded["data_end"] == "2026-08-31"
    assert not os.access(f[0], os.W_OK)
