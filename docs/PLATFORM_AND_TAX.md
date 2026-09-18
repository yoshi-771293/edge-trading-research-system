# Platform, tax, and the live gateway

Researched and built 16 September 2026. **Not tax or investment advice.** The tax figures
below come from a model I wrote and tested, not from a Steuerberater, and the rules they
encode are under political review.

## Binance cannot serve you

Binance withdrew its EU MiCA application and **stopped accepting new spot orders,
deposits and sign-ups from EU residents on 1 July 2026**. Withdrawals remain open.
That was eleven weeks ago. It never held a BaFin licence either; the German application
was pulled in 2023 ahead of an expected rejection.

MEXC, the venue that won my cost analysis, holds no MiCA authorisation either.

So both venues I spent the day optimising for are unavailable to you. That is my error:
I measured fees before checking who may legally take your order.

## What you can actually use, measured live today

Live best bid and ask read from each venue's own API, eight major coins, EUR pairs where
they exist.

| MiCA-licensed venue | Maker | Taker | Median half-spread | All-in taker | All-in maker |
|---|---|---|---|---|---|
| **OKX** (Malta) | 0.08% | 0.10% | 0.0478% | **0.148%** | **0.032%** |
| Bitvavo (Netherlands) | 0.15% | 0.25% | 0.0116% | 0.262% | 0.138% |
| Kraken (Luxembourg/Ireland) | 0.25% | 0.40% | 0.0059% | 0.406% | 0.244% |
| Bitstamp (Luxembourg) | 0.30% | 0.40% | 0.0285% | 0.428% | 0.272% |
| Coinbase (Ireland) | 0.60% | 1.20% | 0.0251% | 1.225% | 0.575% |
| ~~Binance~~ no MiCA | 0.075% | 0.075% | 0.0109% | 0.086% | 0.064% |
| ~~MEXC~~ no MiCA | 0.000% | 0.050% | 0.0252% | 0.075% | **-0.025%** |

**OKX is the answer**, and it makes the problem worse. Passive execution on MEXC was a
credit of 0.025% per side. On OKX it is a cost of 0.032%. The single lever that doubled
the best strategy's result is largely unavailable to you, and Kraken or Coinbase would
be four to eighteen times more expensive again.

## The tax rule works against trading, not for it

You want to hold on the platform and withdraw a year later tax-free. The one-year rule
is real: crypto held **more than twelve months** by a private individual is exempt on
disposal under §23 EStG, whatever the gain. It still applies for the 2026 tax year, with
reform debated for 2027 at the earliest.

But the exemption attaches to each **lot**, not to the account, and every sale is a
disposal that restarts the clock. A bot that rebalances daily never holds anything for a
year. Within twelve months, gains are added to your income at up to 45% plus the
solidarity surcharge. The €1,000 figure is a Freigrenze, a threshold and not an
allowance: cross it and the entire gain becomes taxable, not just the excess.

Modelled on the real backtest, FIFO per asset, 42% plus solidarity surcharge:

| | Bot (daily trend basket) | Bitcoin, same deposits |
|---|---|---|
| Paid in | $7,800 | $7,800 |
| Account value | $22,066 | $16,531 |
| Realised inside 12 months | all of it | nothing |
| Realised after 12 months, exempt | nothing | nothing |
| Unrealised, exempt if sold now | $0 | $8,736 |
| **Tax due** | **$6,466** | **$0** |
| **After tax** | **$15,601** | **$16,531** |

Pre-tax the bot is ahead by $5,536. **After tax it is behind by $930.** German tax law
turns its only win into a loss, because it converted every gain into a short-term one
while buy-and-hold kept them all exempt.

There is a further risk I cannot size for you. Thousands of orders a year is the
territory where the tax office may argue commercial trading, which removes the private
exemption altogether and adds trade tax. That is a question for a Steuerberater before
any money moves, not a question for me.

## The live gateway, as requested

Built in `live/broker.py`, with real OKX order construction and HMAC request signing.
Shipped locked. Fourteen tests cover the interlocks.

Every one of these refuses by default:

| State | Result |
|---|---|
| As shipped | **Refused**, the gateway is not enabled |
| Enabled, nothing qualified | **Refused**, no strategy has passed its gates |
| Enabled, qualified, Binance from Germany | **Refused**, no MiCA authorisation |
| Enabled, qualified, brake on | **Refused**, drawdown brake |
| Enabled, qualified, OKX, brake off | Would trade |

Also enforced: dry run is the default and never touches the network; every order is
post-only, because the cost case depends entirely on being passive; orders are capped
twice, absolutely at $250 and at 35% of equity; credentials are read from the
environment at the moment of use and never stored, printed or logged, and a test proves
no secret reaches the order log. There is no withdrawal, transfer or fund-movement
function anywhere in the module, and a test asserts that no such function name exists.

To arm it you would set `EDGE_OKX_KEY`, `EDGE_OKX_SECRET` and `EDGE_OKX_PASSPHRASE` in
your environment, with a trading-only, withdrawal-disabled API key, then pass
`Config(enabled=True, dry_run=False)`. I have not created a key, and I will not handle
one. It stays locked until a strategy qualifies, and none has.
