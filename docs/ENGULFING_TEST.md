# The MT5 trend-pullback-engulfing strategy, tested

Ported from the TikTok tutorial by TradingByJesper and run through the same harness as
everything else: point-in-time top-30 universe, walk-forward selection, pessimistic
costs, $1,000 plus $100 a month, 17 September 2026.

## What was ported, and what could not be

Faithfully: two exponential averages defining trend, a pullback into the band between
them, an engulfing candle as the trigger, a stop at a swing low or 1.5x ATR, a target at
a fixed multiple of risk, and position size set by risking a fixed percentage.

Not ported, for two honest reasons. **The short half is impossible here**: the original
sells in downtrends, which needs shorting, and this account is spot-only with no
leverage by its own specification. So only the long half was tested. And **the entry is
one bar later than the tutorial says**: "enter at the close of the engulfing candle" is
not achievable by a system that learns the close only once the bar has ended, so entries
fill at the next bar's open, which is strictly worse.

This required a new execution engine, `referee/brackets.py`, because the rest of the
project holds target weights and rebalances and cannot place a stop. 14 tests cover it.
Its central assumption: when one bar touches both the stop and the target, daily data
cannot say which came first, so the engine **always assumes the stop**. Resolving that
the other way is the standard method for making a bracket backtest print money.

## Full results

| Venue | Risk/trade | Value | vs holding BTC | Sharpe | Worst dip | Entries | Win rate | Friction |
|---|---|---|---|---|---|---|---|---|
| Binance | 1% | $8,821 | $16,531 | +0.66 | -30% | 166 | 49% | $76 |
| Binance | 2% | $9,405 | $16,531 | +0.72 | -27% | 121 | 52% | $104 |
| Binance | 5% | $9,328 | $16,531 | +0.71 | -26% | 39 | 56% | $71 |
| OKX | 1% | $8,646 | $16,361 | +0.59 | -31% | 166 | 49% | $222 |
| **OKX** | **2%** | **$9,615** | $16,361 | **+0.95** | **-26%** | 73 | **66%** | $154 |
| OKX | 5% | $10,678 | $16,361 | +0.94 | -38% | 38 | 71% | $207 |

Bitcoin's Sharpe over the same span was +0.70. So on a risk-adjusted basis the best
configuration beat it, +0.95 against +0.70, with a third of the drawdown. **That is the
first time anything in this project has beaten buy-and-hold on any measure.**

## Why it still does not qualify

**It traded 140 of 2,092 days. Seven percent.** Every configuration was stopped by the
25% drawdown brake between February and September 2021, and then sat in cash for the
remaining 5.3 years. The +0.95 Sharpe is a Sharpe of **+3.54 over 140 real days**,
diluted by five years of zeros.

Those 140 days were December 2020 to April 2021, the most violent altcoin rally on
record. Bitcoin and Ethereum also posted Sharpes above 2 in that window, which is why
the plausibility tripwire correctly did not fire: the market really did that.

The six gates, scored honestly against all 30 configurations I tried:

| Gate | Result |
|---|---|
| 1. Causality | **Pass** |
| 2. At least 100 out-of-sample trades | **Fail**, 73 |
| 3. Net Sharpe above zero | Pass, +3.55 |
| 4. Beats the best of 30 noise trials | Pass by 0.19, and see below |
| 5. Earns in more than one regime | **Fail**, 100% from bull markets |
| 6. Plausibility tripwire | Pass, clean |

Gate 4's "pass" is worthless and I want to be explicit about it. On a 140-day sample,
30 trials of pure noise produce a best Sharpe of **+3.36** by luck alone. The strategy
scored +3.55. Clearing a luck threshold of 3.36 by a fifth of a point is not evidence of
anything. Gates 2 and 5 exist precisely to catch a result like this, and they did.

In dollars it made $9,615 against holding's $16,361, and after German tax $8,812 against
$16,361, because every gain was short-term.

## What is genuinely worth keeping

Two things, and they are real.

**The stop-and-target structure cut the drawdown by two thirds**, from Bitcoin's -77% to
-26%, and produced a 66% win rate at a 2:1 reward. That is a structural improvement over
rebalancing toward target weights, and it is the mechanism, not the signal, that did it.
None of my seven original families had an explicit stop.

**The signal itself is the same trend-pullback idea that was my first champion** and died
the same way: one spectacular window during a mania, then a halt. The engulfing candle
changed the entry timing, not the dependence on a rising market.

## What happens now

A second pre-registration, frozen today as a read-only file, containing the three
configurations that actually looked best, to be judged **only on data from tomorrow
onward**. They were chosen knowing how this test turned out, so scoring them on history
would manufacture confidence rather than measure it, and the code refuses to do it.

If the drawdown behaviour holds up on forward data while the returns do not, that is
still a useful finding: it would mean the stop mechanism is worth keeping and the signal
is not.
