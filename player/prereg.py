"""A pre-registered, deliberately small search space, judged on forward data only.

Why this file exists. Narrowing a search raises the apparent confidence of whatever
survives, because the multiple-testing penalty shrinks. That is legitimate when the
narrow space is committed to in advance, and worthless when it is chosen after seeing
which variant won. A noise experiment on 2,000 runs of 87 edgeless strategies makes the
size of the problem plain: judged against the 87 actually tried, 42% of pure-noise
winners clear a 0.50 confidence bar; narrowed after the fact to 7, 100% of them do.

This narrowing was chosen AFTER an 87-variant run, so it is contaminated with respect to
history and may never be scored against it. `assert_forward_only` enforces that. The set
is frozen with a date, and only data after that date counts.

Two disciplines make the set defensible rather than cherry-picked:

1. Each family takes the MIDDLE value of its existing grid, by position. Not the best
   performer, not a value tuned afterwards. The rule picks the parameter, not the result.
2. The fastest horizon is dropped on a cost argument that predates any result: friction
   scales with trade count, and 4-hour trading generated 16,000 trades against weekly's
   660. That reasoning was in the plan before the first search ran.

The bar is also raised. A 0.50 confidence threshold is a coin flip, and the noise
experiment above shows it admits 42% of edgeless winners. A pre-registered set is held to
the conventional 0.95 instead, because with a small space there is no excuse for less.
"""
from __future__ import annotations
import json
import os
import stat
from pathlib import Path

import pandas as pd

from player import families

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
MIN_PSR = 0.95

# Families with the strongest published prior, independent of anything measured here:
# time-series trend following and cross-sectional momentum.
FAMILIES_CHOSEN = ["trend_basket", "xs_momentum"]
BARS_CHOSEN = ["1d", "1w"]
SELECTION_RULE = (
    "Two families with the strongest published prior (time-series trend, cross-sectional "
    "momentum); each takes the MIDDLE value of its grid by position, never its best "
    "performer; the 4-hour horizon is dropped because friction scales with trade count."
)


BRACKET_SET = [
    {"venue": "okx", "risk_frac": 0.02, "grid_index": 2},
    {"venue": "okx", "risk_frac": 0.05, "grid_index": 2},
    {"venue": "okx", "risk_frac": 0.01, "grid_index": 0},
]
BRACKET_RULE = (
    "Trend-pullback-engulfing with a stop and a 2:1 target, ported from the MT5 tutorial "
    "and tested 2026-09-17. Three risk levels at the only venue an EU resident may use. "
    "Chosen AFTER seeing the historical test, so history is inadmissible for this set: it "
    "failed the trade-count and multi-regime gates there, and traded only 7% of the days.")


def build_brackets(now: pd.Timestamp | None = None) -> dict:
    """The bracket-order setup, pre-registered for forward evaluation only."""
    now = now or pd.Timestamp.now(tz="UTC")
    return {"frozen_at": str(now),
            "score_from": str(now.normalize() + pd.Timedelta(days=1)),
            "history_is_invalid_for_this_set": True,
            "selection_rule": BRACKET_RULE,
            "n_trials": len(BRACKET_SET),
            "min_psr": MIN_PSR,
            "min_trades": 100,
            "variants": BRACKET_SET,
            "note": ("Judge the DRAWDOWN behaviour as well as the return. The historical "
                     "test suggested the stop mechanism is worth keeping even though the "
                     "signal is not.")}


def freeze_brackets(now: pd.Timestamp | None = None) -> Path:
    now = now or pd.Timestamp.now(tz="UTC")
    spec = build_brackets(now)
    STATE_DIR.mkdir(exist_ok=True)
    path = STATE_DIR / f"preregistration_brackets_{now.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(spec, indent=1))
    os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return path


def build(now: pd.Timestamp | None = None) -> dict:
    now = now or pd.Timestamp.now(tz="UTC")
    variants = []
    for fam in FAMILIES_CHOSEN:
        grid = families.FAMILIES[fam]["grid"]
        mid = grid[len(grid) // 2]
        for bar in BARS_CHOSEN:
            variants.append({"family": fam, "bar": bar, "param": list(mid)})
    score_from = (now.normalize() + pd.Timedelta(days=1))
    return {
        "frozen_at": str(now),
        "score_from": str(score_from),
        "history_is_invalid_for_this_set": True,
        "selection_rule": SELECTION_RULE,
        "n_trials": len(variants),
        "min_psr": MIN_PSR,
        "variants": variants,
        "note": ("This set was narrowed after an 87-variant search, so its apparent "
                 "confidence on historical data would be manufactured. Only data from "
                 "score_from onward is admissible evidence about it."),
    }


def freeze(now: pd.Timestamp | None = None) -> Path:
    now = now or pd.Timestamp.now(tz="UTC")
    spec = build(now)
    STATE_DIR.mkdir(exist_ok=True)
    path = STATE_DIR / f"preregistration_{now.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(spec, indent=1))
    os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return path


def latest() -> dict | None:
    files = sorted(STATE_DIR.glob("preregistration_*.json"))
    return json.loads(files[-1].read_text()) if files else None


def assert_forward_only(spec: dict, index: pd.DatetimeIndex) -> None:
    """Refuse any attempt to score the pre-registered set on pre-freeze data."""
    cutoff = pd.Timestamp(spec["score_from"])
    if len(index) and pd.DatetimeIndex(index).min() < cutoff:
        raise ValueError(
            f"data starts {pd.DatetimeIndex(index).min().date()}, before the pre-registration "
            f"cutoff {cutoff.date()}. This set was narrowed with knowledge of history, so "
            f"scoring it on history would manufacture confidence rather than measure it.")
