"""Live order gateway. Built on request, shipped locked.

READ THIS BEFORE ENABLING ANYTHING HERE.

As of 16 September 2026 no strategy in this project has passed its own qualification
gates. The best candidate earns 100% of its profit while Bitcoin is above its 200-day
average, which is a bull-market bet rather than an edge, and it loses to simply holding
Bitcoin once German tax is applied. This module therefore refuses to operate until a
strategy has qualified, and that refusal is not a formality: it is the main safety
feature and it is on by default.

What this module does:
  * constructs exchange orders and signs them
  * enforces interlocks that refuse by default
  * records every order it would place, or did, to a local log

What it deliberately does NOT do, and must never:
  * withdraw, transfer or move funds. There is no such method, and a test asserts that
    no function name in this module contains those words.
  * store, print or log a credential. Keys are read from the environment at the moment
    of use and never written anywhere.
  * place a market order. Everything is post-only by default, because the entire cost
    argument for trading at all rests on being passive.

Credentials: set EDGE_<VENUE>_KEY, _SECRET and _PASSPHRASE in the environment. Use
API keys with withdrawals DISABLED and trading scope only. Never put them in this
repository, in a config file, or in a shell history.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ORDER_LOG = Path(__file__).resolve().parent.parent / "state" / "orders.log"

# Venues that can legally serve an EU retail client. Binance withdrew its EU MiCA
# application and stopped new EU spot orders on 1 July 2026; MEXC holds no MiCA
# authorisation. Both are refused for an EU jurisdiction however cheap they are.
MICA_LICENSED = {"okx", "kraken", "bitvavo", "bitstamp", "coinbase", "bitpanda", "gemini", "etoro"}
NOT_EU_ELIGIBLE = {"binance", "mexc"}
ENDPOINTS = {"okx": "https://www.okx.com"}


class Refused(RuntimeError):
    """Raised whenever an interlock declines. Never caught inside this module."""


@dataclass
class Config:
    venue: str = "okx"
    enabled: bool = False          # must be turned on deliberately
    dry_run: bool = True           # must be turned off deliberately
    jurisdiction: str = "DE"
    max_order_usd: float = 250.0
    max_order_frac: float = 0.35   # mirrors referee/risk.py MAX_ASSET_FRAC
    post_only: bool = True


def credentials(venue: str) -> dict:
    """Read keys from the environment at the moment of use. Nothing is cached, stored
    or logged. A missing key is a refusal, never a silent fallback."""
    prefix = f"EDGE_{venue.upper()}_"
    key = os.environ.get(prefix + "KEY")
    secret = os.environ.get(prefix + "SECRET")
    passphrase = os.environ.get(prefix + "PASSPHRASE")
    if not key or not secret:
        raise Refused(
            f"no credential in the environment for {venue}. Set {prefix}KEY and {prefix}SECRET "
            f"with a trading-only, withdrawal-disabled API key. Never store them in this repo.")
    return {"key": key, "secret": secret, "passphrase": passphrase or ""}


def preflight(cfg: Config, champion_qualified: bool, halted: bool, equity: float) -> bool:
    """Every interlock, checked in order of how badly it would go wrong."""
    if not cfg.enabled:
        raise Refused("the live gateway is not enabled. Set Config(enabled=True) deliberately.")
    if not champion_qualified:
        raise Refused(
            "no strategy has passed the qualification gates, so there is nothing fit to trade. "
            "See docs/VERDICT_PHASE1.md. This is the intended state, not a bug.")
    if halted:
        raise Refused("the drawdown brake is on. Trading resumes only under a newly promoted champion.")
    if cfg.jurisdiction.upper() in {"DE", "AT", "FR", "NL", "IT", "ES", "IE", "BE", "FI", "PT", "EU"}:
        if cfg.venue.lower() in NOT_EU_ELIGIBLE:
            raise Refused(
                f"{cfg.venue} holds no MiCA authorisation and cannot legally accept new spot "
                f"orders from an EU resident. Choose one of: {', '.join(sorted(MICA_LICENSED))}.")
        if cfg.venue.lower() not in MICA_LICENSED:
            raise Refused(f"{cfg.venue} is not on the MiCA-licensed list; refusing to route EU orders to it.")
    if equity <= 0:
        raise Refused("equity is zero or negative.")
    return True


def build_order(cfg: Config, symbol: str, side: str, notional: float, price: float, equity: float) -> dict:
    """A post-only limit order, size-capped twice: absolute and as a share of equity."""
    if side not in ("buy", "sell"):
        raise Refused(f"side must be buy or sell, got {side!r}")
    if price <= 0 or notional <= 0:
        raise Refused("price and notional must be positive")
    if notional > cfg.max_order_usd:
        raise Refused(f"order {notional:,.2f} exceeds the per-order cap of {cfg.max_order_usd:,.2f}")
    if notional > cfg.max_order_frac * equity:
        raise Refused(
            f"order {notional:,.2f} is more than {cfg.max_order_frac:.0%} of equity {equity:,.2f}")
    return {"instId": symbol, "tdMode": "cash", "side": side,
            "ordType": "post_only" if cfg.post_only else "limit",
            "px": f"{price:.10g}", "sz": f"{notional / price:.10g}"}


def sign_okx(ts: str, method: str, path: str, body: str, secret: str) -> str:
    """OKX request signature: base64(HMAC-SHA256(timestamp+method+path+body)).
    The secret is used and discarded; it never appears in the return value."""
    msg = f"{ts}{method.upper()}{path}{body}".encode()
    return base64.b64encode(hmac.new(secret.encode(), msg, hashlib.sha256).digest()).decode()


def _http_post(url: str, body: str, headers: dict, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, data=body.encode(), headers=headers, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _record(entry: dict) -> None:
    ORDER_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ORDER_LOG, "a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def submit(cfg: Config, order: dict, champion_qualified: bool, halted: bool, equity: float) -> dict:
    """Run every interlock, record the order, then send it only if dry_run is off.

    The recorded line contains the order and the outcome. It never contains a key, a
    secret, a passphrase or a signature.
    """
    preflight(cfg, champion_qualified, halted, equity)
    stamp = datetime.now(timezone.utc).isoformat()
    if cfg.dry_run:
        _record({"ts": stamp, "venue": cfg.venue, "mode": "dry_run", "order": order})
        return {"status": "dry_run", "order": order}
    creds = credentials(cfg.venue)
    path = "/api/v5/trade/order"
    body = json.dumps(order)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(time.time()*1000)%1000:03d}Z"
    headers = {"Content-Type": "application/json",
               "OK-ACCESS-KEY": creds["key"],
               "OK-ACCESS-SIGN": sign_okx(ts, "POST", path, body, creds["secret"]),
               "OK-ACCESS-TIMESTAMP": ts,
               "OK-ACCESS-PASSPHRASE": creds["passphrase"]}
    try:
        resp = _http_post(ENDPOINTS[cfg.venue] + path, body, headers)
        _record({"ts": stamp, "venue": cfg.venue, "mode": "live", "order": order,
                 "response_code": str(resp.get("code")), "order_id": (resp.get("data") or [{}])[0].get("ordId")})
        return {"status": "sent", "response": resp}
    except Exception as exc:
        _record({"ts": stamp, "venue": cfg.venue, "mode": "live", "order": order, "error": type(exc).__name__})
        raise
