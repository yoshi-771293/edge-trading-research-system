"""A pre-registered, deliberately small search space.

Narrowing the search is statistically legitimate ONLY if the narrowing is committed to
before the results are seen. This narrowing is not: it was chosen after an 87-variant
run. So it may never be scored against history. It is frozen with a date, and the
scorer refuses any data from before that date.
"""
import json
import pandas as pd
import pytest
from player import prereg


def test_the_set_is_small_and_chosen_by_rule_not_by_performance():
    spec = prereg.build()
    assert len(spec["variants"]) <= 6, "the point is a small space"
    assert spec["n_trials"] == len(spec["variants"])
    for v in spec["variants"]:
        grid = prereg.families.FAMILIES[v["family"]]["grid"]
        assert v["param"] == list(grid[len(grid) // 2]), (
            f"{v['family']} must take the grid's MIDDLE value, not its best performer")
    assert spec["selection_rule"]
    assert "4h" not in {v["bar"] for v in spec["variants"]}, "fastest horizon dropped on cost grounds"


def test_it_is_frozen_with_a_date_and_an_explicit_forward_only_flag():
    spec = prereg.build(now=pd.Timestamp("2026-09-16", tz="UTC"))
    assert spec["frozen_at"].startswith("2026-09-16")
    assert spec["score_from"] > spec["frozen_at"]
    assert spec["history_is_invalid_for_this_set"] is True


def test_freeze_writes_a_read_only_file(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(prereg, "STATE_DIR", tmp_path)
    path = prereg.freeze(now=pd.Timestamp("2026-09-16", tz="UTC"))
    assert not os.access(path, os.W_OK)
    loaded = json.loads(open(path).read())
    assert loaded["n_trials"] == len(loaded["variants"])


def test_scoring_refuses_data_from_before_the_freeze():
    spec = prereg.build(now=pd.Timestamp("2026-09-16", tz="UTC"))
    idx = pd.date_range("2020-01-01", periods=100, freq="1D", tz="UTC")
    with pytest.raises(ValueError, match="before the pre-registration"):
        prereg.assert_forward_only(spec, idx)
    fwd = pd.date_range("2026-10-01", periods=100, freq="1D", tz="UTC")
    prereg.assert_forward_only(spec, fwd)          # must not raise


def test_the_bar_is_stricter_than_the_open_ended_search():
    """A 0.50 confidence threshold passes 42% of pure-noise winners: it is a coin flip,
    not a standard of proof. A pre-registered set gets the conventional bar instead."""
    assert prereg.MIN_PSR >= 0.90
    from player import search
    assert prereg.MIN_PSR > search.MIN_PSR


def test_the_bracket_set_is_also_forward_only_and_small():
    spec = prereg.build_brackets(now=pd.Timestamp("2026-09-17", tz="UTC"))
    assert len(spec["variants"]) <= 4
    assert spec["history_is_invalid_for_this_set"] is True
    assert spec["min_psr"] >= 0.90
    assert spec["min_trades"] >= 100, "the historical test failed on 73 trades; keep the gate"
    assert all(v["venue"] == "okx" for v in spec["variants"]), "only a venue an EU client may use"
    import pytest as _p
    idx = pd.date_range("2021-01-01", periods=50, freq="1D", tz="UTC")
    with _p.raises(ValueError, match="before the pre-registration"):
        prereg.assert_forward_only(spec, idx)
