import json
import numpy as np
import pandas as pd
import pytest
from live import store, dashboard, digest


@pytest.fixture
def db(tmp_path):
    d = store.connect(tmp_path / "t.sqlite")
    strat = {"family": "sma_trend", "param": 50, "bar": "1d", "frozen_at": "2026-09-16", "expectation": {"sharpe_net": 0.9, "oos_max_dd": -0.3}}
    store.set_state(d, "champion", {"strategy": strat, "started": "2026-09-16",
                                    "positions": {"BTCUSDT": 0.01, "ETHUSDT": 0.1},
                                    "cash": 200.0, "equity": 1010.0, "contributed": 1100.0, "profit": -90.0})
    idx = pd.date_range("2026-09-16", periods=40, freq="1D", tz="UTC")
    for i, t in enumerate(idx):
        contributed = 1000.0 + 100 * (i // 30)
        d.execute("INSERT INTO equity VALUES(?,?,?,?,?,?,?,?,?,?)",
                  ("champion", str(t), 1000 + i, 1005 + i, 200, 0.8, -0.01,
                   contributed, 1000 + i - contributed, 1.0 + i / 1000))
    d.execute("INSERT INTO trades(strategy_id,time,symbol,side,usd,units,fill,ref_open,fee,slippage) VALUES(?,?,?,?,?,?,?,?,?,?)",
              ("champion", str(idx[1]), "BTCUSDT", "BUY", 500, 0.005, 100000, 99950, 0.5, 0.25))
    store.journal(d, "champion", idx[5], "I believe the trend is up")
    store.lineage(d, idx[0], "freeze", strat, "initial champion from phase 1")
    d.commit()
    return d, idx


def test_dashboard_contains_required_sections(db, monkeypatch):
    d, idx = db
    btc = pd.Series(np.linspace(100000, 110000, 40), index=idx)
    monkeypatch.setattr(dashboard, "btc_daily_close", lambda: btc)
    html = dashboard.build(d)
    for needle in ["Profit or loss so far", "Just buying Bitcoin", "Right now it holds", "History of strategy changes",
                   "as well as history promised", "rising vs falling", "own notes", "sma_trend",
                   "I believe the trend is up", "initial champion", "Fees and slippage", "You have paid in"]:
        assert needle in html, needle


def test_digest_is_short_and_has_the_numbers(db, monkeypatch):
    d, idx = db
    btc = pd.Series(np.linspace(100000, 110000, 40), index=idx)
    monkeypatch.setattr(digest, "btc_daily_close", lambda: btc)
    text = digest.compose(d, now=idx[-1])
    assert len(text) < 1200
    for needle in ["account", "bitcoin", "strategy", "buys/sells", "promised by history", "note"]:
        assert needle.lower() in text.lower(), needle


def test_dashboard_says_plainly_when_nothing_qualified(tmp_path, monkeypatch):
    """With an empty champion slot the page must not imply it is trading."""
    d = store.connect(tmp_path / "empty.sqlite")
    store.lineage(d, pd.Timestamp("2026-09-16", tz="UTC"), "no_champion", {},
                  "0 of 21 combinations qualified")
    monkeypatch.setattr(dashboard, "btc_daily_close",
                        lambda: pd.Series([100.0, 101.0],
                                          index=pd.date_range("2026-09-15", periods=2, tz="UTC")))
    html = dashboard.build(d)
    assert "Not trading" in html
    assert "Trading normally" not in html
    assert "nothing has qualified" in html.lower() or "no strategy" in html.lower()
    assert "waiting for a buy signal" not in html
    for banned in ["192 rule variations", "Bitcoin and Ethereum on its own"]:
        assert banned not in html
