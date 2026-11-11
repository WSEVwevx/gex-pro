"""Futures fair value from the cash index with the cost-of-carry model (no futures data needed).

    F = S * exp((r - q) * T)

S = index level (SPX / NDX), r = risk-free rate, q = index dividend yield, T = years to the expiry of the
quarterly a continuous chart (NQ1!, ES1!) shows (third Friday, 09:30 ET settlement).  The traded futures price differs from
fair value by a few points (rate and dividend expectations, supply/demand), so this basis is labeled
as a model value.  It is only used to show futures-space prices on the website; the TradingView
indicator maps levels with your live chart instead.

The measured basis (futures_ref mode "observed") replaces the model when free 1-minute bars are available:
the median futures / index ratio over the last 15 minutes both traded (Yahoo NQ=F / ^NDX, ES=F / ^GSPC),
the same rule the indicator uses on the chart. Over 20 sessions the 4% carry model sat 22 NQ / 6 ES points
below the market (stress test C1, tools/stress/mapping_accuracy.py).
"""
from __future__ import annotations

import json
import logging
import math
import os
import statistics
import time as _time
import urllib.request
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from . import marketcal
from .mapping import FUTURES, SOURCES
from .models import SourceKind

log = logging.getLogger(__name__)
OBSERVED = {"NDX": ("NQ=F", "^NDX"), "SPX": ("ES=F", "^GSPC")}     # Yahoo's continuous futures roll like NQ1!
MAP_N = 15                       # minutes in the median, as in the indicator
MAX_AGE = timedelta(days=4)      # older than this (a long weekend at most): use the carry model
MAX_MODEL_GAP = 0.003            # further than this from the carry model: misaligned or wrong bars
_cache: dict = {}
DEFAULT_DIV_YIELD = {"SPX": 0.013, "NDX": 0.007, "SPY": 0.013, "QQQ": 0.006}
CODE_MONTH = {v: k for k, v in marketcal.QUARTER_CODES.items()}


def futures_expiry(market: str, asof: datetime) -> tuple[str, datetime]:
    """The quarterly a continuous chart shows (NQ1!: rolls at expiry, not 8 days before) and its settlement time."""
    root = FUTURES[market].full_size_root
    code = marketcal.continuous_contract(root, asof)
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


def _yahoo_1m(sym: str, asof: datetime) -> dict:
    """{minute (epoch s): close} for the 5 days to asof, cached for 2 minutes."""
    hit = _cache.get(sym)
    if hit and _time.monotonic() - hit[0] < 120:
        return hit[1]
    p2 = int(asof.timestamp())
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + sym.replace("^", "%5E").replace("=", "%3D")
           + f"?interval=1m&period1={p2 - 5 * 86400}&period2={p2}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (GEX PRO)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        res = json.loads(r.read())["chart"]["result"][0]
    q = res["indicators"]["quote"][0]["close"]
    out = {t - t % 60: c for t, c in zip(res.get("timestamp") or [], q) if c}
    _cache[sym] = (_time.monotonic(), out)
    return out


def median_ratio(fut: dict, idx: dict, asof: datetime) -> Optional[tuple[float, datetime]]:
    """(median futures / index ratio of the last MAP_N minutes both traded, time of the newest) - restarting
    after a gap of more than an hour, as the indicator does (the basis moves overnight)."""
    end = asof.timestamp()
    ts = sorted(t for t in idx if t in fut and t <= end and idx[t] > 0 and fut[t] > 0)
    if not ts:
        return None
    run = [ts[-1]]
    for t in reversed(ts[:-1]):
        if run[-1] - t > 3600 or len(run) == MAP_N:
            break
        run.append(t)
    return statistics.median(fut[t] / idx[t] for t in run), datetime.fromtimestamp(ts[-1], timezone.utc)


def observed_basis(source_key: str, asof: datetime) -> Optional[tuple[float, datetime, str]]:
    """(ratio, time, label) from free 1-minute bars, or None when they are missing, stale or implausible."""
    if source_key not in OBSERVED:
        return None
    fs, ix = OBSERVED[source_key]
    try:
        got = median_ratio(_yahoo_1m(fs, asof), _yahoo_1m(ix, asof), asof)
    except Exception as e:                       # network, rate limit, format change: the carry model stands in
        log.warning("measured basis unavailable (%s)", e)
        return None
    if not got or asof - got[1] > MAX_AGE or not 0.98 < got[0] < 1.05:
        return None
    # misaligned bars (a shifted clock) give a plausible-looking but wrong ratio: the market's basis never
    # strayed more than 0.17% from the carry model in Oct-Nov 2026 (stress tests C1, E1)
    model = math.exp((float(os.environ.get("GEX_RISK_FREE_RATE", "0.04")) - DEFAULT_DIV_YIELD.get(source_key, 0.0))
                     * max(0.0, (futures_expiry("NQ" if source_key == "NDX" else "ES", asof)[1] - asof).total_seconds() / (365 * 86400)))
    if abs(got[0] / model - 1) > MAX_MODEL_GAP:
        log.warning("measured basis %.6f is %.2f%% from the carry model; not used", got[0], 100 * (got[0] / model - 1))
        return None
    return got[0], got[1], f"measured {fs} / {ix} basis (15-minute median to {got[1].astimezone(marketcal.NY):%m-%d %H:%M} ET)"
