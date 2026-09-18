# Referee proof

The referee (`referee/`) is the execution simulator, cost model, validation harness,
regime labeller and integrity manifest. It was written test-first and is locked:
every file is chmod 444, the directory 555, and `referee/MANIFEST.sha256` is verified
by `player.guard.enforce()` at the start of every search, every hourly cycle, every
weekly cycle and the verdict script. A mismatch exits with code 2 and alerts.

Run the proof yourself: `.venv/bin/python -m pytest tests/ -q` (248 tests).

## What is proven, and by which test

| Claim | Test |
|---|---|
| A decision on bar t fills at the open of bar t+1, never at any price of bar t | `test_decision_on_bar_t_fills_at_open_of_t_plus_1`, `test_fill_never_equals_any_price_of_decision_bar` |
| Buys fill above the open, sells below; impact grows with size; illiquid bars cost more; commission 10 bps | `test_referee_costs.py` (5 tests) |
| Net is worse than gross on every trade and in aggregate | `test_net_is_worse_than_gross_on_every_trade` |
| Exposure never exceeds 100%, single asset never exceeds 60% | `test_exposure_never_exceeds_100pct_and_asset_cap` |
| Kill switch halts and flattens; no trades after it | `test_kill_switch_halts_and_flattens` |
| Buy-and-hold benchmark equals the closed form minus friction and is not capped | `test_buy_and_hold_parity_with_closed_form` |
| The bar-by-bar loop ("see bar t, decide, then see t+1") reproduces the vectorized rule exactly | `test_strict_loop_matches_vectorized_targets`, `test_family_matches_strict_loop` (per family) |
| Live agent fills through the same function as the backtester | `test_fill_bar_is_the_same_code_path_the_replay_uses` |
| Every family and grid point is unchanged when future bars are scaled, shuffled or truncated | `test_family_variant_is_causal` (48 cases) |
| The causality battery catches a rule that peeks one bar ahead | `test_causality_battery_catches_a_leaky_rule`, `test_evaluate_rejects_leaky_rule` |
| Higher bars are resampled causally and incomplete trailing bars are dropped | `test_referee_data.py` |
| Regime labels are causal and total | `test_referee_regimes.py` |
| Deflated Sharpe penalises more trials | `test_deflated_sharpe_penalises_many_trials` |
| Tripwire fires on Sharpe > 3, a +15% day, 10 straight winning days, net equity above gross equity, or a bar return above what any asset offered; each is exempt when BTC buy-and-hold itself did the same; silent on ordinary returns | `test_tripwire_*`, `test_single_day_and_streak_exempt_when_benchmark_did_the_same` (8 tests) |
| Risk caps: numpy fast path equals the pandas reference on 2,000 random cases | `test_fast_risk_equals_reference` |
| Walk-forward windows never overlap in their test portions; selection uses train only | `test_walk_forward_windows_do_not_overlap_in_test`, `test_walk_forward_selects_on_train_and_scores_on_test` |
| A one-byte change, an added file, or a removed file in the referee is detected and halts the player | `test_referee_manifest.py`, `test_guard_halts_on_tampered_referee` |
| Live cycle: first cycle decides but cannot fill; second fills at the next bar's open; no new bar means no action; errors are logged and skipped; kill switch alerts | `test_live_agent.py` |
| Promotion needs 8 shared forward weeks, 30 trades each, and +0.3 net Sharpe; failing challengers are demoted; everything is written to lineage | `test_tournament.py` |

## Added for the many-coin universe (2026-09-16)

| Claim | Test |
|---|---|
| Spreads widen as a coin's own liquidity falls, bounded but never free; a thin coin's round trip exceeds 1% | `test_costs_liquidity.py` (6 tests) |
| Universe membership on date D uses only data before D; new listings wait for 90 days of history; dead coins are selectable while they really traded and gone after | `test_universe.py` (7 tests) |
| Binance leveraged tokens (BTCUP, ETHDOWN, XRPBULL) are rejected structurally, while real coins whose names end in those letters (JUP, SYRUP) are kept | `test_universe_integrity.py` (19 tests) |
| Stablecoin and fiat pairs are rejected, so a near-constant 1.00 price cannot masquerade as a zero-risk asset | same |
| A reused ticker is cut at the seam: LUNAUSDT ends at $0.00005 and Terra 2.0's prices are never traded | same |
| A violent but genuine crash is NOT treated as a seam | same |
| Deposits are never counted as profit: flat prices plus deposits give exactly zero profit and a flat return index | `test_replay_deposits.py` (9 tests) |
| The deposit-neutral return index is identical whether deposits are $0 or $500 a month | same |
| Deposits land once per calendar month; profit equals value minus everything paid in | same |
| A delisted holding is force-exited at a worse price than its last close | same |
| The universe gates buying only: a coin that leaves the top 30 can still be sold, so capital is never stranded | same |
| The archive parser handles both millisecond and microsecond timestamps, header rows, and corrupt rows | `test_archive.py` (8 tests) |
| The live agent keys positions by symbol, buys only universe members, always sells what it holds, takes the same monthly deposit, and trips the kill switch on the deposit-neutral drawdown | `test_live_agent.py` (8 tests) |

## Added for venue selection and passive orders (2026-09-16)

| Claim | Test |
|---|---|
| Each venue's fees and MEASURED spread are registered; MEXC has the cheapest fees, Binance the tightest spread | `test_venues_maker.py` |
| Applying one pessimism factor to every venue reverses the taker ranking: Binance's deep books beat MEXC's cheap fee | `test_pessimism_reverses_the_taker_ranking_between_mexc_and_binance` |
| A passive buy fills BELOW the open, a passive sell ABOVE, or not at all | `test_maker_buy_fills_below_the_open_when_the_bar_dips_to_it` and siblings |
| A passive order on a bar that never trades to it is MISSED, and a missed entry is not escalated | `test_maker_run_skips_an_entry_the_market_ran_away_from` |
| A missed EXIT escalates to a taker order on the next bar, so capital is never stranded | `test_an_unfilled_passive_exit_escalates_to_taker` |
| A bar that merely touches the limit does not fill: the queue has to clear | `test_a_mere_touch_of_the_limit_does_not_fill` |
| The friction-free twin always beats the net account, under both order styles | `test_gross_twin_isolates_fees_so_net_can_never_exceed_it` |
| Earned spread is reported as negative slippage, never hidden in the fee line | `test_maker_spread_income_is_reported_separately_from_fees` |

## Audit findings, 2026-09-16

Four defects found by reading the code rather than by a failing test, each now pinned
by one in `tests/test_audit_fixes.py`:

1. **Weekly universe demanded 90 weeks of history.** `universe.build` derived bars per
   day with `round()`, which collapses weekly bars (0.143/day) to 1/day, so a
   90-*day* history requirement became 90 *weeks*. The search reaches the weekly
   horizon by projecting the daily universe, so the active path was unaffected, but
   any direct weekly call was wrong by a factor of seven.
2. **The breakout family broke ties by ticker spelling.** Every coin in a breakout
   scored exactly 1.0, so pandas fell back to column order and holdings depended on
   alphabetical position. It now ranks by distance above the moving average.
3. **The single-regime share could exceed 1.** It divided regime profit by the sum of
   positive returns only. It now divides by gross gains across regimes, bounded in
   [0, 1]. This gates eligibility, so the bug could have mislabelled a candidate.
4. **The live agent skipped deposits after an outage.** It added one deposit whenever
   the month string changed, so three months offline contributed $100 instead of $300.

## Bugs the referee tests caught while being built (so you know they bite)

1. **Benchmark capped by the agent's risk limits.** The predecessor project's "BTC only"
   benchmark was silently 50% BTC because the 50%-per-order cap applied to it. Found by
   the parity test. The referee now exempts benchmarks from caps.
2. **Net-vs-gross compared per bar in percent.** A smaller net equity base makes the
   same dollar gain a bigger percentage, producing false "cost model bypassed" trips.
   The check now compares cumulative levels.
3. **90-day rolling Sharpe as tripwire.** Pure noise reaches a 90-day Sharpe of 4.5
   within 800 days. The tripwire now uses full-sample (≥ 180 days) and rolling 1-year
   Sharpe, both at 3.0.

4. **Stitched net-vs-gross in percentage space.** The same base-effect as (2) reappeared
   when out-of-sample windows were stitched as returns: every candidate "bypassed the
   cost model". Fixed by counting bars where net equity LEVEL exceeds gross LEVEL inside
   each actual run, and adding an asset bound: a long-only spot account cannot earn more
   on a bar than the best of close/prev-close, close/open, open/prev-close across assets.
5. **Absolute plausibility bounds versus real crypto.** On the real 2017-2025 history, BTC
   buy-and-hold posted a rolling 1-year Sharpe above 3 (2020-21), ETH had +16% days, and
   there was an 11-day winning streak. Every honest trend follower inherited these and
   was flagged. The rules stay as specified but are exempt when the benchmark's own
   daily returns show the same thing over the same window or day. A bull run is not a
   bug; the asset bound above is what catches impossible returns.
6. **Speed.** Risk caps built pandas objects per bar: 54 s per hourly candidate with the
   kill switch off. A numpy path proven equal to the reference brought it to under 1 s.
7. **Stranded capital.** The universe mask gated selling as well as buying, so a coin
   that dropped out of the top 30 could never be exited and its capital was frozen for
   the rest of the run. Buying and selling are now gated separately.
8. **An XML parser that lies quietly.** An ElementTree element with no children is
   falsy, so the paging check `elem or default` silently reported "last page" and the
   symbol enumeration stopped early. It now compares against None.
9. **Liquidity computed two ways.** The live agent derived a coin's typical volume
   differently from the backtester, so live fills would not have matched simulated
   ones. Both now call one function, and a test compares their fills to the cent.
10. **Assuming Bitcoin is present.** Regime labels and benchmark exemptions indexed
    `bars["BTCUSDT"]` directly and crashed on any universe without it. They now fall
    back to an equal-weight basket.
11. **A maker model that invented income.** The first passive-order model filled any
    order whose limit the bar merely touched, and priced the friction-free twin at the
    bar's open. Both were wrong in the same direction. The net account beat its own
    friction-free twin on thousands of bars and the net>gross tripwire fired on every
    maker run, which is exactly what that tripwire is for. Fills now require price to
    trade 0.10% beyond the limit so the queue clears, and the twin is priced at the
    same fill minus the commission.

## Known limits (honest, not fixable from free data)

- Universe is BTC and ETH only. Binance's public API serves no delisted pairs, so a
  point-in-time universe with dead tokens is unobtainable; we say so rather than fake it.
- Hourly bars resampled from Binance 1h klines; the "next open" for a 1h decision is the
  first trade of the following hour, a real, tradeable price, but the fill model is a
  model. Real fills will differ; that is what Phase 2's gap measures.
- Impact is computed against the bar's quote volume. On a $1,000 account it is tiny; the
  spread and commission dominate, as they would in reality.
