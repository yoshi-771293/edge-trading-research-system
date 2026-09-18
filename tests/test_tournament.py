import json
import numpy as np
import pandas as pd
import pytest
from live import store
from player import tournament


def _seed(db, sid, sharpe_daily, n_days=70, n_trades=40, start="2026-10-01"):
    idx = pd.date_range(start, periods=n_days, freq="1D", tz="UTC")
    r = np.random.default_rng(1).normal(sharpe_daily * 0.02 / np.sqrt(365), 0.02, n_days)
    eq = 1000 * np.cumprod(1 + r)
    for t, e in zip(idx, eq):
        db.execute("INSERT INTO equity VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (sid, str(t), float(e), float(e), 0.0, 0.5, 0.0, 1000.0, float(e) - 1000.0, float(e) / 1000.0))
    for k in range(n_trades):
        db.execute("INSERT INTO trades(strategy_id,time,symbol,side,usd,units,fill,ref_open,fee,slippage) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (sid, str(idx[k % n_days]), "BTCUSDT", "BUY", 100, 0.001, 1, 1, 0.1, 0.1))
    db.commit()


@pytest.fixture
def db(tmp_path):
    d = store.connect(tmp_path / "t.sqlite")
    store.set_state(d, "champion", {"strategy": {"family": "sma_trend", "param": 50, "bar": "1d", "file": "c1"}, "started": "2026-09-16"})
    return d


def test_no_promotion_before_eight_weeks(db):
    store.set_state(db, "challenger", {"strategy": {"family": "donchian", "param": 20, "bar": "4h", "file": "c2"}, "started": "2026-10-01"})
    _seed(db, "champion", 0.0, n_days=30); _seed(db, "challenger", 3.0, n_days=30)
    d = tournament.decide(db, now=pd.Timestamp("2026-10-31", tz="UTC"))
    assert d["action"] == "hold" and "8 weeks" in d["reason"]


def test_promotion_when_margin_cleared(db):
    store.set_state(db, "challenger", {"strategy": {"family": "donchian", "param": 20, "bar": "4h", "file": "c2"}, "started": "2026-10-01"})
    _seed(db, "champion", 0.0); _seed(db, "challenger", 3.0)
    d = tournament.decide(db, now=pd.Timestamp("2026-12-15", tz="UTC"))
    assert d["action"] == "promote"
    assert store.get_state(db, "champion")["strategy"]["family"] == "donchian"
    assert store.get_state(db, "challenger") is None
    rows = db.execute("SELECT event, reason FROM lineage").fetchall()
    assert any(e == "promote" for e, _ in rows) and any("Sharpe" in r for _, r in rows)


def test_challenger_demoted_when_it_fails(db):
    store.set_state(db, "challenger", {"strategy": {"family": "donchian", "param": 20, "bar": "4h", "file": "c2"}, "started": "2026-10-01"})
    _seed(db, "champion", 1.0); _seed(db, "challenger", 1.1)
    d = tournament.decide(db, now=pd.Timestamp("2026-12-15", tz="UTC"))
    assert d["action"] == "demote_challenger"
    assert store.get_state(db, "challenger") is None
    assert store.get_state(db, "champion")["strategy"]["family"] == "sma_trend"


def test_too_few_trades_blocks_promotion(db):
    store.set_state(db, "challenger", {"strategy": {"family": "donchian", "param": 20, "bar": "4h", "file": "c2"}, "started": "2026-10-01"})
    _seed(db, "champion", 0.0, n_trades=5); _seed(db, "challenger", 3.0, n_trades=5)
    d = tournament.decide(db, now=pd.Timestamp("2026-12-15", tz="UTC"))
    assert d["action"] == "hold" and "trades" in d["reason"]


def test_with_no_champion_an_eligible_candidate_is_seated_directly(tmp_path, monkeypatch):
    """After a search that finds nothing, the champion slot is empty. The next weekly
    search that DOES find something must seat it as champion, not park it as a
    challenger with no incumbent to beat."""
    db = store.connect(tmp_path / "t.sqlite")
    store.set_state(db, "champion", None)
    frozen = {"family": "trend_basket", "param": [50, 5], "bar": "1w", "file": "c9"}
    monkeypatch.setattr(tournament, "_search_top", lambda now, verbose=False: (frozen, 87))
    out = tournament.propose(db, now=pd.Timestamp("2026-10-04", tz="UTC"))
    assert out["action"] == "seated"
    assert store.get_state(db, "champion")["strategy"]["family"] == "trend_basket"
    assert store.get_state(db, "challenger") is None
    ev = [e for e, in db.execute("SELECT event FROM lineage")]
    assert "seated" in ev


def test_with_no_champion_and_nothing_eligible_it_keeps_waiting(tmp_path, monkeypatch):
    db = store.connect(tmp_path / "t.sqlite")
    store.set_state(db, "champion", None)
    monkeypatch.setattr(tournament, "_search_top", lambda now, verbose=False: (None, 87))
    out = tournament.propose(db, now=pd.Timestamp("2026-10-04", tz="UTC"))
    assert out["action"] == "none"
    assert store.get_state(db, "champion") is None
    assert "no_champion" in [e for e, in db.execute("SELECT event FROM lineage")]
