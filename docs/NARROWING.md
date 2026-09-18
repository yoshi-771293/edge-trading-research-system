# On searching fewer variants

You asked whether narrowing the search would let something qualify. Arithmetically yes,
and that is the problem. Here is the evidence, then what I did instead.

## The same strategy, the same data, a different story

The best candidate is daily gated cross-sectional momentum, net Sharpe +0.79 over 2,093
days. Its confidence score depends entirely on how many variants I claim to have tried:

| Variants claimed | Confidence | Verdict |
|---|---|---|
| 87 (what I actually tried) | 0.28 | fails |
| 40 | 0.38 | fails |
| 20 | 0.50 | fails |
| 10 | 0.62 | **qualifies** |
| 7 | 0.69 | **qualifies** |
| 3 | 0.85 | **qualifies** |
| 1 | 0.97 | **qualifies** |

Nothing about the strategy changes down that column. Not one trade, not one return. Only
the account of how many ideas were tested before this one was picked.

## What narrowing does to pure noise

2,000 runs. Each run generates 87 strategies with **no edge whatsoever**, random returns
at realistic crypto volatility over 5.7 years. Take the best of the 87 and judge it.

| How it is judged | Share of edgeless winners that "qualify" |
|---|---|
| Honestly, against the 87 tried | 42% |
| Narrowed afterwards to 7 | **100%** |

Best-of-87 luck alone produces a median Sharpe of +1.00. There is nothing in those
numbers to find, and the narrowed test finds something every single time.

That 42% figure is worth pausing on, because it is a finding about my own gate. A
confidence threshold of 0.50 means "more likely than not", which is a coin flip, not a
standard of proof. The bar I have been applying is generous, and the best candidate
fails a generous bar.

## What I did instead

A pre-registered set, frozen to a read-only file today, with two disciplines that make it
defensible rather than cherry-picked.

- **Four variants**: time-series trend and cross-sectional momentum, the two families with
  the strongest published prior, on daily and weekly bars.
- **The parameter is chosen by a rule, not by a result.** Each family takes the middle
  value of its grid by position. Not the winner. For the record those are trend basket at
  (100, 5) and cross-sectional momentum at (60, 3), and neither was the best performer in
  any run.
- **The 4-hour horizon is dropped** on a cost argument that predates every result:
  friction scales with trade count, and 4-hour trading generated 16,000 trades against
  weekly's 660.
- **The bar is raised to 0.95**, the conventional level, instead of the coin flip.

And the part that makes it honest rather than theatre: **this set is contaminated with
respect to history and may never be scored against it.** I chose it knowing how the
87-variant run turned out. The code enforces this. Any attempt to score it on data before
17 September 2026 raises an error rather than returning a number.

So its verdict comes from data that does not exist yet, at a rate of about four variants
per year of evidence. That is slow, and slow is the honest speed. The alternative is a
number I could have handed you in ten minutes that would have meant nothing.

## The one thing that has not changed

Even at zero friction the best strategy earns 100% of its profit while Bitcoin is above
its 200-day average. That is a bull-market bet, not an edge, and no amount of narrowing
the search fixes it. It remains the most damning result in this project.
