"""Futures fair value from the cash index with the cost-of-carry model (no futures data needed).

    F = S * exp((r - q) * T)

S = index level (SPX / NDX), r = risk-free rate, q = index dividend yield, T = years to the active
quarterly futures expiry (third Friday, 09:30 ET settlement).  The traded futures price differs from
fair value by a few points (rate and dividend expectations, supply/demand), so this basis is labeled
as a model value.  It is only used to show futures-space prices on the website; the TradingView
indicator maps levels with your live chart instead.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, time
from typing import Optional

from . import marketcal
from .mapping import FUTURES, SOURCES
from .models import SourceKind

DEFAULT_DIV_YIELD = {"SPX": 0.013, "NDX": 0.007}
CODE_MONTH = {v: k for k, v in marketcal.QUARTER_CODES.items()}


def futures_expiry(market: str, asof: datetime) -> tuple[str, datetime]:
    """Active quarterly contract (post-roll) and its settlement time."""
    root = FUTURES[market].full_size_root
    code = marketcal.front_contract(root, asof.astimezone(marketcal.NY).date())
    month = CODE_MONTH[code[len(root)]]
    digit = int(code[len(root) + 1:])
    year = asof.year - asof.year % 10 + digit
    if year < asof.year:
        year += 10
    return code, datetime.combine(marketcal.quarterly_expiry(year, month), time(9, 30), marketcal.NY)


def carry_fair_value(market: str, source_key: str, spot: float, asof: datetime,
                     rate: Optional[float] = None, div_yield: Optional[float] = None) -> Optional[tuple]:
    """(futures fair value, contract code, rate, div_yield) or None if the source is not a cash index."""
    if SOURCES[source_key].kind != SourceKind.INDEX or not spot:
        return None
    r = rate if rate is not None else float(os.environ.get("GEX_RISK_FREE_RATE", "0.04"))
    q = div_yield if div_yield is not None else float(
        os.environ.get(f"GEX_DIV_YIELD_{source_key}", DEFAULT_DIV_YIELD.get(source_key, 0.0)))
    code, exp = futures_expiry(market, asof)
    t = max(0.0, (exp - asof).total_seconds() / (365.0 * 86400))
    return spot * math.exp((r - q) * t), code, r, q
