# Edge Tournament — plan (written before any code)

Score at year end: the simulated net equity curve of a $1,000 BTC/ETH spot
account versus BTC buy-and-hold, plus the backtest-vs-live gap of every champion.

Decisions fixed in the design interview (2026-09-16):
universe: point-in-time top 30 by trailing 30-day dollar volume among every pair
listed at that moment, dead coins included (CORRECTED 2026-09-16: the earlier claim
that delisted pairs were unobtainable was wrong; Binance's data archive at
data.binance.vision retains them, 735 USDT pairs in total) · bars 4h, 1d, 1w · alerts via ntfy.sh · kill switch halts trading while the tournament continues ·
promotion needs net Sharpe +0.3 over 8 shared forward weeks and 30 trades each ·
referee isolated by package + chmod + SHA-256 manifest · search space = rule
families with wider grids across horizons · fresh repo, referee pieces ported from
Edge Lab and re-proven · tripwire Sharpe > 3 / +15% day / 10 straight wins /
net > gross · regimes from BTC 200-day trend, 30-day vol terciles, chop filter.

## 0. Correction log

**2026-09-16, universe.** The first build restricted to BTC and ETH on the stated
grounds that a survivorship-free universe was unobtainable from free data. That was
false. The REST price endpoint serves only currently-listed pairs, but the public
archive retains delisted ones: LUNAUSDT's fall from $68 to $0.00005 is present, as is
FTTUSDT and BCCUSDT. Restricting to two correlated majors also gave the test almost no
breadth (they co-move about 80% of the time, so the effective sample was near one
asset) and contradicted the plan's own argument for hunting in less efficient corners.
Rebuilt on the point-in-time universe.

**2026-09-16, deposits.** The account now takes $1,000 at the start plus $100 every
month. Contributed capital is tracked separately from investment return; profit is
account value minus everything paid in; Sharpe, drawdown and the kill switch are all
computed on a deposit-neutral index so a fresh deposit can never disguise a loss. The
Bitcoin benchmark receives the identical deposit schedule.

**2026-09-16, data integrity.** Two hazards found and gated: Binance leveraged tokens
(BTCUP, ETHDOWN and 46 others) are derivatives, not spot, and show 100,000x one-day
"gains" at redenomination; and Binance reused the LUNAUSDT ticker for Terra 2.0, which
unhandled is a 177,399x single-bar gain for anyone holding the dead token. Leveraged
tokens and stablecoin/fiat pairs are excluded structurally, and every series is cut at
its first implausible upward seam.

## 1. Repository shape: referee vs player

```
edge-tournament/
  referee/            READ-ONLY. chmod a-w. Hashes in referee/MANIFEST.sha256.
    data.py           Binance 1h candles → 4h/1d/1w resampled causally. Local parquet.
    replay.py         Bar-by-bar engine. Strategy gets bars[:t]; fill at open[t+1].
    costs.py          0.10% taker, 0.05% half-spread, sqrt impact vs bar quote volume,
                      thinning multiplier when bar volume < 20% of its 30-bar median.
    risk.py           Max order 50%, max asset 60%, total ≤ 100%, kill at 25% DD.
    validate.py       Walk-forward runner, deflated Sharpe, min-trade gate, regime
                      segmentation, look-ahead battery, tripwire.
    regimes.py        Causal regime labels (fixed definitions).
    manifest.py       Startup checksum; any mismatch → halt + alert.
  player/             The strategy agent. May only import referee's public API.
    families.py       Rule families + parameter grids (the search space).
    search.py         Phase 1 search: enumerate candidates → referee.validate →
                      ranked shortlist → freeze champion.
    tournament.py     Phase 2: weekly re-search, ONE challenger, promotion logic.
  live/
    agent.py          Hourly cycle: fetch → fill pending → mark → decide → record.
    notify.py         ntfy.sh POST. Weekly digest + immediate alerts.
    dashboard.py      Static HTML from SQLite.
  tests/              Referee proof: look-ahead, fills, costs, risk, manifest, tripwire.
  state/              SQLite (equity, trades, decisions, journal, lineage, errors),
                      frozen champion files (champion_YYYYMMDD_HHMMSS.json, immutable).
  launchd/            com.edgetournament.live (hourly), .search (Sunday 03:00).
```

Enforcement, not convention: `player/` and `live/` run with a guard that checks
`referee/` hashes at import time; referee files are chmod 444 and the directory
555; the player never receives a file handle to the referee, only function calls.
Strategies are data (family name + parameters) that the referee executes, so the
player has no place to put a fill price or a cost.

## 2. Referee, proven first (before any strategy exists)

Tests that must pass before `player/` is written, then re-run every cycle:
- Causality: for every family and parameter, signal[:t] unchanged when bars after t
  are shuffled, scaled by noise, or truncated. Three cut points per bar size.
- Fill timing: a decision on bar t fills at open[t+1], never at any price in bar t.
  Test asserts the fill's reference price equals the next bar's open.
- Pessimism: buys fill above open, sells below; net < gross on every trade; impact
  grows with order size; thinning multiplier engages on low-volume bars.
- Risk: exposure never > 100%, per-asset ≤ 60%, kill switch halts and flattens.
- Tripwire: a planted bug (fill at close, zero costs) is caught by net > gross and
  Sharpe > 3 on a known-good strategy.
- Manifest: modifying one byte of any referee file makes startup halt.
- Benchmark parity: buy-and-hold through the referee equals the closed-form
  result within cost.

## 3. Phase 1: search (hours)

- Candidates: rule families (SMA/EMA trend, Donchian breakout, RSI mean reversion,
  vol-targeted trend, BTC/ETH relative momentum, time-of-day/day-of-week filters as
  overlays) × bar size {1h, 4h, 1d, 1w} × parameter grids. Target ≈ 1,000–2,000
  candidates. Count is recorded; it is the N in the deflated Sharpe.
- Walk-forward per candidate: train 365d / test 91d rolled, on data up to the freeze
  date. Reported: gross and net return, Sharpe, deflated Sharpe (Bailey & López de
  Prado, N = candidates tried, skew/kurtosis of returns), max DD, trades, per-regime
  net Sharpe, fraction of OOS windows positive.
- Gates: ≥ 100 OOS trades total; net deflated Sharpe > 0; not single-regime
  (a strategy earning > 80% of its OOS profit in one regime is labelled so and
  ranked below multi-regime ones); tripwire clean.
- Output: `state/shortlist_<ts>.json` ranked, and `state/champion_<ts>.json` frozen
  (family, params, bar size, freeze timestamp, data end date, backtest expectation).
  Frozen files are chmod 444 and never edited.

## 4. Phase 2: live tournament (months)

- Hourly launchd cycle: pull closed bars, fill the pending order at the new bar's
  open, mark, apply risk, compute the champion's decision on bars[:now], store
  decision + reasoning, journal. Errors logged, cycle skipped, next hour recovers.
- Weekly (Sunday 03:00): re-run Phase 1 on data through now. The top candidate that
  is not the incumbent becomes the ONE challenger and starts paper-trading in
  parallel (shadow, no effect on the score). Promotion when, on the forward window
  since the challenger's freeze: both ≥ 8 weeks and ≥ 30 trades, challenger net
  Sharpe ≥ incumbent + 0.3. Then the challenger becomes champion, the old one is
  demoted, both with reasoning rows in `lineage`.
- Kill switch at 25% DD from peak: trading halts, alert sent, tournament continues;
  trading resumes only under a newly promoted champion.
- Tripwire on live and shadow equity every cycle; trip → halt that strategy, alert.
- Weekly digest via ntfy: equity vs BTC, champion, trades, per-regime, backtest
  expectation vs live-to-date, what the journal says it learned.

## 5. Phase 3: verdict

`scripts/verdict.py` produces docs/VERDICT.md: equity vs BTC B&H net, champion
lineage table, and for every champion the backtest-expected Sharpe vs realised
forward Sharpe (the gap). If a champion has a forward-tested edge, a document on
what real capital would need; nothing else is built.

## 6. Out of scope, on purpose

No API keys, no order routing, no leverage or perps, no ML, no altcoins.
