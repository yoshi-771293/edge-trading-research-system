"""Forex data from Dukascopy's public feed: hourly bid AND ask candles.

Why forex is a cleaner research setting than the crypto universe:

  * No survivorship bias to reconstruct. EURUSD has never been delisted and the
    majors existed throughout the sample, so the universe is simply fixed. On the
    crypto side this took an archive crawl, a leveraged-token filter and a
    ticker-reuse detector.
  * Real spreads instead of modelled ones. Dukascopy publishes bid and ask
    separately, so the ACTUAL historical spread is known at every bar. That removes
    the single largest guess in the whole project: on the crypto side the spread had
    to be estimated from dollar volume and multiplied by a pessimism factor.
  * Friction is one to three orders of magnitude smaller. A EURUSD half-spread is a
    fraction of a basis point. The altcoin model charged five basis points at best and
    a full percent at worst, and friction is what destroyed every crypto result.

Three traps in the file format, each covered by a test:
  1. The month in the URL is ZERO-indexed: June 2024 is .../2024/05/...
  2. Prices are big-endian int32 in instrument points, not floats.
  3. The field order is open, CLOSE, low, high. Reading it as OHLC swaps two fields.
"""
from __future__ import annotations
import concurrent.futures as cf
import lzma
import struct
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FX_DIR = ROOT / "state" / "fx"
BASE = "https://datafeed.dukascopy.com/datafeed"
REC = 24                      # bytes per candle record

# Classic majors and crosses. Fixed list, no selection decision to bias.
INSTRUMENTS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF",
               "USDCAD", "NZDUSD", "EURJPY", "EURGBP", "GBPJPY"]
# Dukascopy stores prices as integers in the instrument's own points.
JPY_SCALE, FX_SCALE = 1e3, 1e5


def scale_for(symbol: str) -> float:
    return JPY_SCALE if symbol.upper().endswith("JPY") else FX_SCALE


def month_url(symbol: str, year: int, month: int, side: str = "BID") -> str:
    """NOTE the zero-indexed month: June is 05."""
    return f"{BASE}/{symbol}/{year}/{month - 1:02d}/{side.upper()}_candles_hour_1.bi5"


def decode(blob: bytes, symbol: str, period_start: pd.Timestamp) -> pd.DataFrame:
    """Decode raw (already decompressed) candle bytes. Offsets are seconds from the
    period start. Zero-volume records are market-closed and are dropped."""
    sc = scale_for(symbol)
    times, rows = [], []
    for i in range(0, len(blob) - REC + 1, REC):
        t, o, c, l, h, vol = struct.unpack(">Iiiiif", blob[i:i + REC])
        if vol <= 0:
            continue
        times.append(period_start + pd.Timedelta(seconds=int(t)))
        rows.append((o / sc, h / sc, l / sc, c / sc, float(vol)))
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"],
                            index=pd.DatetimeIndex([], tz="UTC", name="time"))
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"],
                      index=pd.DatetimeIndex(times, name="time"))
    return df[~df.index.duplicated(keep="last")].sort_index()


class _NotFound(Exception):
    pass


def _raw_get(url: str, timeout: int = 45) -> bytes:
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "research"}), timeout=timeout).read()


def _fetch_raw_with_retry(url: str, attempts: int = 5, timeout: int = 45) -> bytes | None:
    """Exponential backoff. The first parallel download swallowed transient failures
    and silently lost 157 of 261 months of EURUSD; a busy server must be waited for,
    not skipped. A genuine 404 is returned immediately as None."""
    delay = 0.5
    for i in range(attempts):
        try:
            return _raw_get(url, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            pass
        if i < attempts - 1:
            time.sleep(delay)
            delay *= 2
    return None


def _fetch(url: str, timeout: int = 45, attempts: int = 5) -> bytes | None:
    raw = _fetch_raw_with_retry(url, attempts=attempts, timeout=timeout)
    if raw is None:
        return None
    if not raw:
        return b""
    return lzma.LZMADecompressor().decompress(raw)


def fetch_month(symbol: str, year: int, month: int, side: str = "BID") -> pd.DataFrame:
    blob = _fetch(month_url(symbol, year, month, side))
    if not blob:
        return decode(b"", symbol, pd.Timestamp("2000-01-01", tz="UTC"))
    start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
    return decode(blob, symbol, start)


def combine(bid: pd.DataFrame, ask: pd.DataFrame) -> pd.DataFrame:
    """Mid prices plus the MEASURED half-spread, as a fraction of price."""
    idx = bid.index.intersection(ask.index)
    b, a = bid.loc[idx], ask.loc[idx]
    if (a["close"] < b["close"]).any():
        raise ValueError("ask below bid in the feed: crossed quote, refusing to use it")
    mid = (b[["open", "high", "low", "close"]] + a[["open", "high", "low", "close"]]) / 2.0
    mid["volume"] = b["volume"]
    mid["half_spread"] = ((a["close"] - b["close"]) / 2.0) / mid["close"]
    return mid


FX_DAY_OFFSET = "22h"          # the forex day runs from 17:00 New York = 22:00 UTC
MIN_BARS_PER_DAY = 12          # anything shorter is a Sunday-open stub, not a session


def to_daily(hourly: pd.DataFrame) -> pd.DataFrame:
    """Aggregate to forex days, which start at 22:00 UTC (17:00 New York), not at UTC
    midnight. A midnight cut produces two-hour stubs at the Sunday open whose open
    price is a thin, illiquid print, and it was being used as a fill.

    `half_spread` is the day's mean, fair for a stop that fires at an unknown time.
    `open_half_spread` is the FIRST hour's spread, which is what an entry at the open
    actually pays, and it is typically several times wider than the mean.
    Days with fewer than MIN_BARS_PER_DAY hours are dropped: they are not sessions."""
    g = hourly.resample("1D", offset=FX_DAY_OFFSET)
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
        "close": g["close"].last(), "volume": g["volume"].sum(),
        "half_spread": g["half_spread"].mean() if "half_spread" in hourly else np.nan,
        "open_half_spread": g["half_spread"].first() if "half_spread" in hourly else np.nan,
        "n_bars": g["close"].count(),
    }).dropna(subset=["close"])
    return out[out["n_bars"] >= MIN_BARS_PER_DAY]


def cache_path(symbol: str) -> Path:
    FX_DIR.mkdir(parents=True, exist_ok=True)
    return FX_DIR / f"{symbol}_1h.csv.gz"


MIN_BARS_PER_MONTH = 300      # a full trading month has ~500 hourly bars; less is a fragment


def expected_months(first_year: int, last: pd.Timestamp) -> list[tuple[int, int]]:
    return [(y, m) for y in range(first_year, last.year + 1) for m in range(1, 13)
            if (y, m) <= (last.year, last.month)]


def completeness(hourly: pd.DataFrame, first_year: int, last: pd.Timestamp) -> dict:
    """Which expected months are absent or too thin to be a real month."""
    want = expected_months(first_year, last)
    counts = hourly.groupby([hourly.index.year, hourly.index.month]).size() if len(hourly) else {}
    missing = [(y, m) for (y, m) in want if counts.get((y, m), 0) < MIN_BARS_PER_MONTH]
    return {"expected": len(want), "missing": missing,
            "coverage": 1.0 - len(missing) / max(len(want), 1)}


def assert_complete(hourly: pd.DataFrame, first_year: int, last: pd.Timestamp,
                    tolerance: float = 0.0) -> dict:
    """Refuse a series with gaps. `tolerance` is the fraction of months that may be
    missing, for instruments whose earliest history genuinely does not exist."""
    rep = completeness(hourly, first_year, last)
    if 1.0 - rep["coverage"] > tolerance:
        miss = ", ".join(f"{y}-{m:02d}" for y, m in rep["missing"][:12])
        more = "" if len(rep["missing"]) <= 12 else f" and {len(rep['missing']) - 12} more"
        raise ValueError(f"{len(rep['missing'])} of {rep['expected']} months missing ({miss}{more}); "
                         f"refusing to run on a series with gaps")
    return rep


def _one_month(symbol: str, y: int, m: int, attempts: int = 5):
    b_raw = _fetch(month_url(symbol, y, m, "BID"), attempts=attempts)
    a_raw = _fetch(month_url(symbol, y, m, "ASK"), attempts=attempts)
    if not b_raw or not a_raw:
        return None
    start = pd.Timestamp(year=y, month=m, day=1, tz="UTC")
    b, a = decode(b_raw, symbol, start), decode(a_raw, symbol, start)
    if not len(b) or not len(a):
        return None
    try:
        return combine(b, a)
    except ValueError as e:
        print(f"  {symbol} {y}-{m:02d}: dropped, {e}", flush=True)
        return None


def download(symbol: str, first_year: int = 2005, last: pd.Timestamp | None = None,
             workers: int = 4, verbose: bool = True) -> pd.DataFrame:
    """Every month of bid and ask hourly candles, combined into mids plus spreads.
    A gentle parallel pass first, then every missing month is retried serially with
    long backoff, then the result is checked for completeness and the gaps reported."""
    last = last or pd.Timestamp.now(tz="UTC")
    months = expected_months(first_year, last)
    with cf.ThreadPoolExecutor(workers) as ex:
        got = dict(zip(months, ex.map(lambda ym: _one_month(symbol, *ym), months)))
    parts = {ym: p for ym, p in got.items() if p is not None and len(p) >= MIN_BARS_PER_MONTH}
    missing = [ym for ym in months if ym not in parts]
    if missing and verbose:
        print(f"  {symbol}: {len(missing)} months thin or missing after the parallel pass; retrying serially",
              flush=True)
    for y, m in missing:
        time.sleep(1.0)
        p2 = _one_month(symbol, y, m, attempts=7)
        if p2 is not None and len(p2) >= MIN_BARS_PER_MONTH:
            parts[(y, m)] = p2
    if not parts:
        return pd.DataFrame()
    df = pd.concat([parts[k] for k in sorted(parts)])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    rep = completeness(df, first_year, last)
    if verbose and rep["missing"]:
        print(f"  {symbol}: STILL MISSING {len(rep['missing'])} months: "
              + ", ".join(f"{y}-{m:02d}" for y, m in rep["missing"][:15]), flush=True)
    df.to_csv(cache_path(symbol), compression="gzip")
    return df


def load(symbols=None, daily: bool = True) -> dict[str, pd.DataFrame]:
    out = {}
    for s in symbols or INSTRUMENTS:
        p = cache_path(s)
        if not p.exists():
            continue
        df = pd.read_csv(p, index_col="time", parse_dates=["time"])
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        out[s] = to_daily(df) if daily else df
    return out
