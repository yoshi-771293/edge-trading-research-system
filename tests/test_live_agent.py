"""Live cycle for a many-coin, point-in-time universe.

Positions are keyed by SYMBOL, not by slot, because the universe churns. The agent
may only buy coins in the current universe, must always be able to sell what it
holds, fills only at the open of the bar AFTER the decision bar, and takes the same
$100 monthly deposit the backtest modelled.
"""
import json
import numpy as np
import pandas as pd
import pytest
from live import agent, store
from tests.conftest import synth_bars

SYMS = [f"C{i}USDT" for i in range(8)]


@pytest.fixture
def world(tmp_path, monkeypatch):
    bars = synth_bars(n=1500, seed=5, freq="1D", syms=tuple(SYMS))
    for i, s in enumerate(SYMS):
        bars[s]["quote_volume"] = 5e8 - i * 1e7          # C0 most liquid, C7 least
    clock = {"i": 1200}

    def fake_fetch(symbols, bar, limit=None):
        i = clock["i"]
        return {s: bars[s].iloc[: i + 2] for s in symbols if s in bars}   # closed bars + forming one

    monkeypatch.setattr(agent, "watchlist", lambda top=60: list(SYMS))
    monkeypatch.setattr(agent, "fetch_bars", fake_fetch)
    monkeypatch.setattr(agent, "notify", lambda *a, **k: None)
    monkeypatch.setattr(agent, "guard_check", lambda: None)
    monkeypatch.setattr(agent, "TOP_N", 4)
    monkeypatch.setattr(agent, "MIN_HISTORY_DAYS", 30)
    monkeypatch.setattr(agent, "ORDER_STYLE", "taker")     # maker semantics get their own test

    db = store.connect(tmp_path / "t.sqlite")
    champ = {"frozen_at": "2026-09-16", "family": "trend_basket", "param": (50, 3),
             "bar": "1d", "expectation": {"sharpe_net": 0.9}, "file": "champion_test.json"}
    store.set_state(db, "champion", {"strategy": champ, "started": "2026-09-16"})
    return bars, db, clock


def test_first_cycle_decides_but_cannot_fill(world):
    bars, db, clock = world
    out = agent.cycle(db, "champion")
    assert out["status"] == "ok" and out["fills"] == 0
    st = store.get_state(db, "champion")
    assert st["pending"] is not None
    assert st["pending"]["decided_bar"] == str(bars[SYMS[0]].index[1200])
    assert st["contributed"] == 1000.0


def test_maker_orders_fill_better_than_the_open_or_not_at_all(world, monkeypatch):
    """With passive limits, a buy either fills BELOW the bar's open or does not fill."""
    bars, db, clock = world
    monkeypatch.setattr(agent, "ORDER_STYLE", "maker")
    agent.cycle(db, "champion")
    clock["i"] = 1201
    agent.cycle(db, "champion")
    rows = db.execute("SELECT symbol, ref_open, fill, side, style FROM trades").fetchall()
    for sym, ref_open, fill, side, style in rows:
        if side == "BUY" and style == "maker":
            assert fill < ref_open
        if side == "SELL" and style == "maker":
            assert fill > ref_open


def test_second_cycle_fills_at_the_next_bar_open(world):
    bars, db, clock = world
    agent.cycle(db, "champion")
    pend = store.get_state(db, "champion")["pending"]["usd"]
    clock["i"] = 1201
    agent.cycle(db, "champion")
    rows = db.execute("SELECT symbol, time, ref_open, fill, side FROM trades").fetchall()
    bought = [r for r in rows if r[4] == "BUY"]
    assert bought, f"nothing filled from pending {pend}"
    for sym, t, ref_open, fill, _ in bought:
        assert t == str(bars[sym].index[1201])
        assert ref_open == bars[sym]["open"].iloc[1201]
        assert fill > ref_open                            # buys fill worse than the open


def test_only_universe_members_are_bought(world):
    bars, db, clock = world
    agent.cycle(db, "champion")
    pend = store.get_state(db, "champion")["pending"]["usd"]
    assert len([s for s, v in pend.items() if v > 0]) <= 3
    assert all(s in SYMS[:4] for s, v in pend.items() if v > 0), pend


def test_no_new_bar_means_no_action(world):
    bars, db, clock = world
    agent.cycle(db, "champion")
    assert agent.cycle(db, "champion")["status"] == "no_new_bar"


def test_monthly_deposit_is_recorded_as_contribution_not_profit(world):
    bars, db, clock = world
    agent.cycle(db, "champion")
    start_month = bars[SYMS[0]].index[1200]
    # advance to the first bar of the next calendar month
    nxt = [i for i in range(1201, 1260) if bars[SYMS[0]].index[i].month != start_month.month][0]
    clock["i"] = nxt
    out = agent.cycle(db, "champion")
    st = store.get_state(db, "champion")
    assert st["contributed"] == pytest.approx(1100.0)
    row = db.execute("SELECT equity, contributed, profit FROM equity ORDER BY time DESC LIMIT 1").fetchone()
    assert row[1] == pytest.approx(1100.0)
    assert row[2] == pytest.approx(row[0] - row[1])


def test_held_coin_can_be_sold_after_leaving_the_universe(world):
    bars, db, clock = world
    agent.cycle(db, "champion"); clock["i"] = 1201; agent.cycle(db, "champion")
    held = {s: u for s, u in store.get_state(db, "champion")["positions"].items() if u > 0}
    assert held, "nothing was bought"
    victim = list(held)[0]
    # make the victim illiquid so it drops out of the top 4
    for s in SYMS:
        bars[s]["quote_volume"] = 1e9 if s != victim else 1.0
    for step in range(1202, 1210):
        clock["i"] = step
        agent.cycle(db, "champion")
    sells = db.execute("SELECT count(*) FROM trades WHERE symbol=? AND side='SELL'", (victim,)).fetchone()[0]
    assert sells >= 1, f"{victim} was stranded after leaving the universe"


def test_error_is_logged_and_the_cycle_is_skipped(world, monkeypatch):
    bars, db, clock = world
    monkeypatch.setattr(agent, "fetch_bars", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("binance down")))
    out = agent.safe_cycle(db, "champion")
    assert out["status"] == "error"
    assert db.execute("SELECT count(*) FROM errors").fetchone()[0] == 1


def test_kill_switch_trips_on_deposit_neutral_drawdown(world, monkeypatch):
    bars, db, clock = world
    alerts = []
    monkeypatch.setattr(agent, "notify", lambda title, msg, **k: alerts.append(title))
    agent.cycle(db, "champion")
    st = store.get_state(db, "champion"); st["peak_twr"] = 2.0; store.set_state(db, "champion", st)
    clock["i"] = 1201
    out = agent.cycle(db, "champion")
    assert out["status"] == "killed"
    assert store.get_state(db, "champion")["halted"] is True
    assert any("KILL" in a for a in alerts)
