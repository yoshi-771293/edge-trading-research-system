"""Costs must scale with each coin's own liquidity. This is the single most likely
source of a FALSE POSITIVE once the universe includes small coins: Bitcoin's spread
applied to a thin altcoin manufactures edge that does not exist."""
import pytest
from referee import costs, venues

BIN = venues.get("binance")


def _base():
    """The venue-anchored floor: measured half-spread times the pessimism factor."""
    return BIN.measured_half_spread * costs.SPREAD_PESSIMISM

BTC_DAILY = 1_500_000_000.0     # BTC-class daily dollar volume
MID_DAILY = 50_000_000.0
SMALL_DAILY = 2_000_000.0


def test_spread_widens_as_daily_liquidity_falls():
    b = costs.half_spread(BTC_DAILY, BIN)
    m = costs.half_spread(MID_DAILY, BIN)
    s = costs.half_spread(SMALL_DAILY, BIN)
    assert b < m < s
    assert b == pytest.approx(_base())          # BTC-class gets the floor
    assert s >= 4 * _base()                     # thin coins pay several times more
    assert s <= costs.MAX_SPREAD_MULT * _base() * (1 + 1e-9)  # but bounded, not infinite


def test_small_coin_round_trip_is_punitive():
    """A 0.5% round trip means a daily strategy on small coins cannot win. Correct."""
    rt = costs.round_trip_cost_frac(500.0, 500_000.0, 500_000.0, SMALL_DAILY, venue=BIN)
    assert rt > 0.008
    btc = costs.round_trip_cost_frac(500.0, 100_000_000.0, 100_000_000.0, BTC_DAILY, venue=BIN)
    assert btc < 0.004
    assert rt > 3 * btc


def test_fill_still_pessimistic_on_both_sides():
    up = costs.fill_price(100.0, +1, 500, 1e7, 1e7, MID_DAILY, venue=BIN)
    dn = costs.fill_price(100.0, -1, 500, 1e7, 1e7, MID_DAILY, venue=BIN)
    assert up > 100.0 > dn


def test_thin_bar_multiplier_still_applies_on_top():
    normal = costs.fill_price(100.0, +1, 500, 1e7, 1e7, MID_DAILY, venue=BIN)
    thin = costs.fill_price(100.0, +1, 500, 1e6, 1e7, MID_DAILY, venue=BIN)     # this bar is 10% of typical
    assert thin > normal


def test_zero_or_missing_liquidity_is_treated_as_worst_case():
    assert costs.half_spread(0.0, BIN) == costs.MAX_SPREAD_MULT * _base()
    assert costs.half_spread(float("nan"), BIN) == costs.MAX_SPREAD_MULT * _base()


def test_order_larger_than_a_bar_is_heavily_penalised():
    """Ordering more than the bar traded must not be cheap."""
    small = costs.slippage_frac(100.0, 1_000_000.0, 1_000_000.0, MID_DAILY, BIN)
    huge = costs.slippage_frac(2_000_000.0, 1_000_000.0, 1_000_000.0, MID_DAILY, BIN)
    assert huge > 10 * small
