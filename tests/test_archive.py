"""Bulk historical loader for Binance's public data archive (includes DELISTED pairs).
Parsing must be exact: the archive changed timestamp precision from milliseconds to
microseconds in 2025, and some files carry a header row."""
import io, zipfile
import pandas as pd
import pytest
from referee import archive

MS_ROW = "1609459200000,29331.69,29600.0,28800.0,29500.0,100.5,1609545599999,2950000.0,1234,50.0,1475000.0,0"
US_ROW = "1767225600000000,95000.0,96000.0,94000.0,95500.0,10.5,1767311999999999,1000000.0,99,5.0,500000.0,0"


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", text)
    return buf.getvalue()


def test_parses_millisecond_timestamps():
    df = archive.parse_zip(_zip(MS_ROW))
    assert df.index[0] == pd.Timestamp("2021-01-01", tz="UTC")
    assert df["close"].iloc[0] == 29500.0
    assert df["quote_volume"].iloc[0] == 2950000.0


def test_parses_microsecond_timestamps_from_2025_files():
    df = archive.parse_zip(_zip(US_ROW))
    assert df.index[0] == pd.Timestamp("2026-01-01", tz="UTC")
    assert df["close"].iloc[0] == 95500.0


def test_skips_header_row():
    df = archive.parse_zip(_zip("open_time,open,high,low,close,volume,close_time,quote_volume,count,tb,tq,ig\n" + MS_ROW))
    assert len(df) == 1 and df["close"].iloc[0] == 29500.0


def test_mixed_precision_in_one_symbol_is_normalised():
    df = archive.parse_zip(_zip(MS_ROW + "\n" + US_ROW))
    assert list(df.index) == [pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")]


def test_rejects_corrupt_rows_rather_than_guessing():
    df = archive.parse_zip(_zip(MS_ROW + "\nnot,a,valid,row\n"))
    assert len(df) == 1


def test_months_range_is_inclusive_and_ordered():
    m = archive.months("2020-11", "2021-02")
    assert m == ["2020-11", "2020-12", "2021-01", "2021-02"]


TRUNCATED_PAGE = """<?xml version="1.0"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
<IsTruncated>true</IsTruncated>
<CommonPrefixes><Prefix>data/spot/monthly/klines/BTCUSDT/</Prefix></CommonPrefixes>
<CommonPrefixes><Prefix>data/spot/monthly/klines/LUNAUSDT/</Prefix></CommonPrefixes>
</ListBucketResult>"""

LAST_PAGE = TRUNCATED_PAGE.replace("<IsTruncated>true</IsTruncated>", "<IsTruncated>false</IsTruncated>")


def test_page_parse_reads_symbols_and_truncation_flag():
    syms, more = archive.parse_listing(TRUNCATED_PAGE.encode())
    assert syms == ["BTCUSDT", "LUNAUSDT"]
    assert more is True


def test_page_parse_detects_last_page():
    """IsTruncated has no child elements, so a truthiness test on it silently breaks."""
    syms, more = archive.parse_listing(LAST_PAGE.encode())
    assert syms == ["BTCUSDT", "LUNAUSDT"]
    assert more is False
