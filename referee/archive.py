"""Bulk historical OHLCV from Binance's PUBLIC DATA ARCHIVE (data.binance.vision).

Unlike the REST endpoint, the archive retains DELISTED pairs (LUNAUSDT, FTTUSDT,
BCCUSDT ...), which is what makes a point-in-time, survivorship-free universe possible.

Two parsing hazards this module handles explicitly:
  * The archive switched kline timestamps from MILLISECONDS to MICROSECONDS during
    2025. One symbol's history can contain both. Magnitude decides, per row.
  * Some files carry a CSV header row; older ones do not.
Rows that do not parse are dropped, never guessed at.
"""
from __future__ import annotations
import concurrent.futures as cf
import io
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BARS_DIR = ROOT / "state" / "bars"
BASE = "https://data.binance.vision/data/spot/monthly/klines"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
COLS = ["open", "high", "low", "close", "volume", "quote_volume"]
US_THRESHOLD = 1e14          # above this a timestamp is microseconds, below it milliseconds


def months(first: str, last: str) -> list[str]:
    return [f"{d.year}-{d.month:02d}" for d in pd.period_range(first, last, freq="M").to_timestamp()]


def parse_zip(blob: bytes) -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(blob))
    raw = z.read(z.namelist()[0]).decode("utf-8", "replace")
    times, rows = [], []
    for line in raw.splitlines():
        parts = line.split(",")
        if len(parts) < 8:
            continue
        try:
            t = float(parts[0])
            vals = [float(parts[i]) for i in (1, 2, 3, 4, 5, 7)]
        except ValueError:
            continue                                   # header or corrupt row
        times.append(int(t / 1000) if t > US_THRESHOLD else int(t))
        rows.append(vals)
    if not rows:
        return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], tz="UTC", name="time"))
    idx = pd.to_datetime(times, unit="ms", utc=True)
    df = pd.DataFrame(rows, columns=COLS, index=idx)
    df.index.name = "time"
    return df[~df.index.duplicated(keep="last")].sort_index()


def _get(url: str, timeout: int = 45) -> bytes | None:
    for attempt in range(3):
        try:
            return urllib.request.urlopen(url, timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None                            # month simply does not exist
            time.sleep(0.5 * (attempt + 1))
        except Exception:
            time.sleep(0.5 * (attempt + 1))
    return None


def parse_listing(blob: bytes) -> tuple[list[str], bool]:
    """One page of the S3 bucket listing -> (symbols, more_pages).
    NOTE: an ElementTree element with no children is FALSY, so `elem or default`
    silently misreads <IsTruncated>. Compare against None explicitly."""
    x = ET.fromstring(blob)
    syms = [p.find("s:Prefix", NS).text.rstrip("/").split("/")[-1] for p in x.findall("s:CommonPrefixes", NS)]
    node = x.find("s:IsTruncated", NS)
    more = node is not None and (node.text or "").strip().lower() == "true"
    return syms, more


def all_symbols(quote: str = "USDT") -> list[str]:
    """Every symbol that has EVER been archived, including delisted ones."""
    out, marker = [], None
    while True:
        url = f"{S3}?delimiter=/&prefix=data/spot/monthly/klines/&max-keys=1000"
        if marker:
            url += f"&marker={urllib.parse.quote(marker)}"
        syms, more = parse_listing(_get(url, timeout=90))
        if not syms:
            break
        out += syms
        if not more:
            break
        marker = f"data/spot/monthly/klines/{syms[-1]}/"
    return sorted(s for s in out if s.endswith(quote))


def fetch_symbol(symbol: str, interval: str, first: str = "2017-07", last: str | None = None,
                 workers: int = 12) -> pd.DataFrame:
    last = last or pd.Timestamp.now(tz="UTC").strftime("%Y-%m")
    ms = months(first, last)
    urls = [f"{BASE}/{symbol}/{interval}/{symbol}-{interval}-{m}.zip" for m in ms]
    with cf.ThreadPoolExecutor(workers) as ex:
        blobs = list(ex.map(_get, urls))
    frames = [parse_zip(b) for b in blobs if b]
    if not frames:
        return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], tz="UTC", name="time"))
    df = pd.concat(frames)
    return df[~df.index.duplicated(keep="last")].sort_index()


def cache_path(symbol: str, interval: str) -> Path:
    BARS_DIR.mkdir(parents=True, exist_ok=True)
    return BARS_DIR / f"{symbol}_{interval}.csv.gz"


def ensure(symbol: str, interval: str, refresh: bool = False) -> pd.DataFrame:
    p = cache_path(symbol, interval)
    if p.exists() and not refresh:
        df = pd.read_csv(p, index_col="time", parse_dates=["time"])
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df
    df = fetch_symbol(symbol, interval)
    if len(df):
        df.to_csv(p, compression="gzip")
    return df


def bulk(symbols: list[str], interval: str, workers: int = 8, log_every: int = 25) -> dict[str, int]:
    """Download and cache many symbols. Returns {symbol: n_bars}."""
    done = {}
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(ensure, s, interval): s for s in symbols}
        for i, f in enumerate(cf.as_completed(futs), 1):
            s = futs[f]
            try:
                done[s] = len(f.result())
            except Exception as e:
                done[s] = 0
            if i % log_every == 0:
                print(f"  [{interval}] {i}/{len(symbols)} symbols cached", flush=True)
    return done
