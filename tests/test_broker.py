"""Live order gateway. Built as requested, shipped locked.

The interlocks are the point of this file. Every one of them must refuse by default,
because the research verdict is that no strategy has qualified, and a gateway that can
be switched on for a failing strategy is worse than no gateway at all.
"""
import os
import pytest
from live import broker


# ---- refusal by default ---------------------------------------------------
def test_disabled_unless_explicitly_enabled():
    cfg = broker.Config(enabled=False, dry_run=False, venue="okx")
    with pytest.raises(broker.Refused, match="not enabled"):
        broker.preflight(cfg, champion_qualified=True, halted=False, equity=1000.0)


def test_refuses_while_no_strategy_has_qualified():
    cfg = broker.Config(enabled=True, dry_run=False, venue="okx")
    with pytest.raises(broker.Refused, match="no strategy has passed"):
        broker.preflight(cfg, champion_qualified=False, halted=False, equity=1000.0)


def test_refuses_while_the_drawdown_brake_is_on():
    cfg = broker.Config(enabled=True, dry_run=False, venue="okx")
    with pytest.raises(broker.Refused, match="brake"):
        broker.preflight(cfg, champion_qualified=True, halted=True, equity=1000.0)


def test_refuses_a_venue_that_cannot_legally_serve_the_user():
    cfg = broker.Config(enabled=True, dry_run=False, venue="binance", jurisdiction="DE")
    with pytest.raises(broker.Refused, match="MiCA"):
        broker.preflight(cfg, champion_qualified=True, halted=False, equity=1000.0)


def test_passes_only_when_everything_is_true():
    cfg = broker.Config(enabled=True, dry_run=False, venue="okx", jurisdiction="DE")
    assert broker.preflight(cfg, champion_qualified=True, halted=False, equity=1000.0) is True


# ---- order construction and size caps -------------------------------------
def test_order_above_the_notional_cap_is_refused():
    cfg = broker.Config(enabled=True, venue="okx", max_order_usd=200.0)
    with pytest.raises(broker.Refused, match="exceeds"):
        broker.build_order(cfg, "BTC-EUR", "buy", 250.0, price=100.0, equity=1000.0)


def test_order_above_the_equity_fraction_is_refused():
    cfg = broker.Config(enabled=True, venue="okx", max_order_usd=10_000.0, max_order_frac=0.35)
    with pytest.raises(broker.Refused, match="equity"):
        broker.build_order(cfg, "BTC-EUR", "buy", 400.0, price=100.0, equity=1000.0)


def test_a_valid_order_is_a_post_only_limit_by_default():
    cfg = broker.Config(enabled=True, venue="okx")
    o = broker.build_order(cfg, "BTC-EUR", "buy", 100.0, price=50_000.0, equity=1000.0)
    assert o["ordType"] == "post_only", "passive by default: the whole cost case rests on it"
    assert o["side"] == "buy" and o["instId"] == "BTC-EUR"
    assert float(o["px"]) == 50_000.0 and float(o["sz"]) > 0


def test_there_is_no_withdrawal_capability_anywhere():
    surface = dir(broker)
    for forbidden in ("withdraw", "transfer", "send_funds", "withdrawal"):
        assert not any(forbidden in name.lower() for name in surface), forbidden


# ---- credentials never live in the repository -----------------------------
def test_credentials_come_only_from_the_environment(monkeypatch):
    monkeypatch.delenv("EDGE_OKX_KEY", raising=False)
    with pytest.raises(broker.Refused, match="credential"):
        broker.credentials("okx")
    monkeypatch.setenv("EDGE_OKX_KEY", "k"); monkeypatch.setenv("EDGE_OKX_SECRET", "s")
    monkeypatch.setenv("EDGE_OKX_PASSPHRASE", "p")
    c = broker.credentials("okx")
    assert c["key"] == "k"


def test_no_credential_is_ever_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_OKX_KEY", "SECRETKEY"); monkeypatch.setenv("EDGE_OKX_SECRET", "SECRETSEC")
    monkeypatch.setenv("EDGE_OKX_PASSPHRASE", "SECRETPASS")
    log = tmp_path / "orders.log"
    monkeypatch.setattr(broker, "ORDER_LOG", log)
    cfg = broker.Config(enabled=True, dry_run=True, venue="okx")
    o = broker.build_order(cfg, "BTC-EUR", "buy", 100.0, price=50_000.0, equity=1000.0)
    broker.submit(cfg, o, champion_qualified=True, halted=False, equity=1000.0)
    text = log.read_text()
    for secret in ("SECRETKEY", "SECRETSEC", "SECRETPASS"):
        assert secret not in text


# ---- dry run is the default and does not reach the network ----------------
def test_dry_run_records_the_order_and_sends_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(broker, "ORDER_LOG", tmp_path / "orders.log")
    sent = []
    monkeypatch.setattr(broker, "_http_post", lambda *a, **k: sent.append(a))
    cfg = broker.Config(enabled=True, dry_run=True, venue="okx")
    o = broker.build_order(cfg, "BTC-EUR", "buy", 100.0, price=50_000.0, equity=1000.0)
    res = broker.submit(cfg, o, champion_qualified=True, halted=False, equity=1000.0)
    assert res["status"] == "dry_run"
    assert sent == [], "dry run must not touch the network"
    assert (tmp_path / "orders.log").exists()


def test_dry_run_is_the_default():
    assert broker.Config(venue="okx").dry_run is True
    assert broker.Config(venue="okx").enabled is False


def test_signing_is_deterministic_and_excludes_the_secret_from_output():
    sig = broker.sign_okx("2026-09-16T12:00:00.000Z", "POST", "/api/v5/trade/order",
                          '{"instId":"BTC-EUR"}', secret="topsecret")
    again = broker.sign_okx("2026-09-16T12:00:00.000Z", "POST", "/api/v5/trade/order",
                            '{"instId":"BTC-EUR"}', secret="topsecret")
    assert sig == again and len(sig) > 20
    assert "topsecret" not in sig
