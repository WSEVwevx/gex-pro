"""Daily bias: a transparent, rule-based reading of options positioning for the session.

NOT a forecast. Each factor is a widely used positioning heuristic with a fixed weight; the website
shows every factor, its score and its reason, so the result can be checked rather than trusted blindly.

Factors (score > 0 leans up, < 0 leans down)
  gamma side     price vs zero gamma in daily expected moves (sigma):  > +0.3 positive gamma (range day),
                 < -0.3 negative gamma (trend day), otherwise a pivot day. Sets the day TYPE, not direction.
  magnet         positive gamma: pull toward the absolute-gamma / largest +GEX strike   weight 1.0 (0.5 otherwise)
  charm          sign of dealer hedge flow from time decay (strongest into the close)    weight 1.0
  walls          within 0.25 sigma under the call wall -0.5; within 0.25 sigma over the put wall +0.5
  vanna          hedge flow if IV eases (positive gamma) or rises (negative gamma)        weight 0.5
  0DTE max pain  late-day pull toward today's max pain when within one expected move      weight up to 0.5
Bias: score >= +0.75 bullish, <= -0.75 bearish, else neutral. Confidence from |score|; a pivot day is
always low confidence.

Path: from "now" (or the 09:30 open before the session) to a base-case close target, eased per day type,
plus a +/-1 sigma cone that widens with the square root of remaining time.
"""
from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from typing import Optional

from . import marketcal

OPEN = time(9, 30)


def _p(v) -> Optional[float]:
    return v.get("price") if isinstance(v, dict) else v


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def session_window(now: datetime) -> tuple[datetime, datetime, datetime, bool]:
    """(session open, session close, path start, live?) for the current or next RTH session (ET)."""
    t = now.astimezone(marketcal.NY)
    d = t.date()
    if not marketcal.is_trading_day(d) or t.time() >= marketcal.rth_close(d):
        d += timedelta(days=1)
        while not marketcal.is_trading_day(d):
            d += timedelta(days=1)
    o = datetime.combine(d, OPEN, marketcal.NY)
    c = datetime.combine(d, marketcal.rth_close(d), marketcal.NY)
    live = o <= t < c
    return o, c, (t if live else o), live


def compute(L: dict, now: datetime, step_min: int = 10) -> Optional[dict]:
    if not L or L.get("status") == "UNAVAILABLE":
        return None
    ex = L.get("extras") or {}
    em = ex.get("expected_move") or {}
    emd = em.get("daily_points_fut") or em.get("daily_points")
    ref = L.get("futures_equiv_of_ref") or L.get("ref_price")
    if not emd or not ref or emd <= 0:
        return None
    zg, cw, pw = _p(L.get("zero_gamma")), _p(L.get("call_wall")), _p(L.get("put_wall"))
    ag, mpos = _p(L.get("abs_gamma")), _p(L.get("max_positive"))
    g = ex.get("greeks") or {}
    factors: list[dict] = []

    def add(name: str, score: float, why: str):
        factors.append({"name": name, "score": round(score, 2), "why": why})

    # ---- day type from the gamma side
    sig = (ref - zg) / emd if zg is not None else None
    if sig is None:
        side = {"POSITIVE": "positive", "NEGATIVE": "negative"}.get(L.get("regime"), "pivot")
    else:
        side = "positive" if sig > 0.3 else "negative" if sig < -0.3 else "pivot"
    add("Gamma side", 0.0,
        ("price is %.1f expected moves %s zero gamma: " % (abs(sig), "above" if sig >= 0 else "below") if sig is not None else "")
        + {"positive": "positive gamma, so dealer hedging tends to dampen moves (range day)",
           "negative": "negative gamma, so dealer hedging tends to add to moves (trend day)",
           "pivot": "right at the flip, so the day type depends on which side of zero gamma price holds"}[side])

    # ---- directional factors
    magnet = ag if ag is not None and abs(ag - ref) <= emd else (mpos if mpos is not None and abs(mpos - ref) <= emd else None)
    if magnet is not None:
        w = 1.0 if side == "positive" else 0.5
        add("Magnet strike", w * _clip((magnet - ref) / (0.5 * emd)),
            f"the biggest gamma strike {magnet:,.2f} is {abs(magnet - ref):,.1f} pts {'above' if magnet >= ref else 'below'}; "
            + ("in positive gamma price tends to drift toward it" if side == "positive" else "its pull is weaker outside positive gamma"))
    flow = g.get("charm_flow_usd_per_day")
    if flow:
        add("Charm flow", 1.0 if flow > 0 else -1.0,
            f"time decay alone has dealers {'buying' if flow > 0 else 'selling'} about ${abs(flow) / 1e6:,.0f}M of exposure today, mostly in the last 2 hours")
    if cw is not None and 0 <= cw - ref < 0.25 * emd:
        add("Call wall overhead", -0.5, f"price is only {cw - ref:,.1f} pts under the call wall {cw:,.2f}; rallies often stall there")
    if pw is not None and 0 <= ref - pw < 0.25 * emd:
        add("Put wall below", 0.5, f"price is only {ref - pw:,.1f} pts over the put wall {pw:,.2f}; dips often find support there")
    v = g.get("vanna_usd_per_vol_pt")
    if v:
        # hedge flow for IV +1pt is -v; positive gamma days usually see IV ease (flow +v), negative gamma days see it rise (flow -v)
        f = v if side == "positive" else (-v if side == "negative" else 0.0)
        if f:
            add("Vanna", 0.5 if f > 0 else -0.5,
                f"if implied vol {'eases' if side == 'positive' else 'rises'} as it usually does on a {side}-gamma day, "
                f"dealers would {'buy' if f > 0 else 'sell'} to rebalance")
    near = ex.get("nearest") or {}
    mps = ex.get("max_pain") or []
    if near.get("label") == "0DTE" and mps and mps[0].get("price") is not None:
        mp = mps[0]["price"]
        if abs(mp - ref) <= emd:
            add("0DTE max pain", 0.5 * _clip((mp - ref) / (0.5 * emd)),
                f"today's max pain {mp:,.2f} is {abs(mp - ref):,.1f} pts {'above' if mp >= ref else 'below'}; expiring options can pull price toward it late in the day")

    score = sum(f["score"] for f in factors)
    bias = "Bullish" if score >= 0.75 else "Bearish" if score <= -0.75 else "Neutral"
    conf = "Low" if side == "pivot" or abs(score) < 1.25 else ("Medium" if abs(score) < 2.0 else "High")

    # ---- expected range and base-case close target
    if side == "positive":
        lo, hi = ref - 0.7 * emd, ref + 0.7 * emd
        if pw is not None and lo < pw < ref:
            lo = pw
        if cw is not None and ref < cw < hi:
            hi = cw
        target = magnet if magnet is not None else ref + _clip(score / 3) * 0.4 * emd
        day = "Range / mean reversion"
    elif side == "negative":
        lo = ref - emd * (1.2 if bias != "Bullish" else 0.8)
        hi = ref + emd * (1.2 if bias != "Bearish" else 0.8)
        target = ref + (0.8 * emd if bias == "Bullish" else -0.8 * emd if bias == "Bearish" else 0.0)
        day = "Trend / expansion"
    else:
        lo, hi = ref - 0.9 * emd, ref + 0.9 * emd
        target = zg if zg is not None else ref
        day = "Pivot around zero gamma"
    # the base case must agree with the stated bias: a bullish read never draws a falling path, and vice versa
    lean = 1 if bias == "Bullish" else -1 if bias == "Bearish" else 0
    if lean and (target - ref) * lean <= 0:
        target = ref + lean * min(abs(score) / 3.0, 1.0) * 0.4 * emd
    target = min(max(target, lo), hi)

    # ---- illustrative path and cone over the session
    o, c, start, live = session_window(now)
    total = (c - o).total_seconds() / 60.0
    m0 = (start - o).total_seconds() / 60.0
    span = max(1.0, total - m0)
    path, cone = [], []
    m = m0
    while True:
        u = (m - m0) / span
        if side == "positive":
            e = u * u * (3 - 2 * u)                 # smooth drift that settles on the magnet into the close
        elif side == "negative":
            e = u ** 1.5                            # slow start, accelerating move
        else:
            e = 1 - (1 - u) ** 2                    # quick test of zero gamma, then holds
        path.append([round(m), round(ref + (target - ref) * e, 2)])
        w = emd * math.sqrt(max(0.0, m - m0) / total)
        cone.append([round(m), round(ref - w, 2), round(ref + w, 2)])
        if m >= total:
            break
        m = min(total, m + step_min)

    lead = {"Bullish": "leans higher", "Bearish": "leans lower", "Neutral": "has no clear direction"}[bias]
    summary = (f"{day}. Positioning {lead} ({conf.lower()} confidence): base case {target:,.2f} by the close, "
               f"expected range {lo:,.2f} to {hi:,.2f}.")
    if side == "pivot" and zg is not None:
        summary += f" Holding above {zg:,.2f} favours a calmer, range-bound day; losing it favours a trending move."
    return {"bias": bias, "confidence": conf, "score": round(score, 2), "day_type": day, "side": side,
            "sigma_from_zero_gamma": None if sig is None else round(sig, 2), "target": round(target, 2),
            "range": [round(lo, 2), round(hi, 2)], "ref": ref, "expected_move": emd, "factors": factors,
            "summary": summary, "session": {"open": o.isoformat(), "close": c.isoformat(), "live": live,
                                             "minutes": round(total), "start_minute": round(m0)},
            "path": path, "cone": cone,
            "levels": {k: v for k, v in (("Call wall", cw), ("Put wall", pw), ("Zero gamma", zg), ("Abs gamma", ag),
                                         ("Max pain 0DTE", mps[0]["price"] if near.get("label") == "0DTE" and mps else None))
                       if v is not None}}
