"""Point-in-time tradable universe, free of survivorship bias.

At each rebalance date the universe is the top N coins by trailing median daily
dollar volume among every coin that was LISTED AND TRADING at that moment. Coins
that later collapsed or were delisted are present for as long as they really traded,
which is the only way a backtest can be punished for holding them into the grave.

Causality: membership on date D uses bars strictly BEFORE D. Nothing else.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


BARS_PER_DAY = {"1h": 24.0, "4h": 6.0, "1d": 1.0, "1w": 1 / 7}


def bars_per_day(index: pd.DatetimeIndex) -> float:
    secs = pd.Series(index).diff().dt.total_seconds().median()
    return (86400.0 / secs) if secs and secs > 0 else 1.0


def master_index(bars: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    idx = None
    for d in bars.values():
        idx = d.index if idx is None else idx.union(d.index)
    return pd.DatetimeIndex([] if idx is None else idx).sort_values()


def field(bars: dict[str, pd.DataFrame], name: str, index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    idx = master_index(bars) if index is None else index
    return pd.DataFrame({s: d[name].reindex(idx) for s, d in bars.items()}, index=idx)


def availability(bars: dict[str, pd.DataFrame], index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """True where the coin actually had a bar: it could be traded then."""
    return field(bars, "close", index).notna()


def last_bar(bars: dict[str, pd.DataFrame]) -> pd.Series:
    return pd.Series({s: (d.index[-1] if len(d) else pd.NaT) for s, d in bars.items()})


def first_bar(bars: dict[str, pd.DataFrame]) -> pd.Series:
    return pd.Series({s: (d.index[0] if len(d) else pd.NaT) for s, d in bars.items()})


def build(bars: dict[str, pd.DataFrame], top_n: int = 30, min_history_days: int = 90,
          volume_window: int = 30, index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Boolean membership frame (bars x symbols). Row D is decided from data < D."""
    idx = master_index(bars) if index is None else index
    if len(idx) == 0:
        return pd.DataFrame(dtype=bool)
    qv = field(bars, "quote_volume", idx)
    av = qv.notna()
    # NOTE: round() here used to collapse weekly bars (0.143/day) to 1/day, which made
    # the weekly universe demand 90 WEEKS of history instead of 90 days.
    bpd = bars_per_day(idx)
    win = max(int(round(volume_window * bpd)), 1)
    hist_bars = max(int(round(min_history_days * bpd)), 1)
    # shift(1): decisions on bar D see only bars strictly before D
    liq = qv.rolling(win, min_periods=max(win // 3, 1)).median().shift(1)
    age = av.cumsum().shift(1)
    eligible = av & (liq > 0) & (age >= hist_bars)
    ranked = liq.where(eligible).rank(axis=1, ascending=False, method="first")
    return (ranked <= top_n).fillna(False)


def median_daily_qv(bars: dict[str, pd.DataFrame], volume_window: int = 30,
                    index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Trailing median DAILY dollar volume per coin, for the cost model. Causal."""
    idx = master_index(bars) if index is None else index
    qv = field(bars, "quote_volume", idx)
    bpd = bars_per_day(idx)
    win = max(int(round(volume_window * bpd)), 1)
    return (qv.rolling(win, min_periods=max(win // 3, 1)).median().shift(1) * bpd)


def liquidity(bars: dict[str, pd.DataFrame], index: pd.DatetimeIndex, symbols: list[str] | None = None,
              bar_window: int = 30, day_window: int = 30) -> tuple[pd.DataFrame, pd.DataFrame]:
    """THE one definition of liquidity, used by the backtester AND the live agent.

    median_bar_qv : typical dollar volume of a bar like this one (thin-bar detection)
    median_daily_qv: typical DAILY dollar volume of the coin (spread width)
    Both are shifted one bar, so neither can see the bar being traded.
    """
    syms = symbols or list(bars)
    bpd = bars_per_day(index)
    qv = pd.DataFrame({s: (bars[s]["quote_volume"].reindex(index) if s in bars else np.nan) for s in syms},
                      index=index)
    med_bar = qv.rolling(bar_window, min_periods=1).median().shift(1)
    win = max(int(day_window * bpd), 1)
    med_day = qv.rolling(win, min_periods=max(win // 3, 1)).median().shift(1) * bpd
    return med_bar.fillna(0.0), med_day


# ---------------------------------------------------------------------------
# Data-integrity gate: spot only, and no trading across a ticker seam.
# ---------------------------------------------------------------------------
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")
STABLE_OR_FIAT = {
    "USDC", "BUSD", "TUSD", "FDUSD", "DAI", "USDP", "PAX", "SUSD", "USDS", "USD1",
    "USDE", "USDTB", "XUSD", "AEUR", "EURI", "EUR", "GBP", "AUD", "TRY", "BRL",
    "RUB", "UAH", "NGN", "IDRT", "BIDR", "VAI", "ARS", "ZAR", "PLN", "RON", "CZK",
    "JPY", "MXN", "COP", "DOGS",
}
SEAM_UP_FACTOR = 5.0          # a >5x single-bar rise in a liquid coin is a data event


def is_spot_symbol(symbol: str, all_symbols, quote: str = "USDT") -> bool:
    """Reject Binance leveraged tokens and stablecoin/fiat pairs.

    Leveraged tokens are detected structurally: strip UP/DOWN/BULL/BEAR and, if the
    remaining stem is itself a traded symbol, this is the derivative of that stem.
    That keeps genuine coins whose names merely end in those letters (JUP, SYRUP).
    """
    if not symbol.endswith(quote):
        return False
    base = symbol[: -len(quote)]
    if not base or base in STABLE_OR_FIAT:
        return False
    stems = {s[: -len(quote)] for s in all_symbols if s.endswith(quote)}
    for suf in LEVERAGED_SUFFIXES:
        if base.endswith(suf) and len(base) > len(suf) and base[: -len(suf)] in stems:
            return False
    return True


def first_seam(close: pd.Series) -> pd.Timestamp | None:
    """First bar whose rise is too large to be a market move, i.e. the ticker was
    reused for a different token or the token was redenominated. A violent genuine
    CRASH is not a seam: crypto really does fall 99% in days."""
    r = close.pct_change()
    hits = r.index[r > (SEAM_UP_FACTOR - 1.0)]
    return hits[0] if len(hits) else None


def clean(bars: dict[str, pd.DataFrame], all_symbols, min_bars: int = 120) -> dict[str, pd.DataFrame]:
    """Drop non-spot and stablecoin pairs; cut every series at its first seam; drop
    anything left too short to carry an indicator."""
    out = {}
    for s, d in bars.items():
        if not is_spot_symbol(s, all_symbols):
            continue
        seam = first_seam(d["close"])
        if seam is not None:
            d = d[d.index < seam]
        if len(d) >= min_bars:
            out[s] = d
    return out
