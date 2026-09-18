# What real capital would require

This document exists because the plan reserved it. It is **not** a recommendation to
fund anything: as of 16 September 2026 no strategy has qualified, and the code contains
no exchange keys, no request signing and no order-submission path. Nothing here has
been built.

## Venue choice, and why the obvious answer is wrong

Fees were compared against live best bid and ask read from each venue's public API on
16 September 2026, across the 26 tradable coins of the then-current top-30 universe.

| Venue | Taker fee | Maker fee | Median half-spread | All-in taker | All-in maker |
|---|---|---|---|---|---|
| MEXC | 0.050% | **0.000%** | 0.0252% | **0.0752%** | **-0.0252%** |
| Binance | 0.075% | 0.075% | **0.0109%** | 0.0859% | 0.0641% |
| Gate | 0.090% | 0.090% | 0.0099% | 0.0999% | 0.0801% |
| Kraken | 0.250% | 0.250% | 0.0222% | 0.2722% | 0.2278% |

Fees are entry-tier spot rates with the native-token discount applied where one exists
(BNB on Binance). No volume tier is assumed anywhere, because a $1,000 account will
never reach one.

On raw top-of-book numbers MEXC is the cheapest taker. **That ranking reverses once you
stop assuming top-of-book fills.** The referee multiplies every venue's measured spread
by the same pessimism factor of 5, because depth runs out and price moves between the
decision and the fill. That factor multiplies MEXC's spread disadvantage while leaving
its fee advantage untouched, so Binance's far deeper books win on taker orders:

- Binance taker, modelled: 0.075% + 0.055% = **0.130% per side**
- MEXC taker, modelled: 0.050% + 0.126% = **0.176% per side**

**MEXC wins only if orders genuinely rest passively.** A free maker fee plus an earned
spread is a credit before the price even moves. That is the whole case for MEXC, and it
depends entirely on fills you cannot assume.

## The lever that actually matters

Friction on the best strategy found was $1,045 over 626 trades, 0.246% of the $425,273
notional traded. It split as:

| Component | Amount | Share |
|---|---|---|
| Commission | $425 | 41% |
| Spread | $508 | 49% |
| Size impact | $112 | 11% |

Size impact is nearly irrelevant at a $229 median trade. Commission and spread are the
whole cost, roughly half each. So the levers, in order of size:

1. **Stop paying the spread and start earning it.** Worth about $1,000 of the $1,045,
   because it removes the commission and flips the spread from a cost to income.
2. **Trade less often.** Weekly trading paid $78 of friction against daily's $1,045 for
   the same family.
3. **Change venue for the fee alone.** Worth at most $425, and Binance to MEXC on taker
   orders is worth *negative* money once spreads are modelled honestly.

## What a maker-only account really costs

The referee now models passive orders against each bar's actual high and low. A resting
bid fills only if the bar traded down to it. The consequence is adverse selection, and
it is the point: you get filled on the coins that sag toward you and you miss the ones
that gap away. A missed entry is simply missed. A missed exit escalates to a taker order
on the next bar, because capital must never be stranded.

That is a model, not a measurement. Before real money, it needs replacing with recorded
fills.

## Conditions that would have to be true

1. **A strategy clears the bar first.** Deflated Sharpe above the multiple-testing
   threshold, earnings in more than one regime, and at least 100 out-of-sample trades.
   Nothing has.
2. **Twelve months of forward paper trading** with no kill-switch trip. Every one of the
   21 strategies tested was stopped within a median 128 days, so this is the binding
   constraint, not a formality.
3. **Measured fills replace modelled ones.** Run the passive strategy against a live
   order book for at least a month, recording requested versus achieved price and the
   non-fill rate, then re-run the backtest with those numbers. If the real non-fill rate
   is materially worse than the bar's high and low imply, the maker case collapses.
4. **The edge survives doubled costs.** If halving the assumed friction is what makes it
   work, it does not work.
5. **Counterparty risk is priced.** MEXC's fee advantage comes with the least regulatory
   protection of the four. For a $1,000 experiment that may be acceptable; it is a
   different conversation for meaningful capital.
6. **A separate, funded, revocable account**, never one holding anything else, with
   withdrawal-disabled API keys held outside this repository.

## What would still not be built

Order submission, key storage and request signing. If conditions 1 through 6 are ever
met, that is a new project with its own review, not an extension of this one.
