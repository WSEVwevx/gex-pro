"""The GEX live table: exposure by strike and expiration, for the website's strike ladder.

For every strike near price (grouped into evenly spaced rows) and every expiration in the basket:
  gex   net gamma exposure, same units and dealer signs as the rest of GEX PRO ($ per 1% move)
  dex   net dealer delta exposure in $: sign x OI x delta x multiplier x price, with the same
        positioning signs as GEX (dealers long calls, short puts under the conventional model)
  oi    call and put open interest (index-equivalent contracts; ETF options are already converted)
  vol   call and put volume today (same units)

Prices are in the options' underlying (index points); the website maps them to futures.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

from . import marketcal, pricing
from .models import OptionType

WINDOW = 0.035                # rows cover price +/- 3.5%
TARGET_ROWS = 60
NICE = [1, 2, 2.5, 5, 10, 20, 25, 40, 50, 100, 200, 250, 500]
MAX_EXPIRIES = 12


def band_width(spot: float) -> float:
    """Price-band width: 40 points on NDX, 10 on SPX (about 60 rows over +/-3.5%)."""
    span = 2 * WINDOW * spot
    return min(NICE, key=lambda w: abs(span / w - TARGET_ROWS))


def _monthly(d: date) -> bool:
    """Third Friday of the month: the standard monthly expiration."""
    return d.weekday() == 4 and 15 <= d.day <= 21


def pick_expirations(all_exps: list) -> list:
    """Like a trader's expiry strip: the 3 nearest, then every Friday and every monthly, up to MAX_EXPIRIES."""
    out = list(all_exps[:3])
    for e in all_exps[3:]:
        if len(out) >= MAX_EXPIRIES:
            break
        d = e.date()
        if d.weekday() == 4 or _monthly(d):
            out.append(e)
    return sorted(out)


def build_ladder(res, snap) -> Optional[dict]:
    """res: engine GexResult, snap: the ChainSnapshot it came from."""
    s = res.spot
    if not res.rows or not s or not math.isfinite(s):
        return None
    w = band_width(s)
    exps = pick_expirations(sorted({r.contract.expiration for r in res.rows}))
    idx = {e: i for i, e in enumerate(exps)}
    other = len(exps)                                   # everything else in the basket, pooled
    tot = [[0.0, 0.0] for _ in range(other + 1)]
    q = snap.div_yield
    cells: dict[float, dict[int, list]] = {}
    for r in res.rows:
        c = r.contract
        i = idx.get(c.expiration, other)
        is_call = c.option_type == OptionType.CALL
        delta = c.delta
        if (delta is None or not math.isfinite(delta)) and r.iv:
            delta = pricing.bsm_delta(s, c.strike, r.t_years, snap.rate, q, r.iv, is_call)
        dex = r.sign * c.open_interest * (delta or 0.0) * c.multiplier * s
        tot[i][0] += r.exposure
        tot[i][1] += dex
        k = round(c.level_strike / w) * w
        if abs(k - s) > WINDOW * s:
            continue
        cell = cells.setdefault(k, {}).setdefault(i, [0.0] * 6)
        cell[0] += r.exposure
        cell[1] += dex
        cell[2 if is_call else 3] += c.open_interest or 0.0
        cell[4 if is_call else 5] += c.volume or 0.0
    expirations = []
    for i, e in enumerate(exps):
        ny = e.astimezone(marketcal.NY)
        d = ny.date()
        am = ny.hour < 12                               # AM-settled (SPX / NDX monthlies settle at the open)
        tag = ("M" if _monthly(d) else "") + (" AM" if am else "")
        expirations.append({"date": d.isoformat(), "dte": round((e - res.asof).total_seconds() / 86400, 1), "tag": tag,
                            "net": round(tot[i][0]), "dex": round(tot[i][1])})
    if any(v for v in tot[other]):
        expirations.append({"date": "other", "dte": None, "tag": "", "net": round(tot[other][0]), "dex": round(tot[other][1])})
    rows = [{"k": round(k, 2), "x": {str(i): [round(v[0]), round(v[1]), round(v[2], 1), round(v[3], 1), round(v[4], 1), round(v[5], 1)]
                                    for i, v in sorted(by.items())}}
            for k, by in sorted(cells.items(), reverse=True)]
    return {"width": w, "spot": s, "unit": res.unit, "expirations": expirations, "rows": rows,
            "fields": ["gex", "dex", "call_oi", "put_oi", "call_vol", "put_vol"]}


HEAT_WINDOW = 0.04            # the heatmap keeps price +/- 4% per snapshot


def heat_profile(res) -> Optional[dict]:
    """Net GEX by price band for the heatmap, saved with every snapshot so history can be drawn later.

    {"base": first band centre, "w": band width, "v": [net $M per band, ...]} in index points; the bands are
    the same as the live table's rows (40 points on NDX, 10 on SPX)."""
    s = res.spot
    if not res.by_strike or not s or not math.isfinite(s):
        return None
    w = band_width(s)
    lo, hi = math.floor(s * (1 - HEAT_WINDOW) / w), math.ceil(s * (1 + HEAT_WINDOW) / w)
    v = [0.0] * (hi - lo + 1)
    for k, d in res.by_strike.items():
        i = round(k / w) - lo
        if 0 <= i < len(v):
            v[i] += d["net"]
    return {"base": lo * w, "w": w, "v": [round(x / 1e6, 1) for x in v]}
