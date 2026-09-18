"""German private-investor crypto tax model, §23 EStG, as the rules stood for 2026.

NOT TAX ADVICE and not a filing. This is a model whose only job is to let two
strategies be compared after tax instead of before it, because for a German private
investor that difference can reverse the ranking.

What is modelled:
  * FIFO per asset. The BMF letter of 10 May 2022 directs FIFO where individual units
    cannot be identified, applied per wallet or account.
  * A lot held MORE than one year is exempt on disposal, whatever the gain.
  * A lot held one year or less is taxable at the personal income rate plus the
    solidarity surcharge.
  * The €1,000 figure is a Freigrenze, a THRESHOLD and not an allowance. If the year's
    net short-term gain reaches it, the whole gain is taxable, not merely the excess.
  * Losses offset gains within the same year.

What is NOT modelled, and matters: staking and lending income, the extended holding
period that can apply to lent or staked coins, loss carry-forward between years, church
tax, and the reclassification of very frequent activity as commercial trading
(gewerblicher Handel), which would remove the private exemption altogether and add
trade tax. A bot placing thousands of orders a year is squarely in the territory where
that reclassification gets argued, and it is a question for a Steuerberater, not for me.
"""
from __future__ import annotations
from collections import defaultdict, deque

import pandas as pd

FREIGRENZE = 1000.0          # €, threshold not allowance, for assessment years from 2024
HOLDING_DAYS = 365           # "more than one year" is exempt


def compute(trades, rate: float = 0.42, soli: float = 0.055,
            marks: dict[str, float] | None = None, freigrenze: float = FREIGRENZE,
            as_of: "pd.Timestamp | None" = None) -> dict:
    """`trades` is an iterable of dicts with time, symbol, side, units, fill.
    Positive units are acquisitions, negative are disposals. Returns realised
    short-term and long-term gains, tax due, a per-year breakdown, and any
    unrealised position valued at `marks`."""
    rows = sorted(trades, key=lambda t: pd.Timestamp(t["time"]))
    lots: dict[str, deque] = defaultdict(deque)
    st_by_year: dict[int, float] = defaultdict(float)
    lt_total = 0.0
    n_st = n_lt = 0

    for t in rows:
        sym = t["symbol"]
        units = float(t["units"])
        px = float(t["fill"])
        when = pd.Timestamp(t["time"])
        if units > 0:
            lots[sym].append({"when": when, "units": units, "price": px})
            continue
        remaining = -units
        while remaining > 1e-18 and lots[sym]:
            lot = lots[sym][0]
            take = min(remaining, lot["units"])
            gain = take * (px - lot["price"])
            held_days = (when - lot["when"]).days
            if held_days > HOLDING_DAYS:
                lt_total += gain
                n_lt += 1
            else:
                st_by_year[when.year] += gain
                n_st += 1
            lot["units"] -= take
            remaining -= take
            if lot["units"] <= 1e-18:
                lots[sym].popleft()

    # Freigrenze is a threshold: at or above it, the whole year's gain is taxable.
    taxable = 0.0
    by_year = {}
    for year, gain in sorted(st_by_year.items()):
        due_base = gain if gain >= freigrenze else 0.0
        taxable += max(due_base, 0.0)
        by_year[year] = {"short_term_gain": float(gain),
                         "taxable": float(max(due_base, 0.0)),
                         "below_threshold": bool(0 < gain < freigrenze)}
    tax_due = taxable * rate * (1 + soli)

    unrealised = unrealised_exempt = 0.0
    if marks:
        now = pd.Timestamp(as_of) if as_of is not None else (
            pd.Timestamp(rows[-1]["time"]) if rows else pd.Timestamp.now(tz="UTC"))
        for sym, q in lots.items():
            m = marks.get(sym)
            if m is None:
                continue
            for lot in q:
                g = lot["units"] * (m - lot["price"])
                unrealised += g
                if (now - lot["when"]).days > HOLDING_DAYS:
                    unrealised_exempt += g

    return {"short_term_gain": float(sum(st_by_year.values())),
            "long_term_gain": float(lt_total),
            "taxable_short_term": float(taxable),
            "tax_due": float(tax_due),
            "effective_rate_on_gains": float(tax_due / max(sum(st_by_year.values()) + lt_total, 1e-9)),
            "n_short_term_disposals": n_st, "n_long_term_disposals": n_lt,
            "by_year": by_year,
            "unrealised": float(unrealised), "unrealised_exempt": float(unrealised_exempt)}
