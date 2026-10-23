"""Rule-based strategies built on the expected-move band and the gamma regime, backtested.

The rules are fixed here before any result is looked at and use only what was known when the trade
is placed (previous close, the vol index close, the regime). Every question a bar cannot answer is
resolved against the trader: when one bar holds both a stop and a target, the stop comes first, and a
trade filled inside a bar can be stopped in that bar but cannot reach its target there.

Three tests per strategy:
  daily    decades of daily bars (S&P 500 since 1991, Nasdaq-100 since 2010), each day one bar
  hourly   about three years of hourly bars (Yahoo), so intraday orders are walked hour by hour; shown
           next to the daily test over the same days, to see how much the bar size changes the answer
  live     the track record's sessions, with GEX PRO's own band and regime

Regime: in history a PROXY, "calm" when the vol index closed at or below its median of the previous
252 sessions (dealers more often long gamma), "stressed" above it; in the live test, GEX PRO's
POSITIVE / NEGATIVE regime.
Band: em = previous close x IV / sqrt(252), one session per trading day, weekends included. (Counting
calendar days charges three days of option premium for a weekend that moves like one: an artifact
that makes any weekend option sale look brilliant.)
P&L: index points after a round-trip cost, and in em units ("R") so years and indexes compare.
Option strategies are priced with Black-Scholes at the vol index level, with no skew and a 10% spread
cost: a model of the premium, not real quotes.
"""
from __future__ import annotations

import math
from typing import Callable, Optional

COST = {"SPX": 0.5, "NDX": 2.0}           # index points per round trip (about 2 ticks of ES / 8 ticks of NQ)
OPTION_COST = 0.10                       # share of the premium lost to spreads on option strategies
REGIME_LOOKBACK = 252
SESSIONS_PER_YEAR = 252


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def option_pair(ref: float, em: float, k: float = 1.0) -> float:
    """Call + put struck at ref +/- k em, Black-Scholes at total vol em/ref (r = q = 0, no skew)."""
    v = em / ref
    out = 0.0
    for strike, call in ((ref + k * em, True), (ref - k * em, False)):
        d1 = (math.log(ref / strike) + 0.5 * v * v) / v
        d2 = d1 - v
        out += ref * _ncdf(d1) - strike * _ncdf(d2) if call else strike * _ncdf(-d2) - ref * _ncdf(-d1)
    return out


# ---------------------------------------------------------------------------- order simulation
def trade(path: list, side: int, entry: Optional[float], kind: str, stop: float, target: Optional[float] = None) -> Optional[float]:
    """Walk one session's bars (o, h, l, c). side +1 long, -1 short. kind: "open" (filled at the first
    bar's open), "limit" or "stop" (a resting order at `entry`). Returns points made, or None if never filled."""
    fill, start = None, 0
    if kind != "open":
        for j, (o, h, l, c) in enumerate(path):
            if kind == "limit" and (l <= entry if side > 0 else h >= entry):
                fill = min(o, entry) if side > 0 else max(o, entry)
            elif kind == "stop" and (h >= entry if side > 0 else l <= entry):
                fill = max(o, entry) if side > 0 else min(o, entry)
            if fill is not None:
                if (l <= stop) if side > 0 else (h >= stop):          # stopped inside the fill bar (worst case)
                    return min(0.0, side * (stop - fill))           # filled through the stop: out at the fill
                start = j + 1
                break
        if fill is None:
            return None
    else:
        fill = path[0][0]
    for o, h, l, c in path[start:]:
        if (o <= stop) if side > 0 else (o >= stop):                    # opened through the stop
            return side * (o - fill)
        if (l <= stop) if side > 0 else (h >= stop):
            return side * (stop - fill)
        if target is not None and ((h >= target) if side > 0 else (l <= target)):
            return side * ((max(o, target) if side > 0 else min(o, target)) - fill)
    return side * (path[-1][3] - fill)


# ---------------------------------------------------------------------------- the rules
# rule(days, i) -> list of P&Ls in index points before costs, for trades decided on day i.
# days[i] = {date, date_prev, ref (previous close), em, o, h, l, c, path [(o, h, l, c), ...], regime}
def band_fade(days, i) -> list:
    """Resting limit orders at the band edges, stop 1 em further, out at the close."""
    d = days[i]
    ref, em, o, p = d["ref"], d["em"], d["o"], d["path"]
    out = []
    if o > ref - 2 * em:
        out.append(trade(p, +1, ref - em, "limit", ref - 2 * em))
    if o < ref + 2 * em:
        out.append(trade(p, -1, ref + em, "limit", ref + 2 * em))
    return [x for x in out if x is not None]


def band_breakout(days, i) -> list:
    """Stop orders at the band edges in the direction of the break, stop back at the previous close."""
    d = days[i]
    ref, em, p = d["ref"], d["em"], d["path"]
    out = [trade(p, +1, ref + em, "stop", ref), trade(p, -1, ref - em, "stop", ref)]
    return [x for x in out if x is not None]


def gap_fade(days, i) -> list:
    """Opens 0.5-1.5 em from the previous close: fade at the open toward it, stop 0.75 em further away."""
    d = days[i]
    ref, em, o = d["ref"], d["em"], d["o"]
    g = o - ref
    if not 0.5 * em <= abs(g) <= 1.5 * em:
        return []
    side = -1 if g > 0 else 1
    return [trade(d["path"], side, None, "open", o - side * 0.75 * em, ref)]


def gap_and_go(days, i) -> list:
    """Opens at least 0.5 em away: go with the gap at the open, stop at the previous close."""
    d = days[i]
    g = d["o"] - d["ref"]
    if abs(g) < 0.5 * d["em"]:
        return []
    side = 1 if g > 0 else -1
    return [trade(d["path"], side, None, "open", d["ref"])]


def short_strangle(days, i) -> list:
    """Sell the 1-day +/-1 em strangle at the previous close, settle at the close."""
    d = days[i]
    ref, em, c = d["ref"], d["em"], d["c"]
    prem = option_pair(ref, em) * (1 - OPTION_COST)
    return [prem - max(0.0, c - (ref + em)) - max(0.0, (ref - em) - c)]


def iron_condor(days, i) -> list:
    """The strangle with wings bought at +/-2 em, so no day can lose more than 1 em minus the credit."""
    d = days[i]
    ref, em, c = d["ref"], d["em"], d["c"]
    credit = (option_pair(ref, em) - option_pair(ref, em, 2.0)) * (1 - OPTION_COST)
    return [credit - min(em, max(0.0, c - (ref + em))) - min(em, max(0.0, (ref - em) - c))]


def close_reversal(days, i) -> list:
    """A close outside the band: take the other side at the close, out at the next close."""
    d = days[i]
    if i + 1 >= len(days) or days[i + 1]["date_prev"] != d["date"]:
        return []
    nxt = days[i + 1]["c"]
    if d["c"] < d["ref"] - d["em"]:
        return [nxt - d["c"]]
    if d["c"] > d["ref"] + d["em"]:
        return [d["c"] - nxt]
    return []


def close_follow(days, i) -> list:
    """A close outside the band: go with it at the close, out at the next close."""
    return [-x for x in close_reversal(days, i)]


STRATEGIES = [
    {"id": "iron_condor", "name": "1-day iron condor", "regime": "calm", "rule": iron_condor, "options": True, "intraday": False},
    {"id": "short_strangle", "name": "1-day strangle sale", "regime": "calm", "rule": short_strangle, "options": True, "intraday": False},
    {"id": "close_reversal", "name": "Close-outside-band reversal", "regime": "calm", "rule": close_reversal, "options": False, "intraday": False},
    {"id": "close_follow", "name": "Close-outside-band follow-through", "regime": "stressed", "rule": close_follow, "options": False, "intraday": False},
    {"id": "band_fade", "name": "Band-edge fade", "regime": "calm", "rule": band_fade, "options": False, "intraday": True},
    {"id": "gap_fade", "name": "Gap fade", "regime": "calm", "rule": gap_fade, "options": False, "intraday": True},
    {"id": "band_breakout", "name": "Band breakout", "regime": "stressed", "rule": band_breakout, "options": False, "intraday": True},
    {"id": "gap_and_go", "name": "Gap and go", "regime": "stressed", "rule": gap_and_go, "options": False, "intraday": True},
]


# ---------------------------------------------------------------------------- statistics
def stats(trades: list) -> dict:
    """trades: (date, points, R)."""
    n = len(trades)
    if not n:
        return {"n": 0}
    r = [t[2] for t in trades]
    pts = [t[1] for t in trades]
    mean = sum(r) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in r) / (n - 1)) if n > 1 else 0.0
    wins, losses = sum(x for x in pts if x > 0), -sum(x for x in pts if x < 0)
    cum = peak = dd = 0.0
    for x in r:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return {"n": n, "win": round(sum(1 for x in pts if x > 0) / n, 4), "avg_r": round(mean, 4),
            "avg_pts": round(sum(pts) / n, 2), "total_r": round(sum(r), 2), "total_pts": round(sum(pts), 1),
            "pf": round(wins / losses, 3) if losses else None, "max_dd_r": round(dd, 2),
            "t": round(mean / sd * math.sqrt(n), 2) if sd else None, "worst_r": round(min(r), 2), "best_r": round(max(r), 2)}


def verdict(s: dict, halves: list) -> str:
    """Fixed before results: 'holds up' needs 30+ trades, t >= 2 and a positive average in both halves, after costs."""
    if not s.get("n") or s["n"] < 30:
        return "too few trades"
    if s["avg_r"] <= 0:
        return "does not work"
    if (s.get("t") or 0) >= 2 and all(h.get("n") and h["avg_r"] > 0 for h in halves):
        return "holds up"
    return "mixed"


def _curve(trades: list, max_points: int = 300) -> list:
    cum, out = 0.0, []
    step = max(1, len(trades) // max_points)
    for i, (d, _, r) in enumerate(trades):
        cum += r
        if i % step == 0 or i == len(trades) - 1:
            out.append([d, round(cum, 2)])
    return out


def run(days: list, rule: Callable, cost: float, regime: str = "any") -> list:
    out = []
    for i, d in enumerate(days):
        if regime != "any" and d.get("regime") != regime:
            continue
        for p in rule(days, i):
            p -= cost
            out.append((d["date"], round(p, 3), p / d["em"]))
    return out


def build_days(bars: dict, vol: dict, until: Optional[str] = None, hourly: Optional[dict] = None) -> list:
    """The day records the rules read. With `hourly`, only the days that have hourly bars, each with its path."""
    ds = sorted(x for x in bars if until is None or x <= until)
    days, past = [], []
    for prev, d in zip(ds, ds[1:]):
        v = vol.get(prev)
        if not v:
            continue
        past.append(v)
        if len(past) <= REGIME_LOOKBACK:
            continue
        window = sorted(past[-REGIME_LOOKBACK - 1:-1])
        med = window[len(window) // 2]
        ref, b = bars[prev]["close"], bars[d]
        path = [(b["open"], b["high"], b["low"], b["close"])]
        if hourly is not None:
            if not hourly.get(d):
                continue
            path = hourly[d]
        days.append({"date": d, "date_prev": prev, "ref": ref, "em": ref * v / 100 / math.sqrt(SESSIONS_PER_YEAR),
                     "o": path[0][0], "h": max(x[1] for x in path), "l": min(x[2] for x in path), "c": path[-1][3],
                     "path": path, "regime": "calm" if v <= med else "stressed"})
    return days


def history(underlying: str, bars: dict, vol: dict, until: Optional[str] = None, hourly: Optional[dict] = None) -> dict:
    days = build_days(bars, vol, until)
    if not days:
        return {}
    hdays = build_days(bars, vol, until, hourly) if hourly else []
    hset = {d["date"] for d in hdays}
    mid = days[len(days) // 2]["date"]
    last3 = f"{int(days[-1]['date'][:4]) - 3}{days[-1]['date'][4:]}"
    out = {"start": days[0]["date"], "end": days[-1]["date"], "sessions": len(days), "cost_pts": COST.get(underlying, 0.0),
           "calm_share": round(sum(d["regime"] == "calm" for d in days) / len(days), 3),
           "hourly_period": [hdays[0]["date"], hdays[-1]["date"]] if hdays else None, "strategies": {}}
    for s in STRATEGIES:
        cost = 0.0 if s["options"] else COST.get(underlying, 0.0)
        on = run(days, s["rule"], cost, s["regime"])
        halves = [stats([t for t in on if t[0] < mid]), stats([t for t in on if t[0] >= mid])]
        st = stats(on)
        r = {"stats": st, "unfiltered": stats(run(days, s["rule"], cost)), "halves": halves, "split": mid,
             "last_3y": stats([t for t in on if t[0] >= last3]), "verdict": verdict(st, halves), "curve": _curve(on)}
        if s["intraday"] and hdays:
            # daily bars force the worst order of high and low on these rules, so the verdict comes from
            # walking the hourly bars instead (fewer years, fairer fills)
            ho = run(hdays, s["rule"], cost, s["regime"])
            hmid = hdays[len(hdays) // 2]["date"]
            hh = [stats([t for t in ho if t[0] < hmid]), stats([t for t in ho if t[0] >= hmid])]
            r["hourly"] = {"stats": stats(ho), "halves": hh, "split": hmid, "curve": _curve(ho),
                           "unfiltered": stats(run(hdays, s["rule"], cost)), "daily_same_days": stats([t for t in on if t[0] in hset])}
            r["verdict"], r["verdict_basis"] = verdict(r["hourly"]["stats"], hh), "hourly"
        else:
            r["verdict_basis"] = "daily"
        out["strategies"][s["id"]] = r
    return out


def live(sessions: list) -> dict:
    """The same rules on the track record: GEX PRO's own band and regime (POSITIVE = calm, NEGATIVE =
    stressed) from each frozen plan, on that session's daily bar."""
    regime = {"POSITIVE": "calm", "NEGATIVE": "stressed"}
    by: dict = {s["id"]: [] for s in STRATEGIES}
    for m in sorted({x["market"] for x in sessions}):
        days = []
        for x in sorted((x for x in sessions if x["market"] == m), key=lambda s: s["session"]):
            p, o = x.get("plan"), x.get("outcome")
            if not p or not o or not p.get("em"):
                continue
            days.append({"date": x["session"], "date_prev": days[-1]["date"] if days else None, "ref": p["ref"], "em": p["em"],
                         "o": o["open"], "h": o["high"], "l": o["low"], "c": o["close"],
                         "path": [(o["open"], o["high"], o["low"], o["close"])],
                         "regime": regime.get(p.get("regime"), "other"), "underlying": p.get("underlying")})
        und = days[0]["underlying"] if days else ""
        for s in STRATEGIES:
            cost = 0.0 if s["options"] else COST.get(und or "", 0.0)
            by[s["id"]] += [(f"{d} {m}", pts, r) for d, pts, r in run(days, s["rule"], cost, s["regime"])]
    return {k: dict(stats(sorted(v)), trades=[{"session": t[0], "pts": t[1], "r": round(t[2], 3)} for t in sorted(v)[-20:]])
            for k, v in by.items()}
