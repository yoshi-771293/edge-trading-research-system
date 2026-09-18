"""The plausibility tripwire, recalibrated after the positive control caught it
rejecting genuine edges.

Two defects, both found by injecting a known edge and watching the gate refuse it:

1. THE WIN-STREAK THRESHOLD WAS A FIXED 10 DAYS. The longest run in a series grows with
   the length of the series: over 2,000 fair coin flips the longest run of heads reaches
   10 about 62% of the time, and over 5,000 flips 92%. A fixed threshold therefore fires
   on pure noise and on any real edge alike, carrying no information at all.

2. THE ROLLING ONE-YEAR SHARPE RULE FIRED ON HONEST VARIANCE. A strategy whose true
   Sharpe is 1.2 will throw individual one-year windows above 3 simply by sampling. The
   gate flagged a genuine, modest edge as a suspected bug.

The principle the fix restores: the tripwire exists to catch a BROKEN SIMULATOR, so it
must flag results inconsistent with the strategy's own long-run behaviour, not results
that are merely large. A sustained full-sample Sharpe above 3 is still implausible and
is still flagged.
"""
import numpy as np
import pandas as pd
import pytest
from referee import validate


def _idx(n):
    return pd.date_range("2018-01-01", periods=n, freq="1D", tz="UTC")


def _series(n, sharpe, seed=0, vol=0.01):
    rng = np.random.default_rng(seed)
    mu = sharpe * vol / np.sqrt(365)
    return pd.Series(rng.normal(mu, vol, n), index=_idx(n))


# ---- the streak rule must scale with the sample -----------------------------
def test_streak_threshold_grows_with_sample_length():
    assert validate.streak_threshold(500) < validate.streak_threshold(5000)
    assert validate.streak_threshold(2000) >= 10, "a fixed 10 is below a coin's own median at 2,000 days"


def test_a_fair_coin_does_not_trip_the_streak_rule_at_any_sample_size():
    for n in (500, 2000, 5000):
        fired = 0
        for s in range(40):
            r = _series(n, sharpe=0.0, seed=s)
            if "streak" in validate.tripwire(r, periods_per_year=365).reason:
                fired += 1
        assert fired <= 2, f"{fired}/40 noise runs tripped the streak rule at n={n}"


def test_a_genuine_edge_does_not_trip_the_streak_rule():
    for s in range(15):
        r = _series(2000, sharpe=1.3, seed=100 + s)
        assert "streak" not in validate.tripwire(r, periods_per_year=365).reason


def test_an_impossible_streak_still_trips():
    r = _series(2000, sharpe=0.0, seed=7)
    r.iloc[500:560] = 0.004          # sixty consecutive winners: no market does this
    assert "streak" in validate.tripwire(r, periods_per_year=365).reason


# ---- the rolling Sharpe rule must judge against the strategy's own level ----
def test_a_modest_real_edge_is_not_flagged_for_a_hot_year():
    """True Sharpe 1.2 throws one-year windows above 3 by ordinary sampling."""
    flagged = 0
    for s in range(20):
        r = _series(2200, sharpe=1.2, seed=200 + s)
        if "sharpe" in validate.tripwire(r, periods_per_year=365).reason:
            flagged += 1
    assert flagged <= 2, f"{flagged}/20 honest runs were flagged as suspected bugs"


def test_a_sustained_impossible_sharpe_still_trips():
    r = _series(1000, sharpe=6.0, seed=9)
    assert "sharpe" in validate.tripwire(r, periods_per_year=365).reason


def test_a_window_wildly_out_of_line_with_the_rest_still_trips():
    """The real bug signature: one stretch behaving unlike everything around it."""
    r = _series(2500, sharpe=0.2, seed=11)
    r.iloc[1000:1365] = np.abs(r.iloc[1000:1365]) + 0.01     # a year that cannot lose
    assert validate.tripwire(r, periods_per_year=365).tripped


# ---- the original purpose must survive the recalibration -------------------
def test_the_planted_simulator_bug_is_still_caught():
    """Net above gross is the signature the tripwire was built for and must keep."""
    r = _series(1500, sharpe=0.5, seed=13)
    t = validate.tripwire(r, periods_per_year=365, level_violations=42)
    assert t.tripped and "net>gross" in t.reason


def test_a_return_beyond_what_any_asset_offered_is_still_caught():
    r = _series(1200, sharpe=0.3, seed=15)
    bound = pd.Series(0.01, index=r.index)
    r.iloc[600] = 0.25
    t = validate.tripwire(r, periods_per_year=365, asset_bound=bound)
    assert t.tripped and "asset" in t.reason
