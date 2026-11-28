"""Chain helpers shared by the option providers: the standard series, the index / ETF pairs, the rate and dividend
yields used when gamma is computed, and the ETF merge.

ETF options merged into the index chain (SPY into SPX, QQQ into NDX)
* The ETF tracks the index at ratio r = index price / ETF price (~10 for SPY, ~41 for QQQ).
* Each ETF option becomes an index-equivalent contract: strike x r (exact, for the math; grouped
  with the nearest listed index strike for levels), open interest and volume / r.  BSM gamma scales as 1/r when price and
  strike both scale by r, so OI/r x gamma/r x multiplier x (r S)^2 equals the ETF option's own
  dollar gamma: GEX, walls, max pain and put/call ratios stay consistent in index contracts.
* IV is kept (the ETF's own); bid/ask are dropped because they are not in index units.
"""
from __future__ import annotations

import bisect
import os
from dataclasses import replace
from datetime import datetime
from typing import Optional

from .. import pricing
from ..models import OptionContract, OptionType, Quality

ETF_FOR = {"SPX": "SPY", "NDX": "QQQ"}
# The standard series only. OCC also lists e.g. B1SPY (an adjusted SPY series: a different deliverable, so its
# gamma is not SPY's) and SPXO (Wednesday special-settlement SPX); counting them as standard contracts was wrong,
# and B1SPY even became the paste's ETF label (stress test B1, 2026-11-10).
STANDARD_ROOTS = {"SPX": {"SPX", "SPXW"}, "NDX": {"NDX", "NDXP"}, "SPY": {"SPY"}, "QQQ": {"QQQ"}}
# index / ETF price ratios outside these mean one of the two prices is wrong (SPY ~ SPX/10, QQQ ~ NDX/41)
ETF_RATIO = {"SPX": (9.5, 10.5), "NDX": (38.0, 45.0)}


def risk_free_rate() -> float:
    return float(os.environ.get("GEX_RISK_FREE_RATE", "0.04"))


def dividend_yield(source_key: str) -> float:
    """Continuous dividend yield used when gamma is recomputed (GEX_DIV_YIELD_SPX etc. override)."""
    from ..basis import DEFAULT_DIV_YIELD
    return float(os.environ.get(f"GEX_DIV_YIELD_{source_key}", DEFAULT_DIV_YIELD.get(source_key, 0.0)))


def merge_etf(index_contracts: list[OptionContract], etf_contracts: list[OptionContract], ratio: float,
              index_key: str, index_multiplier: float, etf_spot: Optional[float] = None,
              asof: Optional[datetime] = None, etf_q: float = 0.0) -> list[OptionContract]:
    """ETF options -> index-equivalent contracts (see module notes). The exact converted strike is used for
    all math; `group_strike` (the nearest listed index strike, within 0.75 x the usual spacing) only groups
    levels, walls and max-pain candidates. An ETF option without an IV gets one solved from its own
    bid/ask first (IV is unchanged by the scaling)."""
    strikes = sorted({c.strike for c in index_contracts})
    gaps = sorted(b - a for a, b in zip(strikes, strikes[1:]) if b > a)
    tol = 0.75 * (gaps[len(gaps) // 2] if gaps else 1.0)
    out: list[OptionContract] = []
    for c in etf_contracts:
        # no IV, or a placeholder above 500% (stress test B1: the engine then dropped it, and with it the quote
        # that could have given a real one): solve from the bid / ask, in the ETF's own terms
        if (c.iv is None or c.iv > 5.0) and c.mid is not None and etf_spot and asof:
            yrs = (c.expiration - asof).total_seconds() / (365.0 * 86400)
            iv = None
            if yrs > 0:
                iv = pricing.implied_vol(c.mid, etf_spot, c.strike, yrs, risk_free_rate(), etf_q,
                                         c.option_type == OptionType.CALL, pricing.QUOTE_TOL, pricing.QUOTE_MAX_VOL_ERR)
            c = replace(c, iv=iv if iv and iv <= 5.0 else None)
        k = c.strike * ratio
        i = bisect.bisect_left(strikes, k)
        near = min((strikes[j] for j in (i - 1, i) if 0 <= j < len(strikes)), key=lambda s: abs(s - k), default=None)
        out.append(replace(c, symbol=f"{c.symbol}@{index_key}", strike=k,
                           group_strike=near if near is not None and abs(near - k) <= tol else round(k, 2),
                           multiplier=index_multiplier,
                           open_interest=None if c.open_interest is None else c.open_interest / ratio,
                           volume=None if c.volume is None else c.volume / ratio,
                           bid=None, ask=None, last=None, gamma=None, delta=None, greeks_quality=Quality.MISSING,
                           div_yield=etf_q))
    return out
