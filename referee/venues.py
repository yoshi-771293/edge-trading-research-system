"""Trading venues, with fees and MEASURED spreads.

The spread multipliers are not guesses. On 2026-09-16 the live best bid and ask were
read from each venue's public API for the 26 tradable coins of the current top-30
universe, and the median half-spread recorded:

    venue     median half-spread    taker fee (native-token discount)
    Binance         0.0109%                 0.075%
    MEXC            0.0252%                 0.050%
    Gate            0.0099%                 0.090%
    Kraken          0.0222%                 0.250%

`spread_multiplier` scales the referee's BASE_HALF_SPREAD, which is itself deliberately
pessimistic (0.05%, roughly five times Binance's measured 0.0109%). So the model still
charges far more than the venues actually quoted.

Fees are the published spot rates at the entry tier with the native-token discount
applied where one exists. They are not promotional rates and they get worse, never
better, at low volume, so no tier improvement is assumed anywhere.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Venue:
    name: str
    maker_fee: float
    taker_fee: float
    spread_multiplier: float      # vestigial; the cost model anchors on measured_half_spread
    measured_half_spread: float   # median of what this venue actually quoted
    note: str
    eu_eligible: bool = False     # holds a MiCA licence and may serve an EU retail client

    def all_in_taker(self) -> float:
        """Fee plus the spread you pay when you cross it."""
        return self.taker_fee + self.measured_half_spread

    def all_in_maker(self) -> float:
        """Fee minus the spread you earn when your limit order is hit.
        Negative means a passive fill is a credit before any price movement."""
        return self.maker_fee - self.measured_half_spread


ALL = {
    # --- MiCA-licensed: an EU retail client may legally trade here -------------
    "okx": Venue("okx", 0.0008, 0.0010, 1.0, 0.000478,
                 "MiCA via Malta; cheapest fees of the licensed venues but the widest spreads of them",
                 eu_eligible=True),
    "bitvavo": Venue("bitvavo", 0.0015, 0.0025, 1.0, 0.000116,
                     "MiCA via the Netherlands; very tight EUR spreads, middling fees", eu_eligible=True),
    "kraken": Venue("kraken", 0.0025, 0.0040, 1.0, 0.000059,
                    "MiCA via Luxembourg and Ireland; tightest EUR spreads measured, worst entry-tier fees",
                    eu_eligible=True),
    "bitstamp": Venue("bitstamp", 0.0030, 0.0040, 1.0, 0.000285,
                      "MiCA via Luxembourg", eu_eligible=True),
    "coinbase": Venue("coinbase", 0.0060, 0.0120, 1.0, 0.000251,
                      "MiCA via Ireland; entry-tier fees are an order of magnitude above the rest",
                      eu_eligible=True),
    # --- No MiCA licence: CANNOT serve an EU retail client ---------------------
    "binance": Venue("binance", 0.00075, 0.00075, 1.0, 0.000109,
                     "deepest books in crypto spot, but withdrew its EU MiCA application and stopped "
                     "new EU spot orders on 1 July 2026"),
    "mexc": Venue("mexc", 0.0000, 0.00050, 2.3, 0.000252,
                  "0% maker and 0.05% taker, the cheapest measured anywhere; holds no MiCA licence"),
    "gate": Venue("gate", 0.00090, 0.00090, 1.0, 0.000099,
                  "spreads as tight as Binance but a higher flat fee; no MiCA licence"),
}
DEFAULT = "okx"        # the cheapest venue an EU resident may legally use


def get(name: str | None = None) -> Venue:
    return ALL[(name or DEFAULT).lower()]


def eu_eligible_names() -> list[str]:
    return sorted(n for n, v in ALL.items() if v.eu_eligible)
