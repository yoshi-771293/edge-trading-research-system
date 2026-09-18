"""Venue-parameterised costs, and honest maker-order modelling.

A maker (limit) order pays a lower fee and EARNS the spread instead of paying it, but
it only fills if the market actually trades through the limit price. Modelling that
with the bar's own high and low captures adverse selection exactly: you get filled on
the coins that dip toward you, and you MISS the ones that run away. Pretending maker
orders always fill is the single easiest way to invent an edge that does not exist.
"""
import numpy as np
import pytest
from referee import costs, venues


def test_venue_registry_has_the_fields_the_cost_model_needs():
    for name in ["binance", "mexc", "gate", "kraken"]:
        v = venues.get(name)
        assert 0 <= v.maker_fee <= 0.005 and 0 <= v.taker_fee <= 0.005
        assert v.spread_multiplier > 0
        assert v.name and v.note


def test_mexc_is_the_cheapest_taker_and_free_maker():
    mexc, binance, kraken = venues.get("mexc"), venues.get("binance"), venues.get("kraken")
    assert mexc.maker_fee == 0.0
    assert mexc.taker_fee < binance.taker_fee < kraken.taker_fee


def test_binance_has_the_tightest_measured_spread():
    assert venues.get("binance").measured_half_spread < venues.get("mexc").measured_half_spread


def test_taker_cost_is_unchanged_by_switching_to_a_venue_object():
    v = venues.get("binance")
    f = costs.fill_price(100.0, +1, 500, 1e7, 1e7, 1e9, venue=v, style="taker")
    assert f > 100.0
    assert costs.commission(1000.0, venue=v, style="taker") == pytest.approx(1000.0 * v.taker_fee)
    assert costs.commission(1000.0, venue=v, style="maker") == pytest.approx(1000.0 * v.maker_fee)


# ---- maker fills depend on the bar actually reaching the limit -------------
def test_maker_buy_fills_below_the_open_when_the_bar_dips_to_it():
    v = venues.get("mexc")
    got = costs.maker_fill(open_px=100.0, high=101.0, low=98.0, side=+1, median_daily_qv=1e9, venue=v)
    assert got is not None
    assert got < 100.0, "a passive buy must fill better than the open"


def test_maker_buy_does_not_fill_when_the_price_runs_away():
    """The bar opens and only goes up: a resting bid is never touched. You miss it."""
    v = venues.get("mexc")
    assert costs.maker_fill(open_px=100.0, high=115.0, low=100.0, side=+1, median_daily_qv=1e9, venue=v) is None


def test_maker_sell_fills_above_the_open_only_when_the_bar_rallies_to_it():
    v = venues.get("mexc")
    assert costs.maker_fill(100.0, 102.0, 99.0, -1, 1e9, v) > 100.0
    assert costs.maker_fill(100.0, 100.0, 90.0, -1, 1e9, v) is None


def test_maker_is_cheaper_than_taker_when_it_does_fill():
    v = venues.get("mexc")
    taker = costs.fill_price(100.0, +1, 500, 1e7, 1e7, 1e9, venue=v, style="taker")
    maker = costs.maker_fill(100.0, 101.0, 98.0, +1, 1e9, v)
    assert maker < 100.0 < taker
    assert costs.commission(500, v, "maker") <= costs.commission(500, v, "taker")


def test_a_thin_coin_still_has_a_wider_passive_limit():
    v = venues.get("mexc")
    liquid = costs.maker_fill(100.0, 101.0, 90.0, +1, 2_000_000_000.0, v)
    thin = costs.maker_fill(100.0, 101.0, 90.0, +1, 1_000_000.0, v)
    assert thin < liquid, "a thin coin's resting bid should sit further from the open"


def test_all_in_cost_ranking_matches_the_live_measurements():
    """On the RAW measured spreads, MEXC's cheap fee makes it the cheapest taker of all,
    and Coinbase the dearest. Among venues an EU client may use, OKX is cheapest."""
    ranking = sorted(venues.ALL.values(), key=lambda v: v.all_in_taker())
    assert ranking[0].name == "mexc"
    assert ranking[-1].name == "coinbase"
    assert venues.get("mexc").all_in_maker() < 0, "free maker plus earned spread is a credit"


def test_pessimism_reverses_the_taker_ranking_between_mexc_and_binance():
    """The finding that decides the venue. Raw top-of-book says MEXC is the cheapest
    taker. Once every venue's spread is multiplied by the same pessimism factor, MEXC's
    wider books cost more than its cheaper fee saves, and Binance becomes the cheaper
    taker. MEXC only wins if orders can genuinely rest passively."""
    q = 1_000_000_000.0
    mexc_taker = venues.get("mexc").taker_fee + costs.half_spread(q, venues.get("mexc"))
    bin_taker = venues.get("binance").taker_fee + costs.half_spread(q, venues.get("binance"))
    assert bin_taker < mexc_taker
    mexc_maker = venues.get("mexc").maker_fee - costs.half_spread(q, venues.get("mexc"))
    assert mexc_maker < 0 and mexc_maker < bin_taker


# ---- replay integration ---------------------------------------------------
import pandas as pd
from referee import replay, universe


def _bars(opens, highs, lows, closes, qv=1e9):
    idx = pd.date_range("2021-01-01", periods=len(opens), freq="1D", tz="UTC")
    return {"A": pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes,
                               "volume": 1e6, "quote_volume": qv}, index=idx)}


def test_maker_run_skips_an_entry_the_market_ran_away_from():
    """Every bar gaps up and never trades below its open, so a resting bid is never
    hit and the account never gets in. A missed entry is NOT escalated: missing the
    coins that run away is precisely the cost of resting passively."""
    n = 40
    o = [100 * 1.02 ** i for i in range(n)]
    bars = _bars(o, [x * 1.03 for x in o], o, [x * 1.02 for x in o])
    idx = bars["A"].index
    uni = pd.DataFrame(True, index=idx, columns=["A"])
    tgt = pd.DataFrame(0.3, index=idx, columns=["A"])
    taker = replay.execute(bars, tgt, universe=uni, kill_switch=False, venue="mexc", style="taker")
    maker = replay.execute(bars, tgt, universe=uni, kill_switch=False, venue="mexc", style="maker")
    assert len(taker.trades) > 0
    assert len(maker.trades) == 0, "a passive bid must not fill on a bar that never trades down"
    assert maker.equity.iloc[-1] == pytest.approx(1000.0)


def test_maker_fills_cheaper_than_taker_when_the_bar_dips():
    n = 40
    o = [100.0] * n
    bars = _bars(o, [101.0] * n, [97.0] * n, [100.0] * n)
    idx = bars["A"].index
    uni = pd.DataFrame(True, index=idx, columns=["A"])
    tgt = pd.DataFrame(0.3, index=idx, columns=["A"])
    taker = replay.execute(bars, tgt, universe=uni, kill_switch=False, venue="mexc", style="taker")
    maker = replay.execute(bars, tgt, universe=uni, kill_switch=False, venue="mexc", style="maker")
    assert len(maker.trades) > 0
    assert maker.trades.iloc[0]["fill"] < taker.trades.iloc[0]["fill"]
    assert maker.total_costs < taker.total_costs
    assert maker.equity.iloc[-1] > taker.equity.iloc[-1]


def test_switching_venue_changes_cost_in_the_expected_direction():
    n = 60
    o = [100.0] * n
    bars = _bars(o, [102.0] * n, [98.0] * n, [100.0 + (i % 5) for i in range(n)])
    idx = bars["A"].index
    uni = pd.DataFrame(True, index=idx, columns=["A"])
    tgt = pd.DataFrame([0.3 if i % 4 else 0.0 for i in range(n)], index=idx, columns=["A"])
    runs = {v: replay.execute(bars, tgt, universe=uni, kill_switch=False, venue=v, style="taker")
            for v in ["mexc", "binance", "kraken"]}
    # Under the pessimistic spread model Binance's deep books beat MEXC's cheap fee,
    # and Kraken is worst on both counts.
    assert runs["binance"].total_costs < runs["mexc"].total_costs < runs["kraken"].total_costs
    maker = replay.execute(bars, tgt, universe=uni, kill_switch=False, venue="mexc", style="maker")
    assert maker.total_costs < runs["binance"].total_costs


def test_an_unfilled_passive_exit_escalates_to_taker():
    """The account is long and wants out. Its offer sits above the open and the bar
    only falls, so the passive exit fails. It must not be stuck: the next bar crosses."""
    n = 30
    o = [100.0] * 10 + [100.0] * 20
    hi = [102.0] * 10 + [100.0] * 20          # after bar 10 the high never exceeds the open
    lo = [98.0] * 10 + [90.0] * 20
    bars = _bars(o, hi, lo, [100.0] * 10 + [95.0] * 20)
    idx = bars["A"].index
    uni = pd.DataFrame(True, index=idx, columns=["A"])
    tgt = pd.DataFrame(0.0, index=idx, columns=["A"]); tgt.iloc[:10] = 0.3
    r = replay.execute(bars, tgt, universe=uni, kill_switch=False, venue="mexc", style="maker")
    sells = r.trades[r.trades["side"] == "SELL"]
    assert len(sells) >= 1, "the position was stranded: a passive exit never escalated"
    assert r.weights["A"].iloc[-1] < 1e-9


# ---- defects the tripwire caught in the maker model itself ----------------
def test_a_mere_touch_of_the_limit_does_not_fill():
    """Queue position. A $229 order rests behind thousands of dollars at the touch.
    If price only kisses the limit and bounces, the queue never clears and you do not
    fill. Requiring the bar to trade THROUGH the limit is what stops this model
    inventing free money."""
    v = venues.get("mexc")
    hs = costs.half_spread(1e9, v)
    limit = 100.0 * (1 - hs)
    assert costs.maker_fill(100.0, 101.0, limit, +1, 1e9, v) is None, "an exact touch must not fill"
    through = limit * (1 - costs.MAKER_QUEUE_MARGIN * 1.01)
    assert costs.maker_fill(100.0, 101.0, through, +1, 1e9, v) is not None, "trading through must fill"


def test_queue_margin_applies_to_sells_too():
    v = venues.get("mexc")
    hs = costs.half_spread(1e9, v)
    limit = 100.0 * (1 + hs)
    assert costs.maker_fill(100.0, limit, 99.0, -1, 1e9, v) is None
    assert costs.maker_fill(100.0, limit * (1 + costs.MAKER_QUEUE_MARGIN * 1.01), 99.0, -1, 1e9, v) is not None


def test_gross_twin_isolates_fees_so_net_can_never_exceed_it():
    """`equity_gross` is the same executed trades with the commission removed. It must
    therefore always be at least equity, under BOTH order styles. The earlier version
    priced the twin at the bar's open, so a maker fill below the open made net beat
    gross and the tripwire fired on every run."""
    n = 60
    o = [100.0] * n
    bars = _bars(o, [103.0] * n, [95.0] * n, [100.0 + (i % 7) for i in range(n)])
    idx = bars["A"].index
    uni = pd.DataFrame(True, index=idx, columns=["A"])
    tgt = pd.DataFrame([0.3 if i % 3 else 0.0 for i in range(n)], index=idx, columns=["A"])
    for style in ["taker", "maker"]:
        r = replay.execute(bars, tgt, universe=uni, kill_switch=False, venue="mexc", style=style)
        assert len(r.trades) > 0, style
        assert (r.equity <= r.equity_gross * (1 + 1e-9)).all(), f"net beat gross under {style}"


def test_maker_spread_income_is_reported_separately_from_fees():
    """Earning the spread is real income and must show up as negative slippage, not be
    hidden inside the fee line."""
    n = 40
    o = [100.0] * n
    bars = _bars(o, [103.0] * n, [95.0] * n, [100.0] * n)
    idx = bars["A"].index
    uni = pd.DataFrame(True, index=idx, columns=["A"])
    tgt = pd.DataFrame(0.3, index=idx, columns=["A"])
    r = replay.execute(bars, tgt, universe=uni, kill_switch=False, venue="mexc", style="maker")
    assert len(r.trades) > 0
    assert (r.trades["fee"] >= 0).all()
    assert r.trades["slippage"].sum() < 0, "a filled passive buy earns the spread"


# ---- venues an EU resident can actually use ------------------------------
def test_the_mica_licensed_venues_are_registered_with_measured_spreads():
    for name in ["okx", "bitvavo", "bitstamp", "coinbase"]:
        v = venues.get(name)
        assert v.measured_half_spread > 0
        assert v.eu_eligible is True, f"{name} holds a MiCA licence"
    for name in ["binance", "mexc"]:
        assert venues.get(name).eu_eligible is False, f"{name} has no MiCA licence"


def test_okx_is_the_cheapest_venue_an_eu_resident_may_use():
    eu = [v for v in venues.ALL.values() if v.eu_eligible]
    assert sorted(eu, key=lambda v: v.all_in_taker())[0].name == "okx"
    assert sorted(eu, key=lambda v: v.all_in_maker())[0].name == "okx"


def test_the_legal_venue_is_worse_than_the_illegal_one_passively():
    """The whole passive-execution case weakens on a licensed venue: MEXC's free maker
    was a credit per side, OKX's is a cost."""
    assert venues.get("mexc").all_in_maker() < 0
    assert venues.get("okx").all_in_maker() > 0
    assert venues.get("okx").all_in_maker() > venues.get("binance").all_in_maker() * 0  # positive


def test_eu_eligible_helper_lists_only_licensed_venues():
    names = set(venues.eu_eligible_names())
    assert "okx" in names and "kraken" in names
    assert "binance" not in names and "mexc" not in names
