# Phase 1 verdict: no strategy qualified. The account is not trading.

Rebuilt on the point-in-time top-30 universe, 20 May 2019 to 31 August 2026 (7.3
years), with $1,000 at the start and $100 every month.

## The headline

**0 of 21 family-horizon combinations qualified.** No champion was frozen, so Phase 2
does not begin. The account sits in cash and the weekly search keeps running.

| | Paid in | Worth at the end | Profit | Sharpe | Worst dip |
|---|---|---|---|---|---|
| Bitcoin, same monthly deposits | $9,700 | $38,076 | +$28,376 | 0.82 | -77% |
| Best strategy found, walk-forward | $9,700 | — | +25% on the money at risk | 0.39 | -90% |

The best candidate was daily gated cross-sectional momentum: hold the 5 strongest
coins while the market is above its 100-day average. It needed a Sharpe of 1.04 to
clear the multiple-testing bar for 87 variants tried. It reached 0.39. Only 30% of
its 23 out-of-sample windows were profitable, and it drew down 90%.

## The dollar answer, as a real account with the safety brake on

The table above measures the signal with the drawdown brake switched off, which is
the right way to judge a signal. Run instead as an actual account, brake armed, this
is what happened. Windows differ by horizon because a walk-forward account cannot
start until its first training window is complete.

| | Amount |
|---|---|
| Strategies that made money in dollars | 14 of 21 |
| Total profit across all 21 | +$42,069 |
| Total losses among the 7 losers | -$2,479 |
| Strategies that beat Bitcoin over their own window | **1 of 21** |
| Strategies stopped by the 25% drawdown brake | **21 of 21** |
| Median days of trading before being stopped | 128 |
| Friction paid across all 21 | $5,238 on 5,563 trades |

Best single result, daily trend basket, December 2020 to August 2026, $7,800 paid in:

| | Ended at | Profit |
|---|---|---|
| The strategy | $22,000 | +$14,200 |
| Bitcoin, same deposits, same days | $16,531 | +$8,731 |

It beat Bitcoin by $5,469, and that is the only encouraging number in this project.
It should not encourage you. It traded for **165 days**, from December 2020 to 19 May
2021, turning $1,500 into $15,729 during the most violent altcoin rally on record.
Then it lost 25% from its peak, the brake stopped it, and it held cash for the
remaining **5.3 years**. Every dollar of the curve after May 2021 is your own deposit.
Bitcoin over those same 165 trading days made $829.

So the honest reading is one lucky quarter, not a repeatable edge. And the 21-for-21
kill rate is its own finding: a 25% drawdown limit is incompatible with trading
volatile altcoins. Either the limit is wrong for this instrument, or the instrument is
wrong for the limit. Nothing here tells me which, and I am not going to loosen the
limit after seeing the results.

## What killed it: friction, not signal

Almost every family had a genuinely positive gross Sharpe. Costs then removed all of
it and more.

| Horizon | Best gross Sharpe | Best net Sharpe |
|---|---|---|
| 4-hour | +1.01 | -0.23 |
| Daily | +0.76 | +0.39 |
| Weekly | +0.52 | +0.51 |

For the best daily candidate specifically: before costs the account would have been
worth $92,109. After costs, $39,066. **Trading friction destroyed $53,043, which is
58% of the gross account value.**

The pattern is unambiguous and it is a real economic result, not a modelling artefact.
Trading a broad altcoin universe means paying 0.10% commission plus a spread that runs
from 0.05% on Bitcoin to 1.0% on thin coins, on both sides, thousands of times. The
cross-sectional signals are real, and they are smaller than the toll.

Weekly trading nearly breaks even because it trades 660 times instead of 16,000. It
still does not beat holding Bitcoin.

## Why this is more trustworthy than the earlier BTC/ETH result

The first build restricted to Bitcoin and Ethereum on a false premise, that
survivorship-free data was unavailable. It is available. This run:

- ranks the top 30 by trailing dollar volume among **every pair listed at that
  moment**, from 735 archived pairs, of which 251 have entered the top 30
- keeps coins that later died for as long as they really traded, and forces a
  loss when they stop. LUNA is in the universe from February 2021, falls from $68 to
  $0.00005 in six days, and is force-exited at a further 30% haircut
- excludes 48 Binance leveraged tokens, which are derivatives and show 100,000x
  one-day "gains" at redenomination
- cuts any series where a ticker was reused. Binance reassigned LUNAUSDT to Terra 2.0,
  which unhandled is a 177,399x single-bar gain for a holder of the corpse
- scales the spread to each coin's own liquidity, so Bitcoin's tight market is never
  assumed for a thin altcoin

## What was not tuned

The grids, the cost model, the 30-coin universe size, the deflated-Sharpe threshold
and the walk-forward windows were fixed before the run. Nothing was adjusted after
seeing results. Two referee changes were made during the run, neither of which
affected any eligibility decision: the weekly horizon was added after I noticed it had
been silently skipped, and the plausibility tripwire was corrected to exempt daily
moves that an available coin genuinely delivered. Every candidate failed on economics,
not on a tripwire.

## What happens next, without any action from you

The weekly job re-runs this search on all data including the newest weeks. If a
candidate ever clears the bar, it is seated as champion and live paper trading begins,
recorded with its full reasoning. Until then the account holds cash and reports that
it is holding cash. That is the correct behaviour: the alternative is trading a
strategy the evidence says does not work.

## What would change the answer

Ranked by how much they would move the result:

1. **A venue with lower costs.** The entire deficit is friction. A maker-only
   execution model, or fee tiers, would change the arithmetic more than any signal.
   It would also require modelling non-fills, which is a real research project.
2. **Longer holding periods.** Weekly nearly broke even. Monthly rebalancing is the
   obvious untested horizon.
3. **Something other than price.** Every family here is a function of past prices
   only. Funding rates, on-chain flows and order-book imbalance are different
   information. Perpetual funding is explicitly out of scope by your instruction.

I am not recommending you fund a real account on anything in this document.
