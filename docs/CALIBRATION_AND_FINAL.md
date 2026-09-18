# Calibrating the instrument, and the final position

Dated 2026-09-18. This is the document that should have been written first.

## The question nobody asked for three days

Sixty-nine strategies were rejected by this harness before anyone checked whether it can
detect an edge at all. An instrument that rejects everything, including things that are
true, is not strict. It is broken, and every negative it produced is worthless.

So: inject edges of KNOWN size into the data and see what comes out. The edge is a
return autocorrelation rho, and it is read by a fully causal momentum rule, so nothing
peeks. (A first attempt used a rule that looked one bar ahead; the causality battery
refused to score it, which was the guard doing its job.)

| Injected rho | Theory | Paper | Gross | Net | Confidence | Verdict |
|---|---|---|---|---|---|---|
| 0.00 | 0.00 | +0.26 | -0.09 | -0.20 | 0.00 | correctly rejected |
| 0.01 | 0.15 | +0.54 | +0.20 | +0.10 | 0.01 | rejected |
| 0.02 | 0.30 | +0.71 | +0.38 | +0.27 | 0.04 | rejected |
| 0.03 | 0.46 | +1.01 | +0.67 | +0.57 | 0.14 | rejected |
| 0.04 | 0.61 | +1.28 | +0.94 | +0.84 | 0.32 | rejected |
| **0.06** | 0.91 | +1.85 | +1.53 | **+1.43** | 0.81 | **passes all six gates** |
| 0.08 | 1.22 | +2.47 | +2.15 | +2.05 | 0.99 | passes all six |
| 0.12 | 1.83 | +3.73 | +3.41 | +3.31 | 1.00 | flagged: a sustained Sharpe above 3 |

**The harness works. Its detection floor is a net Sharpe of about +1.43.**

That number is the honest qualification on everything else in this project. The 69
rejections rule out edges at or above that level. A weaker edge could be present and this
instrument would not see it, though it would also not be distinguishable from luck across
69 trials, which is the same statement said twice.

## Three defects the control found immediately

Each had been invisible to 69 consecutive negative results, because a gate that wrongly
rejects looks exactly like a strategy that deserves rejecting.

**1. The win-streak rule fired on noise.** It used a fixed threshold of ten winning days.
But the longest run in a series grows with its length: over 2,000 fair coin flips a
ten-day run appears 62% of the time, and over 5,000 flips 92%. The rule was firing on
pure noise and on genuine edges alike and carried no information whatsoever. It now
scales with sample size and win rate, calibrated by simulation so it fires about once in
a thousand honest runs. All four real bug signatures are still caught.

**2. The rolling Sharpe rule called honest variance a bug.** Any one-year window above 3
was flagged. A strategy whose true Sharpe is 1.2 throws such windows by ordinary
sampling, so genuine, modest edges were being reported as suspected simulator faults. A
window is now judged against the strategy's own long-run level plus sampling error. A
sustained full-sample Sharpe above 3 is still flagged, because for a retail strategy it
genuinely is implausible.

**3. "Gross" never meant what it said, and nearly produced a false headline.** It removed
the commission but still paid the spread, because it reprices the same fills. The seven
forex families showed gross -0.5, and I was one paragraph from telling you their signals
were actively anti-predictive. Then the control showed an informationless rule scores
-0.5 gross on a panel with no edge in it at all. The whole of that -0.5 was spread. Both
engines now carry a genuinely friction-free curve: on it, the same rule reads -0.20 with
no edge present and +3.53 with one. The correct statement is that those families are
indistinguishable from random, not worse than it.

## Both markets, re-run through the corrected gates

**Crypto, 30-coin point-in-time universe, passive execution: 0 of 21.**
Best was daily gated cross-sectional momentum at net Sharpe **+0.62**, confidence 0.16.
Nearly every family now fails on the two gates that carry economic meaning, the
multiple-testing correction and the requirement to earn in more than one regime, rather
than on the broken streak rule.

**Forex, 10 majors, 2005-2026, measured spreads: 0 of 15.**
Best was **+0.01**. Friction here costs 0.025 of Sharpe against 0.6 to 1.3 on crypto, so
the excuse that costs killed it is gone and the answer did not change.

**Fixing the broken gate rescued nothing.** That matters: it means the rejections were
never driven by the defect. Before the fix the tripwire fired on almost every candidate;
after it, it fires on two. The verdicts are identical.

## Where this leaves the numbers

| | Best net Sharpe | Detection floor |
|---|---|---|
| Crypto, 21 variants | +0.62 | +1.43 |
| Forex, 15 variants | +0.01 | +1.43 |

Nothing tested comes within half of the level this instrument can reliably see. That is
the finding, stated with its own limits attached.

## What was not done, deliberately

No grid was widened, no parameter was tuned, no threshold was moved to let something
through. The only thresholds that changed were two that a known-true edge proved were
wrong, and both were changed in the direction that makes the harness MORE likely to pass
a strategy, not less. Neither rescued anything.

The frozen forward-only pre-registrations remain the only test left that can change the
answer, and they report on data that did not exist when they were chosen.
