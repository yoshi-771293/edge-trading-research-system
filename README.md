# Edge Trading Research System

A research harness whose job is to **disprove** trading edges, cheaply and with receipts.
Across three days it tested 69 pre-registered strategy variants over two markets and
twenty-one years, and rejected every one of them.

**Simulation only.** There are no exchange credentials anywhere in this repository. The
live order gateway exists but is interlocked off and has no withdrawal path.

## The result

| | Best net Sharpe | Eligible | Instrument's detection floor |
|---|---|---|---|
| Crypto, 30-coin point-in-time universe, 21 variants | +0.62 | 0 | +1.43 |
| Forex, 10 majors 2005-2026, 15 variants | +0.01 | 0 | +1.43 |

The detection floor is measured, not assumed: injecting an edge of known size shows this
harness reliably sees anything from a net Sharpe of about +1.43 upward. Nothing tested
came within half of that.

The most informative single finding is that forex friction costs 0.025 of Sharpe against
0.6 to 1.3 on crypto, and every strategy still loses. With costs effectively removed, the
answer did not change, so the failure is the signals rather than the fees.

## Start here

- [docs/CALIBRATION_AND_FINAL.md](docs/CALIBRATION_AND_FINAL.md) — does the instrument
  work at all, and the three defects that question exposed. **Read this first.**
- [docs/FOREX_VERDICT.md](docs/FOREX_VERDICT.md) — the cleanest negative, with friction
  near zero.
- [docs/NARROWING.md](docs/NARROWING.md) — why searching fewer variants after the fact
  turns 87 edgeless strategies into a "winner" 100% of the time.
- [docs/REFEREE_PROOF.md](docs/REFEREE_PROOF.md) — every claim the simulator makes, and
  the test that pins it, including eleven bugs it caught in its own construction.
- [docs/PLATFORM_AND_TAX.md](docs/PLATFORM_AND_TAX.md) — measured venue costs, and why
  German tax law rewards holding over trading.

The account starts with $1,000 and receives $100 every month. Profit is account value
minus everything paid in, never the raw balance. The benchmark is the same money, with
the same monthly top-ups on the same days, put into Bitcoin instead.

- Plain-English report: `state/dashboard.html`, rebuilt every hour
- Plan and correction log: [docs/PLAN.md](docs/PLAN.md)
- Why the instrument can be trusted: [docs/REFEREE_PROOF.md](docs/REFEREE_PROOF.md)
- Year-end verdict: `scripts/verdict.py` writes docs/VERDICT.md

## Universe

Point-in-time top 30 by trailing 30-day dollar volume, chosen from every USDT pair
that was listed at that moment. Coins that later collapsed or were delisted are
present for as long as they really traded, so the test can be punished for holding
them into the grave. 735 pairs are archived; 251 have entered the top 30 at some point.
Leveraged tokens and stablecoin pairs are excluded, and any series is cut where a
ticker was reused for a different token.

## Referee and player

`referee/` is the instrument: the replay engine, cost model, risk limits, universe
construction, validation harness and regime labels. It is chmod-locked and every file
is hashed in `referee/MANIFEST.sha256`, verified at the start of every run. A mismatch
halts the process and alerts. `player/` proposes strategies and may only call the
referee's public functions; strategies are data, not code that can touch execution.

## Commands

```bash
.venv/bin/python -m pytest tests -q                              # the proof (217 tests)
.venv/bin/python -c "from player import search; search.run(monthly_deposit=100)"
.venv/bin/python -m live.run bootstrap                           # seed champion from the frozen file
.venv/bin/python -m live.run hourly                              # one live cycle + dashboard
.venv/bin/python -m live.run weekly                              # judge, propose, send digest
.venv/bin/python scripts/verdict.py                              # year-end verdict
```

## Schedule

`com.edgetournament.hourly` runs at minute 3 of every hour; `com.edgetournament.weekly`
runs Sundays at 03:30. Logs are in `state/`. Remove with
`launchctl unload ~/Library/LaunchAgents/com.edgetournament.*.plist`.

## Alerts

`state/notify.json` holds the ntfy topic. The weekly digest and every kill-switch,
anomaly or integrity alert go to the ntfy app on the phone, and tapping one opens
Claude Code.

## Editing the referee

Not during a tournament. If you must: `manifest.unlock`, change it, run the tests,
`manifest.write`, `manifest.lock`, and add a line to the correction log in
docs/REFEREE_PROOF.md saying what changed and why.
