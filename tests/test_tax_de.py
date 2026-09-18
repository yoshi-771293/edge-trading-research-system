"""German private-investor crypto tax model (§23 EStG), as it stood for 2026.

Not tax advice and not a filing. A model, to compare strategies on an after-tax basis.

Rules modelled: FIFO per asset; a lot held MORE than 12 months is exempt on disposal;
a lot held 12 months or less is taxable at the personal rate; and the €1,000 figure is a
Freigrenze, a threshold rather than an allowance, so crossing it makes the WHOLE
short-term gain taxable, not just the excess.
"""
import pandas as pd
import pytest
from referee import tax_de as tax


def _t(day, sym, side, units, price):
    return {"time": pd.Timestamp(day, tz="UTC"), "symbol": sym, "side": side,
            "units": units, "fill": price}


def test_a_lot_held_over_a_year_is_exempt():
    trades = [_t("2021-01-01", "BTC", "BUY", 1.0, 100.0),
              _t("2022-06-01", "BTC", "SELL", -1.0, 300.0)]
    r = tax.compute(trades)
    assert r["long_term_gain"] == pytest.approx(200.0)
    assert r["short_term_gain"] == pytest.approx(0.0)
    assert r["tax_due"] == pytest.approx(0.0)


def test_a_lot_sold_inside_a_year_is_taxable():
    trades = [_t("2021-01-01", "BTC", "BUY", 1.0, 100.0),
              _t("2021-06-01", "BTC", "SELL", -1.0, 5000.0)]
    r = tax.compute(trades, rate=0.42, soli=0.055)
    assert r["short_term_gain"] == pytest.approx(4900.0)
    assert r["tax_due"] == pytest.approx(4900.0 * 0.42 * 1.055)


def test_fifo_order_is_used():
    """Two lots at different prices; the FIRST one bought must be the one sold."""
    trades = [_t("2021-01-01", "BTC", "BUY", 1.0, 100.0),
              _t("2021-02-01", "BTC", "BUY", 1.0, 200.0),
              _t("2021-03-01", "BTC", "SELL", -1.0, 300.0)]
    r = tax.compute(trades)
    assert r["short_term_gain"] == pytest.approx(200.0), "sold the 100 lot, not the 200 lot"


def test_the_thousand_euro_figure_is_a_threshold_not_an_allowance():
    base = [_t("2021-01-01", "BTC", "BUY", 1.0, 1000.0)]
    under = tax.compute(base + [_t("2021-06-01", "BTC", "SELL", -1.0, 1999.0)], rate=0.42, soli=0.0)
    assert under["short_term_gain"] == pytest.approx(999.0)
    assert under["tax_due"] == pytest.approx(0.0), "below the threshold, nothing is due"
    over = tax.compute(base + [_t("2021-06-01", "BTC", "SELL", -1.0, 2001.0)], rate=0.42, soli=0.0)
    assert over["short_term_gain"] == pytest.approx(1001.0)
    assert over["tax_due"] == pytest.approx(1001.0 * 0.42), "the WHOLE gain becomes taxable"


def test_the_threshold_applies_per_calendar_year():
    """+800 short-term in each of two years is 1,600 in total, yet nothing is due:
    each year is tested against the threshold on its own."""
    trades = [_t("2021-01-01", "BTC", "BUY", 1.0, 100.0),
              _t("2021-06-01", "BTC", "SELL", -1.0, 900.0),     # 2021: +800, under 1000
              _t("2022-01-05", "BTC", "BUY", 1.0, 100.0),
              _t("2022-06-01", "BTC", "SELL", -1.0, 900.0)]     # 2022: +800, under 1000
    r = tax.compute(trades, rate=0.42, soli=0.0)
    assert set(r["by_year"]) == {2021, 2022}
    assert r["short_term_gain"] == pytest.approx(1600.0)
    assert r["tax_due"] == pytest.approx(0.0)


def test_fifo_can_turn_a_late_sale_into_an_exempt_one():
    """Selling after a year sells the OLDEST lot, which may already be exempt even
    though a newer lot of the same coin is not."""
    trades = [_t("2021-01-01", "BTC", "BUY", 1.0, 100.0),
              _t("2021-07-01", "BTC", "BUY", 1.0, 100.0),
              _t("2022-02-01", "BTC", "SELL", -1.0, 900.0)]
    r = tax.compute(trades)
    assert r["long_term_gain"] == pytest.approx(800.0)
    assert r["short_term_gain"] == pytest.approx(0.0)


def test_losses_offset_gains_within_the_same_year():
    trades = [_t("2021-01-01", "A", "BUY", 1.0, 1000.0), _t("2021-03-01", "A", "SELL", -1.0, 3000.0),
              _t("2021-04-01", "B", "BUY", 1.0, 2000.0), _t("2021-05-01", "B", "SELL", -1.0, 500.0)]
    r = tax.compute(trades, rate=0.42, soli=0.0)
    assert r["short_term_gain"] == pytest.approx(500.0)


def test_each_asset_has_its_own_fifo_queue():
    trades = [_t("2021-01-01", "A", "BUY", 1.0, 100.0), _t("2021-01-02", "B", "BUY", 1.0, 500.0),
              _t("2021-03-01", "B", "SELL", -1.0, 600.0)]
    r = tax.compute(trades)
    assert r["short_term_gain"] == pytest.approx(100.0), "sold B against B's basis, not A's"


def test_unrealised_gains_are_reported_but_not_taxed():
    trades = [_t("2021-01-01", "BTC", "BUY", 1.0, 100.0)]
    r = tax.compute(trades, marks={"BTC": 5000.0}, as_of=pd.Timestamp("2023-01-01", tz="UTC"))
    assert r["tax_due"] == pytest.approx(0.0)
    assert r["unrealised"] == pytest.approx(4900.0)
    assert r["unrealised_exempt"] == pytest.approx(4900.0), "held over a year, exempt if sold now"
