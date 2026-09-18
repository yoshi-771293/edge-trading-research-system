"""A data layer that silently loses months is worse than no data layer.

The first parallel download of EURUSD came back with 157 of 261 months missing,
including whole years, while a serial probe fetched those same months fine. Transient
failures under load were being swallowed. The downloader must now retry with backoff,
report exactly which months are missing, and refuse to hand over a series with gaps.
"""
import pandas as pd
import pytest
from referee import forex


def test_expected_months_are_enumerated_inclusively():
    ms = forex.expected_months(2024, pd.Timestamp("2024-03-15", tz="UTC"))
    assert ms == [(2024, 1), (2024, 2), (2024, 3)]


def test_completeness_report_names_every_missing_month():
    idx = pd.date_range("2024-01-01", "2024-03-31", freq="1h", tz="UTC")
    h = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
                      "half_spread": 1e-5}, index=idx)
    h = h[h.index.month != 2]                       # February is missing
    rep = forex.completeness(h, first_year=2024, last=pd.Timestamp("2024-03-31", tz="UTC"))
    assert rep["missing"] == [(2024, 2)]
    assert rep["coverage"] == pytest.approx(2 / 3)


def test_a_thin_month_counts_as_missing():
    """A month with a few dozen bars is a failed fetch that returned a fragment."""
    idx = pd.date_range("2024-01-01", "2024-02-29", freq="1h", tz="UTC")
    h = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
                      "half_spread": 1e-5}, index=idx)
    h = pd.concat([h[h.index.month == 1], h[h.index.month == 2].iloc[:20]])
    rep = forex.completeness(h, first_year=2024, last=pd.Timestamp("2024-02-29", tz="UTC"))
    assert (2024, 2) in rep["missing"]


def test_loading_a_series_with_gaps_is_refused_by_default():
    idx = pd.date_range("2024-01-01", "2024-03-31", freq="1h", tz="UTC")
    h = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
                      "half_spread": 1e-5}, index=idx)
    h = h[h.index.month != 2]
    with pytest.raises(ValueError, match="missing"):
        forex.assert_complete(h, first_year=2024, last=pd.Timestamp("2024-03-31", tz="UTC"))
    forex.assert_complete(h, first_year=2024, last=pd.Timestamp("2024-03-31", tz="UTC"), tolerance=0.5)


def test_fetch_retries_with_backoff_before_giving_up(monkeypatch):
    calls = []
    def flaky(url, timeout=45):
        calls.append(url)
        if len(calls) < 3:
            raise TimeoutError("busy")
        return b"ok"
    sleeps = []
    monkeypatch.setattr(forex, "_raw_get", flaky)
    monkeypatch.setattr(forex.time, "sleep", lambda s: sleeps.append(s))
    assert forex._fetch_raw_with_retry("http://x", attempts=5) == b"ok"
    assert len(calls) == 3
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0], "backoff must grow between attempts"
