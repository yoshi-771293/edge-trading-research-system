"""Forex friction, built on MEASURED spreads.

The crypto cost model had to infer the spread from dollar volume, because Binance's
feed gives no bid or ask, and then multiply it by a pessimism factor. Here the real
historical half-spread sits in the data at every bar, so the inference is replaced by a
measurement. A pessimism factor still applies, for three honest reasons:

  * the published bid and ask are the interbank top of book, and a retail account is
    quoted worse than that
  * depth at the touch is finite, and a market order walks the book
  * spreads widen exactly when a strategy most wants to trade, around data releases and
    at the session roll, and an average over the hour hides that

Two costs the crypto side did not have:

  * COMMISSION. A raw-spread retail account charges a per-side commission even when the
    spread is near zero. Ignoring it would make forex look free.
  * CARRY. Holding a forex position overnight triggers a swap. CORRECTED 2026-09-18:
    an earlier version charged a flat 3% a year as if the position were borrowed. At
    1:1 leverage nothing is borrowed. Being long EURUSD is holding euros bought with
    dollars, so what you face is the INTEREST DIFFERENTIAL between the two currencies,
    which is bidirectional and is often positive. The flat charge billed $457 against a
    $1,000 account over 21 years and supplied about half of every strategy's negative
    Sharpe, which is a wrong sign on a real quantity rather than conservatism.

    What is modelled now: the broker's MARKUP on the swap, taken whichever way you
    face, which a retail account really does pay. What is NOT modelled, and is declared
    here as a known gap: the underlying interest differential itself, which would
    require a policy-rate series per currency. Ignoring it means carry trades are
    neither rewarded nor punished, so any result here is about price behaviour alone.
"""
from __future__ import annotations
import math

SPREAD_PESSIMISM = 3.0          # multiple of the measured interbank half-spread
WORST_HALF_SPREAD = 0.00050     # 5 bp, used when the feed gives nothing
COMMISSION = 0.000035           # 0.0035% per side, a typical raw-spread retail rate
SWAP_MARKUP_ANNUAL = 0.010      # broker markup on the swap, charged either way you face
FINANCING_ANNUAL = SWAP_MARKUP_ANNUAL   # retained name; see the correction note above
IMPACT_K = 0.0                  # a retail-sized forex order does not move a major pair


def half_spread(measured: float | None) -> float:
    """Scale the measured half-spread. Missing or zero is the worst case, never free."""
    if measured is None or not (measured > 0) or measured != measured:
        return WORST_HALF_SPREAD
    return max(measured * SPREAD_PESSIMISM, 0.0)


def fill_price(mid: float, side: int, measured_half_spread: float | None) -> float:
    """side=+1 buy, -1 sell. Symmetric around the mid, always against us."""
    return mid * (1 + side * half_spread(measured_half_spread))


def commission(notional: float, per_side: float = COMMISSION) -> float:
    return abs(notional) * per_side


def round_trip(measured_half_spread: float | None, commission_per_side: float = COMMISSION) -> float:
    """Total cost of opening and closing, as a fraction of notional."""
    return 2 * (commission_per_side + half_spread(measured_half_spread))


def financing_cost(notional: float, days: float, annual: float = SWAP_MARKUP_ANNUAL) -> float:
    """The broker's swap markup for holding overnight, charged on the ABSOLUTE notional
    so a short pays it as surely as a long. The true interest differential is not
    modelled; see the note at the top of this file."""
    n = abs(float(notional))
    if n <= 0 or days <= 0:
        return 0.0
    return n * ((1 + annual / 365.0) ** days - 1)
