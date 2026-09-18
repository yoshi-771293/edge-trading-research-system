"""Pessimistic friction, scaled to each coin's own liquidity.

Why liquidity scaling matters more than anything else here: Bitcoin's real spread is
about 0.01 bp, a small altcoin's is 20-50 bp. Applying a Bitcoin spread across a
broad universe would invent an edge that does not exist in a tradable market. Every
number below is deliberately worse than reality for large coins and roughly honest
for small ones.

Per side, a fill costs: commission + half_spread(coin liquidity) + impact(order size
vs this bar's volume), with an extra multiplier when THIS bar was unusually thin.
"""
from __future__ import annotations
import math

from .venues import Venue, get as get_venue

COMMISSION = 0.0010            # 0.10% taker, Binance spot, no BNB/VIP discount
BASE_HALF_SPREAD = 0.0005      # legacy floor, kept only for the venue-less default path
SPREAD_PESSIMISM = 5.0         # multiple of each venue's MEASURED top-of-book half-spread
REF_DAILY_QV = 1_000_000_000.0  # daily dollar volume that earns the floor
MAX_SPREAD_MULT = 20.0         # thin coins pay up to 1.0% half-spread
SPREAD_EXP = 0.5               # spread grows with sqrt of illiquidity
IMPACT_K = 0.10                # impact = K * sqrt(order$ / bar $volume)
THIN_RATIO = 0.20              # this bar under 20% of its typical volume = thin
THIN_MULT = 3.0
MIN_TRADE_USD = 25.0
MAKER_QUEUE_MARGIN = 0.0010    # price must trade 0.10% BEYOND the limit before we fill
DELIST_HAIRCUT = 0.30          # forced exit when a coin stops trading


def half_spread(median_daily_qv: float, venue: Venue | None = None) -> float:
    """Half-spread for a coin on a venue.

    Anchored on what that venue ACTUALLY quoted for top-30 coins, multiplied by
    SPREAD_PESSIMISM because top-of-book understates real execution cost (depth runs
    out, and price moves between the decision and the fill), then widened further for
    illiquid coins. Missing liquidity is the worst case, never free.

    The pessimism factor applies to every venue equally. That matters: it multiplies a
    venue's spread disadvantage while leaving its fee advantage alone, so a thin-book
    venue with cheap fees can come out worse here than its headline rate suggests.
    """
    v = venue or get_venue()
    base = v.measured_half_spread * SPREAD_PESSIMISM
    if median_daily_qv is None or not (median_daily_qv > 0) or median_daily_qv != median_daily_qv:
        return MAX_SPREAD_MULT * base
    mult = (REF_DAILY_QV / median_daily_qv) ** SPREAD_EXP
    return base * min(max(mult, 1.0), MAX_SPREAD_MULT)


def slippage_frac(order_usd: float, bar_qv: float, median_bar_qv: float, median_daily_qv: float,
                  venue: Venue | None = None) -> float:
    qv = max(bar_qv, 1.0)
    impact = IMPACT_K * math.sqrt(abs(order_usd) / qv)
    s = half_spread(median_daily_qv, venue) + impact
    if median_bar_qv and median_bar_qv > 0 and bar_qv < THIN_RATIO * median_bar_qv:
        s *= THIN_MULT
    return s


def fill_price(open_price: float, side: int, order_usd: float, bar_qv: float,
               median_bar_qv: float, median_daily_qv: float,
               venue: Venue | None = None, style: str = "taker") -> float:
    """TAKER fill: cross the spread at this bar's open, pushed against us by
    half-spread plus size impact."""
    return open_price * (1 + side * slippage_frac(order_usd, bar_qv, median_bar_qv, median_daily_qv, venue))


def maker_fill(open_px: float, high: float, low: float, side: int, median_daily_qv: float,
               venue: Venue | None = None) -> float | None:
    """MAKER fill, or None if the order was never touched.

    A resting limit is placed half a spread on our own side of the open: a bid below it
    for a buy, an offer above it for a sell. It fills ONLY if the bar actually traded
    through that price, which is what makes this honest. The consequence is adverse
    selection, and it is the point: we get filled on coins that sag toward us and we
    MISS the ones that gap away. Assuming a maker order always fills would invent an
    edge out of nothing.
    """
    v = venue or get_venue()
    hs = half_spread(median_daily_qv, v)
    limit = open_px * (1 - side * hs)
    # Queue position: a small order rests behind whatever is already at the touch, so a
    # bar that merely kisses the limit does not clear the queue. Requiring price to
    # trade MAKER_QUEUE_MARGIN beyond the limit is what stops this model inventing
    # income out of prices that never really traded to us.
    if side > 0:
        trigger = limit * (1 - MAKER_QUEUE_MARGIN)
        return limit if (low is not None and low == low and low < trigger) else None
    trigger = limit * (1 + MAKER_QUEUE_MARGIN)
    return limit if (high is not None and high == high and high > trigger) else None


def commission(order_usd: float, venue: Venue | None = None, style: str = "taker") -> float:
    v = venue or get_venue()
    rate = v.maker_fee if style == "maker" else v.taker_fee
    return abs(order_usd) * rate


def round_trip_cost_frac(order_usd: float, bar_qv: float, median_bar_qv: float, median_daily_qv: float,
                         venue: Venue | None = None, style: str = "taker") -> float:
    v = venue or get_venue()
    if style == "maker":
        return 2 * (v.maker_fee - half_spread(median_daily_qv, v))
    return 2 * (v.taker_fee + slippage_frac(order_usd, bar_qv, median_bar_qv, median_daily_qv, v))
