"""Pluggable cost models, so one execution engine serves both markets.

The bracket engine was written against the crypto model, where the spread is inferred
from dollar volume. Forex supplies a real measured spread in the bars. Forking the
engine would have meant two copies of the execution logic drifting apart, which is
exactly the failure this project keeps catching, so costs became an object instead.

The crypto path delegates to the existing functions unchanged, and a test asserts it
reproduces them to the cent, so every earlier result remains valid.
"""
from __future__ import annotations
from dataclasses import dataclass

from . import costs, fxcosts
from .venues import Venue, get as get_venue


@dataclass
class CryptoCosts:
    """Spread inferred from dollar volume, impact from order size. Spot, so no
    financing: holding costs nothing."""
    venue: Venue | None = None
    style: str = "taker"

    def __post_init__(self):
        if not hasattr(self.venue, "taker_fee"):
            self.venue = get_venue(self.venue)

    def fill_price(self, mid, side, notional, bar_qv, median_bar_qv, median_daily_qv,
                   measured_half_spread=None):
        return costs.fill_price(mid, side, notional, bar_qv, median_bar_qv, median_daily_qv,
                                venue=self.venue, style=self.style)

    def commission(self, notional):
        return costs.commission(notional, venue=self.venue, style=self.style)

    def financing(self, notional, days):
        return 0.0

    @property
    def name(self):
        return f"crypto:{self.venue.name}:{self.style}"


@dataclass
class ForexCosts:
    """Spread MEASURED from the feed's own bid and ask, scaled for pessimism. No size
    impact, because a retail order does not move a major pair.

    Carry is the broker's swap MARKUP, charged symmetrically on longs and shorts. The
    underlying interest differential is deliberately not modelled, so `unmodelled_carry`
    is True and every result must be read as being about price behaviour alone."""
    commission_per_side: float = fxcosts.COMMISSION
    financing_annual: float = fxcosts.SWAP_MARKUP_ANNUAL
    unmodelled_carry: bool = True

    def fill_price(self, mid, side, notional, bar_qv=None, median_bar_qv=None,
                   median_daily_qv=None, measured_half_spread=None):
        return fxcosts.fill_price(mid, side, measured_half_spread)

    def commission(self, notional):
        return fxcosts.commission(notional, self.commission_per_side)

    def financing(self, notional, days):
        return fxcosts.financing_cost(notional, days, self.financing_annual)

    @property
    def name(self):
        return f"forex:comm{self.commission_per_side:.5f}:fin{self.financing_annual:.3f}"
