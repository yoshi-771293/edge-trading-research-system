"""Costs for forex, using the MEASURED spread rather than a modelled one.

On the crypto side the spread had to be guessed from dollar volume and then multiplied
by a pessimism factor, because the feed gave no bid or ask. Here the real historical
spread is in the data, so the guess is replaced by a measurement. A pessimism factor is
still applied, because top-of-book understates what a retail order actually pays, but it
now multiplies something real.
"""
import pandas as pd
import pytest
from referee import costs, fxcosts


def test_the_measured_spread_is_used_and_scaled_by_a_stated_factor():
    measured = 0.00002            # 0.2 bp half-spread, typical for EURUSD
    hs = fxcosts.half_spread(measured)
    assert hs == pytest.approx(measured * fxcosts.SPREAD_PESSIMISM)
    assert fxcosts.SPREAD_PESSIMISM >= 2.0, "retail pays more than the interbank top of book"


def test_a_missing_spread_is_treated_as_the_worst_case_not_as_free():
    assert fxcosts.half_spread(float("nan")) >= fxcosts.WORST_HALF_SPREAD
    assert fxcosts.half_spread(0.0) >= fxcosts.WORST_HALF_SPREAD
    assert fxcosts.half_spread(None) >= fxcosts.WORST_HALF_SPREAD


def test_forex_friction_is_far_below_the_crypto_model():
    """The entire reason for coming here."""
    from referee import venues
    fx = fxcosts.round_trip(0.00002, commission_per_side=fxcosts.COMMISSION)
    crypto = costs.round_trip_cost_frac(500.0, 1e8, 1e8, 1e9, venue=venues.get("okx"))
    assert fx < crypto / 3, f"forex round trip {fx:.5%} vs crypto {crypto:.5%}"


def test_commission_is_charged_on_top_of_the_spread():
    """A raw-spread account pays commission as well, so the round trip is both.
    Note a spread of exactly zero is NOT free: it is treated as a missing quote."""
    measured = 0.00002
    rt = fxcosts.round_trip(measured)
    assert rt == pytest.approx(2 * (fxcosts.COMMISSION + measured * fxcosts.SPREAD_PESSIMISM))
    assert rt > 2 * measured * fxcosts.SPREAD_PESSIMISM, "commission must be included"
    assert fxcosts.COMMISSION > 0


def test_buys_fill_above_mid_and_sells_below():
    up = fxcosts.fill_price(1.08000, +1, 0.00002)
    dn = fxcosts.fill_price(1.08000, -1, 0.00002)
    assert up > 1.08000 > dn
    assert (up - 1.08000) == pytest.approx(1.08000 - dn, rel=1e-9)


def test_a_wider_measured_spread_costs_more():
    calm = fxcosts.fill_price(1.08, +1, 0.00002)
    stressed = fxcosts.fill_price(1.08, +1, 0.00050)      # spreads blow out in a crisis
    assert stressed > calm


def test_swap_financing_is_charged_for_holding_overnight():
    """A forex position is financed. Holding is not free the way spot crypto is."""
    one_night = fxcosts.financing_cost(notional=1000.0, days=1)
    a_year = fxcosts.financing_cost(notional=1000.0, days=365)
    assert one_night > 0
    assert a_year > 100 * one_night
