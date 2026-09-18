"""Binance 1h candles (public, keyless) cached locally; higher bars resampled
causally. HOLDOUT GATE lives here."""
from __future__ import annotations
import time
from pathlib import Path
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
BARS_DIR = ROOT / "state" / "bars"
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
DATA_START = "2017-08-17"
HOLDOUT_START = "2026-09-16"          # Phase 1 search sees strictly before this; live runs after
BINANCE = "https://api.binance.com/api/v3/klines"
BAR_HOURS = {"1h": 1, "4h": 4, "1d": 24, "1w": 168}
PERIODS_PER_YEAR = {"1h": 24 * 365, "4h": 6 * 365, "1d": 365, "1w": 52}
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "tb", "tq", "ig"]


def fetch_1h(symbol: str, start: str) -> pd.DataFrame:
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    rows = []
    while True:
        r = requests.get(BINANCE, params={"symbol": symbol, "interval": "1h", "startTime": start_ms, "limit": 1000}, timeout=30)
        r.raise_for_status(); batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        start_ms = batch[-1][0] + 3_600_000
        time.sleep(0.15)
    df = pd.DataFrame(rows, columns=COLS)
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[c] = df[c].astype(float)
    df = df[df["close_time"] < int(time.time() * 1000)]          # drop the forming bar
    return df.set_index("time")[["open", "high", "low", "close", "volume", "quote_volume"]].sort_index()


def update_cache(symbol: str) -> pd.DataFrame:
    BARS_DIR.mkdir(parents=True, exist_ok=True)
    path = BARS_DIR / f"{symbol}_1h.csv.gz"
    if path.exists():
        old = pd.read_csv(path, index_col="time", parse_dates=["time"])
        old.index = pd.DatetimeIndex(old.index, tz="UTC") if old.index.tz is None else old.index
        new = fetch_1h(symbol, (old.index[-1] - pd.Timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S"))
        df = pd.concat([old, new]); df = df[~df.index.duplicated(keep="last")].sort_index()
    else:
        df = fetch_1h(symbol, DATA_START)
    df.to_csv(path, compression="gzip")
    return df


def load_1h(symbols=None, refresh=False) -> dict[str, pd.DataFrame]:
    out = {}
    for s in symbols or SYMBOLS:
        path = BARS_DIR / f"{s}_1h.csv.gz"
        if refresh or not path.exists():
            out[s] = update_cache(s)
        else:
            df = pd.read_csv(path, index_col="time", parse_dates=["time"])
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            out[s] = df
    return out


def resample(h: pd.DataFrame, bar: str) -> pd.DataFrame:
    """Aggregate 1h bars into `bar`, labelled by OPEN time, dropping any trailing
    incomplete bar. Weekly bars start Monday 00:00 UTC."""
    if bar == "1h":
        return h
    rule = {"4h": "4h", "1d": "1D", "1w": "W-MON"}[bar]
    kw = {"label": "left", "closed": "left"}
    g = h.resample(rule, **kw)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum(), "quote_volume": g["quote_volume"].sum(),
                        "n": g["close"].count()})
    full = BAR_HOURS[bar]
    out = out[out["n"] == full].drop(columns="n")
    return out


def align(bars: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    idx = None
    for d in bars.values():
        idx = d.index if idx is None else idx.intersection(d.index)
    return {s: d.loc[idx] for s, d in bars.items()}


def apply_gate(bars: dict[str, pd.DataFrame], allow_holdout: bool) -> dict[str, pd.DataFrame]:
    if allow_holdout:
        return bars
    cutoff = pd.Timestamp(HOLDOUT_START, tz="UTC")
    return {s: d[d.index < cutoff] for s, d in bars.items()}


def load(bar: str, allow_holdout: bool = False, refresh: bool = False) -> dict[str, pd.DataFrame]:
    h = load_1h(refresh=refresh)
    return apply_gate(align({s: resample(d, bar) for s, d in h.items()}), allow_holdout)
