"""Third audit, after the first forex run. Two defects of mine, one structural finding.

1. FINANCING WAS MODELLED AS A BORROWING COST. I charged a flat 3% a year on every
   position. At 1:1 leverage nothing is borrowed: being long EURUSD means holding euros
   bought with dollars, so what you face is the INTEREST DIFFERENTIAL, which is
   bidirectional and can be positive. A flat 3% cost billed $457 against a $1,000
   account over 21 years and supplied roughly half of every strategy's negative Sharpe.
   That is not conservatism, it is a wrong sign on a real quantity.

2. n_capped COUNTED ATTEMPTS, NOT ENTRIES. It reported 525 capped out of 449 entries,
   which is impossible on its face, because it incremented before the cash and
   minimum-size checks could reject the order.

3. Structural, not a bug: a 1:1 forex account CANNOT express a 1%-risk strategy. Daily
   ranges are so small that a normal stop sits well under 1% away, so risking 1% demands
   a position larger than the account. The cap then binds on nearly every trade and the
   realised risk is a fraction of the intended one. Leverage is not an enhancement in
   forex, it is a precondition, and the tests below pin that so it is stated rather than
   hidden.
"""
import numpy as np
import pandas as pd
import pytest
from referee import brackets, costmodels, fxcosts


def _bars(n=80, px=1.08, spread=2e-5):
    idx = pd.date_range("2021-01-01", periods=n, freq="1D", tz="UTC")
    return {"A": pd.DataFrame({"open": px, "high": px * 1.004, "low": px * 0.996, "close": px,
                               "volume": 1e6, "quote_volume": 1e9,
                               "half_spread": spread, "open_half_spread": spread}, index=idx)}


def _sig(idx, at, stop, target, side=+1):
    s = pd.DataFrame(index=idx, columns=pd.MultiIndex.from_product([["A"], ["enter", "stop", "target"]]),
                     dtype=float)
    s[("A", "enter")] = 0.0
    s.iloc[at, s.columns.get_loc(("A", "enter"))] = float(side)
    s.iloc[at, s.columns.get_loc(("A", "stop"))] = stop
    s.iloc[at, s.columns.get_loc(("A", "target"))] = target
    return s


# ---- 1. carry, not borrowing ----------------------------------------------
def test_the_default_carry_charge_is_a_broker_markup_not_a_borrowing_rate():
    assert fxcosts.SWAP_MARKUP_ANNUAL <= 0.015, "3% a year is a borrowing rate, not a swap markup"
    assert fxcosts.SWAP_MARKUP_ANNUAL > 0, "a retail account really does pay a markup on both sides"


def test_carry_is_charged_symmetrically_on_longs_and_shorts():
    """The broker's markup is taken whichever way you face. The underlying differential
    is NOT modelled and is declared as a known gap."""
    cm = costmodels.ForexCosts()
    assert cm.financing(1000.0, 1) == pytest.approx(cm.financing(-1000.0, 1))
    assert cm.financing(1000.0, 1) > 0


def test_twenty_one_years_of_carry_is_a_markup_sized_drag_not_half_the_account():
    cm = costmodels.ForexCosts()
    drag = sum(cm.financing(830.0, 1) for _ in range(365 * 21))       # 83% average exposure
    assert drag < 250.0, f"carry billed ${drag:,.0f} against a $1,000 account"


def test_the_true_interest_differential_is_declared_unmodelled():
    assert "differential" in fxcosts.__doc__.lower()
    assert costmodels.ForexCosts().unmodelled_carry is True


# ---- 2. the cap counter --------------------------------------------------
def test_capped_entries_never_exceed_entries():
    b = _bars()
    idx = b["A"].index
    # a stop 0.4% away with 1% risk asks for 250% of equity: the cap must bind
    r = brackets.execute(b, _sig(idx, 40, 1.08 * 0.996, 1.10), start_equity=10_000.0,
                         risk_frac=0.01, cost_model=costmodels.ForexCosts(), kill_switch=False)
    n_entries = int((r.trades["reason"] == "entry").sum())
    assert r.n_capped <= n_entries, f"{r.n_capped} capped vs {n_entries} entries"


def test_an_order_rejected_for_size_is_not_counted_as_capped():
    b = _bars()
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 40, 1.08 * 0.5, 1.10), start_equity=100.0,
                         risk_frac=0.01, cost_model=costmodels.ForexCosts(), kill_switch=False)
    assert len(r.trades) == 0
    assert r.n_capped == 0


# ---- 3. leverage is a precondition in forex --------------------------------
def test_at_one_to_one_the_realised_risk_is_far_below_the_intended_risk():
    b = _bars()
    idx = b["A"].index
    r = brackets.execute(b, _sig(idx, 40, 1.08 * 0.996, 1.10), start_equity=10_000.0,
                         risk_frac=0.01, cost_model=costmodels.ForexCosts(), kill_switch=False)
    assert r.effective_risk_frac < 0.005, "1% intended risk should be throttled to well under half"


def test_leverage_lets_the_intended_risk_actually_be_taken():
    b = _bars()
    idx = b["A"].index
    lev = brackets.execute(b, _sig(idx, 40, 1.08 * 0.996, 1.10), start_equity=10_000.0,
                           risk_frac=0.01, cost_model=costmodels.ForexCosts(), kill_switch=False,
                           leverage=10.0)
    assert lev.effective_risk_frac == pytest.approx(0.01, rel=0.2)
    assert lev.n_capped == 0


def test_leverage_scales_the_position_and_is_reported():
    """Leverage raises the CAP; risk-based sizing still decides the size. With a tight
    stop the cap is what binds, so leverage is exactly what lets the intended risk be
    taken. Measured on the entry notional, because a stop at the bar's low closes the
    position on its own entry bar and exposure never marks."""
    b = _bars()
    idx = b["A"].index
    flat = brackets.execute(b, _sig(idx, 40, 1.08 * 0.996, 1.10), start_equity=10_000.0,
                            risk_frac=0.01, cost_model=costmodels.ForexCosts(),
                            kill_switch=False, leverage=1.0)
    lev = brackets.execute(b, _sig(idx, 40, 1.08 * 0.996, 1.10), start_equity=10_000.0,
                           risk_frac=0.01, cost_model=costmodels.ForexCosts(),
                           kill_switch=False, leverage=10.0)
    f = flat.trades[flat.trades["reason"] == "entry"].iloc[0]["usd"]
    l = lev.trades[lev.trades["reason"] == "entry"].iloc[0]["usd"]
    assert l > f * 5
    assert flat.n_capped == 1 and lev.n_capped == 0
    assert lev.leverage == 10.0 and flat.leverage == 1.0


def test_leverage_multiplies_the_drawdown_too():
    """Leverage is not free: it scales losses by the same factor it scales gains. The
    stop sits far enough away that it is never reached, so the whole decline is worn."""
    n = 120
    px = np.linspace(1.08, 1.03, n)              # a steady 4.6% decline into a long position
    idx = pd.date_range("2021-01-01", periods=n, freq="1D", tz="UTC")
    b = {"A": pd.DataFrame({"open": px, "high": px * 1.0005, "low": px * 0.9995, "close": px,
                            "volume": 1e6, "quote_volume": 1e9,
                            "half_spread": 2e-5, "open_half_spread": 2e-5}, index=idx)}
    sig = _sig(idx, 40, 0.97, 2.00)              # a 10% stop, never hit
    from referee import replay
    flat = brackets.execute(b, sig, start_equity=10_000.0, risk_frac=0.10,
                            cost_model=costmodels.ForexCosts(), kill_switch=False, leverage=1.0)
    lev = brackets.execute(b, sig, start_equity=10_000.0, risk_frac=0.10,
                           cost_model=costmodels.ForexCosts(), kill_switch=False, leverage=10.0)
    fdd = replay.metrics(flat.twr, 365)["max_dd"]
    ldd = replay.metrics(lev.twr, 365)["max_dd"]
    assert flat.n_capped == 1 and lev.n_capped == 0, "the cap must bind at 1:1 and not at 10:1"
    assert ldd < fdd * 1.8, f"leveraged drawdown {ldd:.2%} vs unleveraged {fdd:.2%}"


def test_leverage_cannot_exceed_the_retail_regulatory_cap():
    b = _bars()
    idx = b["A"].index
    with pytest.raises(ValueError, match="leverage"):
        brackets.execute(b, _sig(idx, 40, 1.05, 1.10), leverage=50.0)
