# Optimisation and venue readiness, 16 September 2026

## The headline: friction was half the problem, not all of it

I previously told you the entire deficit was friction. That was wrong, and the fix
proves it. Running the same 21 strategies with friction driven to roughly zero:

| Configuration | Best net Sharpe | Best PSR | Eligible |
|---|---|---|---|
| Binance, taker (previous) | +0.40 | 0.06 | 0 of 21 |
| MEXC, taker | +0.47 | 0.08 | 0 of 21 |
| **MEXC, passive limits** | **+0.79** | **0.28** | **0 of 21** |
| Bar to clear | ~1.04 | 0.50 | |

Passive execution on the cheapest venue **doubles** the best net Sharpe and more than
quadruples its statistical confidence. Under that configuration net Sharpe equals gross
Sharpe to two decimals, meaning the earned spread now cancels the commission and
friction is effectively gone.

**And nothing qualifies.** At zero net cost the best strategy still reaches 0.79 against
a bar of 1.04. So friction accounted for about half the shortfall, and the other half is
simply absent signal. That is a cleaner negative result than the one I gave you before,
because it can no longer be blamed on fees.

## Venue: Binance for crossing, MEXC for resting

Measured live on 16 September 2026 from each venue's public API, across the 26 tradable
coins of the then-current top-30 universe:

| Venue | Taker | Maker | Median half-spread | All-in taker | All-in maker |
|---|---|---|---|---|---|
| MEXC | 0.050% | **0.000%** | 0.0252% | **0.0752%** | **-0.0252%** |
| Binance | 0.075% | 0.075% | **0.0109%** | 0.0859% | 0.0641% |
| Gate | 0.090% | 0.090% | 0.0099% | 0.0999% | 0.0801% |
| Kraken | 0.250% | 0.250% | 0.0222% | 0.2722% | 0.2278% |

The interesting part is that the ranking depends on how you trade, and the headline
fee table gets it wrong. Once every venue's spread is multiplied by the same pessimism
factor of five, because top-of-book understates real execution cost:

- Binance taker: 0.130% per side. MEXC taker: 0.176% per side. **Binance wins**, because
  the pessimism multiplies MEXC's wider books while leaving its cheaper fee alone.
- MEXC passive: a free fee plus an earned spread is a **credit** before the price moves.
  **MEXC wins by a wide margin**, and only this way.

Configured default: **MEXC with passive limit orders**, in `live/agent.py`. Switching is
one string; every venue lives in `referee/venues.py` with its measured spread.

## How passive orders are modelled, and why it is not free money

A resting bid sits half a spread below the open. It fills only if the bar traded
**through** it by 0.10%, so the queue ahead of a small order actually clears. A bar that
merely touches the limit does not fill. The consequences are deliberate:

- You are filled on coins that sag toward you and you **miss** the ones that gap away.
  That adverse selection is the real cost of resting, and it is why the Sharpe improves
  by half a point rather than by two.
- A missed entry is simply missed. A missed exit escalates to a crossing order on the
  next bar, so capital is never stranded.

My first version of this got it wrong in both directions at once: it filled on a touch
and priced the friction-free baseline at the bar's open. The net account then beat its
own friction-free twin and the net-exceeds-gross tripwire fired on every single run.
That is exactly what that tripwire is for, and it caught my error rather than a
strategy's.

## Where the money went, before the fix

Friction on the best strategy: $1,045 over 626 trades, 0.246% of $425,273 traded.

| Component | Amount | Share |
|---|---|---|
| Spread | $508 | 49% |
| Commission | $425 | 41% |
| Size impact | $112 | 11% |

Size impact is negligible at a $229 median trade, which is why venue depth mattered less
than it would for real size, and why the fee and the spread were the only real levers.

## Code audit: four defects found and fixed

Each is now pinned by a test in `tests/test_audit_fixes.py`.

1. **Weekly universe demanded 90 weeks of history instead of 90 days.** Bars-per-day was
   computed with `round()`, which turns weekly bars (0.143 per day) into 1 per day. The
   search reaches the weekly horizon by projecting the daily universe, so the active
   path was unaffected, but any direct weekly call was wrong by a factor of seven.
2. **The breakout strategy chose coins by ticker spelling.** Every coin in a breakout
   scored exactly 1.0, so the tiebreak fell through to alphabetical column order. It now
   ranks by how far price sits above its moving average.
3. **The single-regime test could produce a share above 1.** It divided one regime's
   profit by the sum of positive returns only. It now uses gross gains across regimes and
   is bounded. This gates eligibility, so it could have mislabelled a candidate.
4. **The live agent skipped deposits after an outage.** One deposit was added whenever
   the month changed, so three months offline contributed $100 instead of $300.

Two further defects were found in the new maker model itself and are described above.
The full list, including every bug found during the original build, is in
docs/REFEREE_PROOF.md. 248 tests pass and the referee is locked and hashed.

## What did not change

No exchange keys, no request signing, no order path. The requirements for real capital
are in docs/GOING_LIVE.md and remain unmet: nothing has qualified, and every strategy
tested was stopped by the drawdown brake within a median 128 days.
