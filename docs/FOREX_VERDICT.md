# Forex verdict: no. And this is the cleanest no in the project.

Ten major pairs, 2005 to 2026, 5,630 forex days, real bid and ask from Dukascopy,
walk-forward, $1,000 plus $100 a month. **0 of 15 configurations qualified.**

## Why this result matters more than the crypto one

On crypto I could always say friction killed it, and friction was about half the
shortfall. Here friction is gone and the strategies still lose.

| | Crypto (OKX) | Forex (measured) |
|---|---|---|
| Round-trip cost | 0.72% | 0.013% |
| Friction's cost in Sharpe | 0.6 to 1.3 | **0.025** |
| Best net Sharpe | +0.79 | +0.01 |
| Luck threshold | +1.04 | +0.64 |

Gross and net are now identical to two decimals. The average family loses 0.025 of
Sharpe to all trading costs combined, across twenty-one years. **The excuse is gone and
the answer did not change.** These price-based rules have no edge, independent of the
market they are run in and independent of what trading costs.

## The results

Seven weight-based families, walk-forward:

| Family | Net Sharpe | Gross | Trades | Max drawdown |
|---|---|---|---|---|
| trend_basket | -0.49 | -0.47 | 5,219 | -53% |
| vol_target_trend | -0.51 | -0.49 | 8,612 | -50% |
| xs_reversal | -0.51 | -0.46 | 5,773 | -38% |
| breakout | -0.52 | -0.50 | 3,446 | -46% |
| xs_momentum_gated | -0.52 | -0.49 | 4,066 | -42% |
| xs_momentum | -0.56 | -0.54 | 5,253 | -58% |
| low_vol_trend | -0.57 | -0.54 | 5,209 | -49% |

The engulfing bracket setup, in the market it was designed for, now including the short
half its author intended and the leverage it structurally requires:

| Risk | Sides | Leverage | Net Sharpe | Drawdown | Entries | Win rate |
|---|---|---|---|---|---|---|
| 2% | long | 1:1 | **+0.01** | -30% | 448 | 31.5% |
| 1% | long | 10:1 | -0.17 | -55% | 298 | 31.4% |
| 1% | long | 1:1 | -0.21 | -39% | 452 | 30.3% |
| 2% | long | 10:1 | -0.33 | -65% | 194 | 29.0% |
| 1% | both | 10:1 | -0.40 | -77% | 862 | 31.3% |
| 1% | both | 1:1 | -0.43 | -60% | 855 | 30.5% |
| 2% | both | 1:1 | -0.44 | -68% | 882 | 29.6% |
| 2% | both | 10:1 | -0.38 | **-94%** | 755 | 30.9% |

Every configuration was stopped by the drawdown brake, most of them between 2008 and
2013.

## The one number that explains the whole thing

At a 2:1 reward-to-risk you must win **more than one trade in three** to break even
before costs. Across all eight configurations the setup won between **29.0% and 31.5%**.
It is one to four points under its own break-even line, consistently, in every variant,
over twenty-one years and thousands of trades.

That is not a friction problem or a market problem. The entry signal simply does not
select winners often enough to pay for a stop that is half the size of its target.

## Leverage made it worse, exactly as theory says

Leverage is not an edge multiplier, it is a scale multiplier, and Sharpe is
scale-invariant. Going from 1:1 to 10:1 left the Sharpe roughly where it was and
multiplied the drawdown:

| Config | Sharpe 1:1 → 10:1 | Drawdown 1:1 → 10:1 |
|---|---|---|
| risk 1% long | -0.21 → -0.17 | -39% → -55% |
| risk 2% long | +0.01 → -0.33 | -30% → -65% |
| risk 2% both | -0.44 → -0.38 | -68% → **-94%** |

Leverage did fix the sizing throttle: realised risk went from about 0.5% to the intended
1 to 2%. It bought the strategy the ability to take the risk it wanted, and the strategy
used that ability to lose faster.

## Shorting did not help either

The author's strategy sells in downtrends, which crypto spot could not test. Forex can,
and it made things worse in every pairing: adding the short half moved the Sharpe from
-0.21 to -0.43 at 1% risk, and from +0.01 to -0.44 at 2%. Roughly half of all entries
were shorts, so it was a fair test of the other half of his idea.

## Corrections made before this run, all of them mine

The first forex run reported every family between -0.71 and -0.96. About half of that
was my own error, and I found it by testing my cost model rather than believing my
result.

1. **Financing was modelled as a borrowing cost.** A flat 3% a year on every position,
   as if it were borrowed. At 1:1 nothing is borrowed: being long EURUSD is holding
   euros bought with dollars, so the real quantity is the interest differential, which
   is bidirectional and often positive. The flat charge billed $457 against a $1,000
   account over 21 years. It now charges the broker's swap markup at 1% a year, and the
   true differential is declared unmodelled.
2. **The capped-order counter reported 525 capped out of 449 entries**, impossible on
   its face, because it counted attempts that were later rejected.
3. **A position held across another pair's data gap turned equity into NaN**, because
   the panel is a union of dates. Holdings are now valued at the last known close.
4. **Entries were charged the day's average spread** rather than the opening hour's,
   which is several times wider. Fixed before this run.
5. **Forex days were cut at UTC midnight** rather than the 17:00 New York close,
   producing two-hour stubs whose thin opening print was used as a fill price.

## What I am not going to do

Search more variants, widen the grids, add indicators, or try more pairs. Twenty-one
years, ten instruments, two markets, near-zero friction and 69 pre-registered variants
have now said the same thing. The answer to "does this class of price-based rule have an
edge" is no, and repeating the question with different clothes on is how a research
project turns into a slot machine.

The pre-registered forward tests remain frozen and will report on data that did not
exist when they were chosen. That is the only test left that can still change the answer.
