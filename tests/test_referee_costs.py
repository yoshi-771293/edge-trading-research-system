"""Core cost properties. Liquidity scaling: test_costs_liquidity.py.
Venue fees and maker modelling: test_venues_maker.py."""
import pytest
from referee import costs, venues

BIG = 1_000_000_000.0
BIN = venues.get("binance")


def test_buy_fills_above_open_and_sell_below():
    assert costs.fill_price(100.0, +1, 500, 1e7, 1e7, BIG, venue=BIN) > 100.0
    assert costs.fill_price(100.0, -1, 500, 1e7, 1e7, BIG, venue=BIN) < 100.0


def test_impact_scales_with_order_size():
    small = costs.fill_price(100.0, +1, 500, 1e6, 1e6, BIG, venue=BIN)
    big = costs.fill_price(100.0, +1, 50_000, 1e6, 1e6, BIG, venue=BIN)
    assert big > small


def test_thinning_multiplier_on_illiquid_bar():
    normal = costs.fill_price(100.0, +1, 500, 1e7, 1e7, BIG, venue=BIN)
    thin = costs.fill_price(100.0, +1, 500, 1e6, 1e7, BIG, venue=BIN)
    assert thin > normal


def test_commission_uses_the_venue_rate():
    assert costs.commission(1000.0, BIN, "taker") == pytest.approx(0.75)
    assert costs.commission(1000.0, BIN, "maker") == pytest.approx(0.75)
    assert costs.commission(1000.0, venues.get("mexc"), "maker") == pytest.approx(0.0)


def test_model_stays_more_pessimistic_than_the_measured_market():
    """The referee must never charge less than a venue really quotes. Binance's
    measured all-in taker was 0.086% per side; the model must exceed that."""
    modelled = BIN.taker_fee + costs.half_spread(BIG, BIN)
    assert modelled > BIN.all_in_taker()
    assert costs.round_trip_cost_frac(1000.0, 1e9, 1e9, BIG, venue=BIN) > 2 * BIN.all_in_taker()
    assert costs.round_trip_cost_frac(1000.0, 1e9, 1e9, BIG, venue=BIN) >= 0.0025


def test_delist_haircut_is_a_real_penalty():
    assert 0.1 <= costs.DELIST_HAIRCUT <= 0.5
