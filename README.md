# Edge Tournament

Autonomous crypto trading research on this Mac. **Simulation only**: no exchange keys,
no signing code, no order-submission path anywhere in this repository.

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
