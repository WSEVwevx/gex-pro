"""The futures strategy lab: rules built on options data, tested on ES (S&P 500) and NQ (Nasdaq-100).

Every rule is fixed here before it is run and is never tuned afterwards. A rule is LISTED as a
strategy only when it passes every test below; the others stay in the research log with the reason
they failed. Nothing is fitted to the results.

Inputs, all free and all derived from options:
  expected move   em = previous close x VIX (ES) or VXN (NQ) / sqrt(252)
  term structure  VIX / VIX3M (contango below 1 = calm, above 1 = stress) and VIX9D / VIX (front end)
  intraday VIX    hourly VIX closes (Yahoo)
  GEX PRO levels  the track record's frozen pre-open plans (regime, walls, zero gamma, abs gamma)

Execution: futures-style, one position at a time, a round trip costs 0.5 points (ES) or 2 points (NQ).
Intraday rules walk hourly bars; when one hour touches both the stop and the target, the stop counts.

The bar (fixed before running):
  intraday rules  last 3 years of hourly bars: 30+ trades, a profit after costs (in $ and in R), t >= 2 and both halves
                  profitable, on ES and on NQ. (Free hourly history only reaches back about 3 years.)
  swing rules     the same 3 years: a profit in both halves on ES and on NQ; then OUT OF SAMPLE on
                  2010 to the start of that window: both halves profitable and t >= 1.65 on ES and on NQ.
  GEX rules       the track record's own sessions (forward only): 30+ trades, t >= 2, both halves
                  profitable, on ES and NQ together. Until then they are evidence, not strategies.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Callable, Optional

VERSION = 2                                   # bump when rules or the simulator change: cached results are rebuilt
COST = {"SPX": 0.5, "NDX": 2.0}               # index points per round trip
POINT_VALUE = {"SPX": 50.0, "NDX": 20.0}      # $ per point: ES, NQ
FUTURE = {"SPX": "ES", "NDX": "NQ"}
SESSIONS_PER_YEAR = 252
WINDOW_YEARS = 3
OOS_START = "2010-01-01"


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


# ---------------------------------------------------------------------------- intraday rules: (day) -> [points]
def last_half_hour_momentum(d) -> list:
    """Price at 15:30 more than 0.25 em from the previous close: trade the last half hour in that direction."""
    p = d["path"]
    move = p[-1][0] - d["ref"]
    if abs(move) < 0.25 * d["em"]:
        return []
    side = 1 if move > 0 else -1
    return [side * (p[-1][3] - p[-1][0])]


def _orb(d) -> list:
    p = d["path"]
    hi, lo = p[0][1], p[0][2]
    rest = p[1:]
    up, dn = trade(rest, +1, hi, "stop", lo), trade(rest, -1, lo, "stop", hi)
    for o, h, l, c in rest:                                  # one-cancels-other; both in one hour = the loser
        if h >= hi and l <= lo:
            return [min(x for x in (up, dn) if x is not None)]
        if h >= hi:
            return [up]
        if l <= lo:
            return [dn]
    return []


def orb_front_stress(d) -> list:
    """VIX9D above VIX the evening before: trade a break of the first hour's range, stop at the other side."""
    return _orb(d) if d["front_prev"] > 1.0 else []


def orb_calm(d) -> list:
    """VIX9D at least 10% under VIX: the same first-hour breakout."""
    return _orb(d) if d["front_prev"] <= 0.9 else []


def first_hour_fade(d) -> list:
    """Contango (VIX/VIX3M < 0.9) and a first hour that ran 0.5 em from the previous close: fade it at 10:30,
    target the previous close, stop 0.5 em past the first hour's extreme."""
    if d["ts_prev"] >= 0.9:
        return []
    p = d["path"]
    move = p[0][3] - d["ref"]
    if abs(move) < 0.5 * d["em"]:
        return []
    side = -1 if move > 0 else 1
    ext = p[0][1] if side < 0 else p[0][2]
    return [trade(p[1:], side, None, "open", ext - side * 0.5 * d["em"], d["ref"])]


def vanna_afternoon(d) -> list:
    """VIX at 13:00 down 3%+ from yesterday's close: long from 13:30 to the close; up 5%+: short."""
    v = d["vixh"].get("12:00")                               # the 12:00 bar closes at 13:00
    if not v or len(d["path"]) < 7:
        return []
    ch = v / d["vix_prev"] - 1
    side = 1 if ch <= -0.03 else -1 if ch >= 0.05 else 0
    return [side * (d["path"][-1][3] - d["path"][4][0])] if side else []


def band_fade_contango(d) -> list:
    """Contango (VIX/VIX3M < 0.9): resting orders at +/-1 em, stop at +/-1.75 em, out at the close."""
    if d["ts_prev"] >= 0.9:
        return []
    ref, em, p = d["ref"], d["em"], d["path"]
    out = [trade(p, +1, ref - em, "limit", ref - 1.75 * em), trade(p, -1, ref + em, "limit", ref + 1.75 * em)]
    return [x for x in out if x is not None]


# ---------------------------------------------------------------------------- swing rules: signal at day i's close
# (signal(D, i) -> bool, entry "close" | "next_open", exit after `hold` sessions at the close, or at the next open)
def contango(D, i):       return D[i]["ts"] < 0.95
def backwardation(D, i):  return D[i]["ts"] > 1.0
def dip_contango(D, i):   return D[i]["ts"] < 1.0 and D[i]["c"] < D[i]["ref"] - D[i]["em"]
def strength(D, i):       return D[i]["ts"] < 0.95 and D[i]["c"] > D[i]["ref"] + D[i]["em"]
def vix_spike(D, i):      return D[i]["vix"] / D[i]["vix_prev"] >= 1.20
def front_inverted(D, i): return D[i]["front"] >= 1.10
def calm_close(D, i):     return D[i]["ts"] < 0.90
def exhaustion(D, i):     return i >= 3 and D[i]["ts"] < 1.0 and D[i - 3]["c"] - D[i]["c"] > 2 * D[i]["em"]


RULES = [
    # id, name, kind, rule, spec (swing), what options data it uses, the idea
    {"id": "contango_hold", "name": "Contango trend hold", "kind": "swing", "signal": contango, "entry": "close", "hold": 1,
     "uses": "VIX / VIX3M", "idea": "Long ES/NQ from close to close while the VIX curve is in steep contango (calm, dealers long gamma)."},
    {"id": "backwardation_bounce", "name": "Backwardation bounce", "kind": "swing", "signal": backwardation, "entry": "close", "hold": 3,
     "uses": "VIX / VIX3M", "idea": "Buy the close when the VIX curve inverts (stress), hold 3 sessions: panic tends to be overdone."},
    {"id": "dip_buy_contango", "name": "Dip buy in contango", "kind": "swing", "signal": dip_contango, "entry": "close", "hold": 3,
     "uses": "Expected move, VIX / VIX3M", "idea": "A close below the expected move while the curve stays in contango: buy, hold 3 sessions."},
    {"id": "strength_follow", "name": "Strength follow-through", "kind": "swing", "signal": strength, "entry": "close", "hold": 1,
     "uses": "Expected move, VIX / VIX3M", "idea": "A close above the expected move in steep contango: hold long one more session."},
    {"id": "vix_spike_buy", "name": "VIX spike buy", "kind": "swing", "signal": vix_spike, "entry": "close", "hold": 3,
     "uses": "VIX", "idea": "VIX up 20%+ in a day: buy the close, hold 3 sessions."},
    {"id": "front_inversion_buy", "name": "Front-end inversion buy", "kind": "swing", "signal": front_inverted, "entry": "close", "hold": 3,
     "uses": "VIX9D / VIX", "idea": "9-day vol 10%+ over 30-day vol (event stress): buy the close, hold 3 sessions."},
    {"id": "overnight_contango", "name": "Overnight hold in contango", "kind": "swing", "signal": contango, "entry": "close", "exit": "next_open", "hold": 1,
     "uses": "VIX / VIX3M", "idea": "In contango, hold long from the close to the next open (the overnight drift)."},
    {"id": "calm_day_long", "name": "Calm-day long", "kind": "swing", "signal": calm_close, "entry": "next_open", "hold": 1,
     "uses": "VIX / VIX3M", "idea": "In steep contango, buy the next open and sell its close."},
    {"id": "exhaustion_dip", "name": "Exhaustion dip buy", "kind": "swing", "signal": exhaustion, "entry": "close", "hold": 3,
     "uses": "Expected move, VIX / VIX3M", "idea": "Down more than two expected moves in 3 sessions without curve inversion: buy, hold 3 sessions."},
    {"id": "last_half_hour", "name": "Last-half-hour momentum", "kind": "intraday", "rule": last_half_hour_momentum,
     "uses": "Expected move", "idea": "The day's direction at 15:30 carries into the close (late hedging flows)."},
    {"id": "orb_stress", "name": "Opening-range breakout in stress", "kind": "intraday", "rule": orb_front_stress,
     "uses": "VIX9D / VIX", "idea": "When short-dated vol is bid, trade the break of the first hour's range."},
    {"id": "orb_calm", "name": "Opening-range breakout in calm", "kind": "intraday", "rule": orb_calm,
     "uses": "VIX9D / VIX", "idea": "The same breakout on calm days."},
    {"id": "first_hour_fade", "name": "First-hour fade in contango", "kind": "intraday", "rule": first_hour_fade,
     "uses": "Expected move, VIX / VIX3M", "idea": "Calm markets mean-revert: fade a big first hour back toward the previous close."},
    {"id": "vanna_afternoon", "name": "Vanna afternoon drift", "kind": "intraday", "rule": vanna_afternoon,
     "uses": "Hourly VIX", "idea": "Falling implied vol makes dealers buy back hedges into the close (vanna); rising vol the opposite."},
    {"id": "band_fade", "name": "Expected-move fade in contango", "kind": "intraday", "rule": band_fade_contango,
     "uses": "Expected move, VIX / VIX3M", "idea": "In calm markets, fade touches of the expected-move band."},
]


# ---------------------------------------------------------------------------- GEX PRO level rules (forward test)
def wall_fade(d) -> list:
    """Positive gamma: resting order at the put wall (long) / call wall (short) within 1.5 em, stop 0.5 em
    past the wall, target the previous close, out at the close."""
    if d["regime"] != "POSITIVE":
        return []
    out = []
    for lvl, side in ((d.get("pw"), +1), (d.get("cw"), -1)):
        if lvl and 0 < side * (d["ref"] - lvl) <= 1.5 * d["em"]:
            x = trade(d["path"], side, lvl, "limit", lvl - side * 0.5 * d["em"], d["ref"])
            if x is not None:
                out.append(x)
    return out


def zero_gamma_reject(d) -> list:
    """Negative gamma with zero gamma above price: short a rally into zero gamma, stop 0.5 em above."""
    zg = d.get("zg")
    if d["regime"] != "NEGATIVE" or not zg or not 0 < zg - d["ref"] <= 1.5 * d["em"]:
        return []
    x = trade(d["path"], -1, zg, "limit", zg + 0.5 * d["em"])
    return [] if x is None else [x]


def negative_gamma_orb(d) -> list:
    """Negative gamma: trade the break of the first hour's range."""
    return _orb(d) if d["regime"] == "NEGATIVE" else []


def magnet(d) -> list:
    """Positive gamma: at 10:30, more than 0.5 em from the absolute gamma strike, trade toward it, target it,
    stop 0.75 em further away."""
    ag = d.get("ag")
    if d["regime"] != "POSITIVE" or not ag:
        return []
    px = d["path"][1][0]
    if abs(px - ag) <= 0.5 * d["em"]:
        return []
    side = 1 if ag > px else -1
    return [trade(d["path"][1:], side, None, "open", px - side * 0.75 * d["em"], ag)]


GEX_RULES = [
    {"id": "wall_fade", "name": "Wall fade in positive gamma", "rule": wall_fade, "uses": "Call and put walls, regime"},
    {"id": "zero_gamma_reject", "name": "Zero-gamma rejection in negative gamma", "rule": zero_gamma_reject, "uses": "Zero gamma, regime"},
    {"id": "negative_gamma_orb", "name": "Negative-gamma opening-range breakout", "rule": negative_gamma_orb, "uses": "Regime"},
    {"id": "magnet", "name": "Absolute-gamma magnet", "rule": magnet, "uses": "Absolute gamma strike, regime"},
]


# ---------------------------------------------------------------------------- statistics and the bar
def stats(trades: list) -> dict:
    """trades: (date, points, R). """
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
    cum = peak = ddp = 0.0
    for x in pts:
        cum += x
        peak = max(peak, cum)
        ddp = max(ddp, peak - cum)
    held = [t[3] for t in trades if len(t) > 3]
    return {"n": n, "max_dd_pts": round(ddp, 1), "sessions_held": sum(held) if held else None, "win": round(sum(1 for x in pts if x > 0) / n, 4), "avg_r": round(mean, 4),
            "avg_pts": round(sum(pts) / n, 2), "total_r": round(sum(r), 2), "total_pts": round(sum(pts), 1),
            "pf": round(wins / losses, 3) if losses else None, "max_dd_r": round(dd, 2),
            "t": round(mean / sd * math.sqrt(n), 2) if sd else None, "worst_r": round(min(r), 2), "best_r": round(max(r), 2)}


def _halves(trades: list, mid: str) -> list:
    return [stats([t for t in trades if t[0] < mid]), stats([t for t in trades if t[0] >= mid])]


def _both_up(h: list) -> bool:
    return all(x.get("n") and x["avg_r"] > 0 for x in h)


def verdict(kind: str, res: dict) -> tuple[bool, str]:
    """(passed, reason) from the per-index results {"SPX": {...}, "NDX": {...}}."""
    for und in ("SPX", "NDX"):
        w = res[und]["window"]
        if w["stats"].get("n", 0) < (30 if kind == "intraday" else 10):
            return False, f"too few trades on {FUTURE[und]}"
        if w["stats"]["avg_pts"] <= 0:
            return False, f"loses money after costs on {FUTURE[und]}"
        if w["stats"]["avg_r"] <= 0:
            return False, f"loses money per unit of risk on {FUTURE[und]} (a few big wins carry the $ average)"
        if not _both_up(w["halves"]):
            return False, f"one half of the 3 years lost money on {FUTURE[und]}"
        if kind == "intraday" and (w["stats"].get("t") or 0) < 2:
            return False, f"profit too small to rule out luck on {FUTURE[und]} (t {w['stats'].get('t')})"
    if kind == "swing":
        for und in ("SPX", "NDX"):
            o = res[und].get("oos")
            if not o or o["stats"].get("n", 0) < 30:
                return False, f"too few out-of-sample trades on {FUTURE[und]}"
            if o["stats"]["avg_r"] <= 0 or o["stats"]["avg_pts"] <= 0 or not _both_up(o["halves"]):
                return False, f"failed out of sample ({OOS_START[:4]}-) on {FUTURE[und]}"
            if (o["stats"].get("t") or 0) < 1.65:
                return False, f"out-of-sample profit too small to rule out luck on {FUTURE[und]} (t {o['stats'].get('t')})"
    return True, "passed every test"


# ---------------------------------------------------------------------------- running the study
def build_days(bars: dict, vol: dict, term: dict, until: str, hourly: Optional[dict] = None, vixh: Optional[dict] = None) -> list:
    """One record per session. term = {"VIX": {...}, "VIX3M": {...}, "VIX9D": {...}} (daily closes)."""
    vix, v3, v9 = term["VIX"], term["VIX3M"], term.get("VIX9D", {})
    ds = sorted(d for d in bars if d <= until)
    out = []
    for prev, d in zip(ds, ds[1:]):
        if not (vol.get(prev) and vix.get(prev) and v3.get(prev) and vix.get(d) and v3.get(d)):
            continue
        ref, b = bars[prev]["close"], bars[d]
        rec = {"date": d, "ref": ref, "em": ref * vol[prev] / 100 / math.sqrt(SESSIONS_PER_YEAR),
               "o": b["open"], "h": b["high"], "l": b["low"], "c": b["close"],
               "ts_prev": vix[prev] / v3[prev], "front_prev": (v9.get(prev) or vix[prev]) / vix[prev],
               "ts": vix[d] / v3[d], "front": (v9.get(d) or vix[d]) / vix[d], "vix": vix[d], "vix_prev": vix[prev],
               "path": None, "vixh": (vixh or {}).get(d, {})}
        if hourly and len(hourly.get(d) or []) >= 6:
            rec["path"] = hourly[d]
        out.append(rec)
    return out


def run_swing(D: list, spec: dict, cost: float) -> list:
    """One position at a time. A close-to-close position is KEPT (no new round trip, no new cost) when the
    signal is still on at its exit close; other signals while a trade is open are ignored."""
    out, i, hold = [], 0, spec["hold"]
    while i < len(D):
        if spec["signal"](D, i):
            if spec.get("exit") == "next_open":
                if i + 1 >= len(D):
                    break
                p, nxt = D[i + 1]["o"] - D[i]["c"], i + 1
            elif spec["entry"] == "next_open":
                if i + 1 >= len(D):
                    break
                p, nxt = D[i + 1]["c"] - D[i + 1]["o"], i + 2
            else:
                if i + hold >= len(D):
                    break
                nxt = i + hold
                while nxt + hold < len(D) and spec["signal"](D, nxt):
                    nxt += hold                                 # still signalled: stay in the trade
                p = D[nxt]["c"] - D[i]["c"]
            p -= cost
            out.append((D[i]["date"], round(p, 3), p / D[i]["em"], max(1, nxt - i)))
            i = nxt
        else:
            i += 1
    return out


def position_now(D: list, spec: dict) -> dict:
    """Where the rule stands after the last close: in a trade (since when, at what price) or flat."""
    i, hold = 0, spec["hold"]
    while i < len(D):
        if spec["signal"](D, i) and spec["entry"] == "close" and spec.get("exit") != "next_open":
            nxt = i + hold
            while nxt < len(D) and spec["signal"](D, nxt):      # still signalled at that close: stay in
                nxt += hold
            if nxt > len(D) - 1:                               # the exit close hasn't happened yet: still in
                e = D[i]
                return {"in": True, "since": e["date"], "entry": e["c"], "last": D[-1]["c"], "pts": round(D[-1]["c"] - e["c"], 2),
                        "exit_due": f"{nxt - (len(D) - 1)} more session(s), then again only if the signal is still on"}
            i = nxt
        else:
            i += 1
    last = D[-1] if D else None
    return {"in": False, "signal_today": bool(last and spec["signal"](D, len(D) - 1)), "date": last["date"] if last else None}


def _benchmark(D: list) -> dict:
    """Buy and hold over the same sessions, in index points (no costs)."""
    if len(D) < 2:
        return {}
    eq = peak = dd = 0.0
    for a, b in zip(D, D[1:]):
        eq += b["c"] - a["c"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"pts": round(D[-1]["c"] - D[0]["c"], 1), "max_dd_pts": round(dd, 1), "sessions": len(D) - 1}


def daily_drawdown(D: list, trades: list, cost: float) -> float:
    """Worst peak-to-trough fall of the account marked to market at every close (index points)."""
    at = {d["date"]: k for k, d in enumerate(D)}
    pos = [0] * len(D)
    entry_cost = [0.0] * len(D)
    for tr in trades:
        k = at.get(tr[0])
        if k is None or len(tr) < 4:
            continue
        for m in range(k, min(len(D) - 1, k + tr[3])):
            pos[m] = 1
        entry_cost[k] += cost
    eq = peak = dd = 0.0
    for k in range(len(D) - 1):
        eq += pos[k] * (D[k + 1]["c"] - D[k]["c"]) - entry_cost[k]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return round(dd, 1)


def run_intraday(D: list, rule: Callable, cost: float) -> list:
    out = []
    for d in D:
        if not d.get("path"):
            continue
        for x in rule(d):
            if x is not None:
                x -= cost
                out.append((d["date"], round(x, 3), x / d["em"]))
    return out


def _curve(trades: list, max_points: int = 200) -> list:
    cum, out = 0.0, []
    step = max(1, len(trades) // max_points)
    for i, tr in enumerate(trades):
        d, r = tr[0], tr[2]
        cum += r
        if i % step == 0 or i == len(trades) - 1:
            out.append([d, round(cum, 2)])
    return out


def study(data: dict, until: str) -> dict:
    """data = {"SPX": {"bars", "vol", "hourly"}, "NDX": {...}, "term": {...}, "vixh": {...}}."""
    days = {}
    for und in ("SPX", "NDX"):
        x = data[und]
        days[und] = build_days(x["bars"], x["vol"], data["term"], until, x.get("hourly"), data.get("vixh"))
    hourly_days = {u: [d for d in D if d["path"]] for u, D in days.items()}
    if not hourly_days["SPX"]:
        return {}
    end = hourly_days["SPX"][-1]["date"]
    start = f"{int(end[:4]) - WINDOW_YEARS}{end[4:]}"
    start = max(start, hourly_days["SPX"][0]["date"])
    last = days["SPX"][-1] if days["SPX"] else None
    out = {"version": VERSION, "window": [start, end], "oos": [OOS_START, start], "rules": [], "cost_pts": COST, "point_value": POINT_VALUE,
           "now": {"date": last["date"], "vix_vix3m": round(last["ts"], 4), "vix9d_vix": round(last["front"], 4), "vix": last["vix"]} if last else None}
    for spec in RULES:
        res = {}
        for und in ("SPX", "NDX"):
            D = days[und]
            if spec["kind"] == "swing":
                Dw, Do = [d for d in D if d["date"] >= start], [d for d in D if OOS_START <= d["date"] < start]
                win, oos = run_swing(Dw, spec, COST[und]), run_swing(Do, spec, COST[und])
                mid_o = next((d["date"] for d in D if d["date"] >= OOS_START), start)
                omid = sorted(t[0] for t in oos)[len(oos) // 2] if oos else mid_o
                res[und] = {"window": {"stats": dict(stats(win), daily_dd_pts=daily_drawdown(Dw, win, COST[und])),
                                       "halves": _halves(win, _mid(start, end)), "buy_hold": _benchmark(Dw)},
                            "oos": {"stats": dict(stats(oos), daily_dd_pts=daily_drawdown(Do, oos, COST[und])),
                                    "halves": _halves(oos, omid), "buy_hold": _benchmark(Do)},
                            "curve": _curve(oos + win), "now": position_now(D, spec)}
            else:
                win = run_intraday([d for d in hourly_days[und] if d["date"] >= start], spec["rule"], COST[und])
                res[und] = {"window": {"stats": stats(win), "halves": _halves(win, _mid(start, end))}, "curve": _curve(win)}
        ok, why = verdict(spec["kind"], res)
        out["rules"].append({"id": spec["id"], "name": spec["name"], "kind": spec["kind"], "uses": spec["uses"],
                             "idea": spec["idea"], "hold": spec.get("hold"), "passed": ok, "why": why, "results": res})
    return out


def _mid(a: str, b: str) -> str:
    da, db = date.fromisoformat(a), date.fromisoformat(b)
    return (da + (db - da) / 2).isoformat()


def gex_forward(sessions: list, hourly: dict) -> dict:
    """The GEX-level rules on the track record's sessions (frozen pre-open plans), walked on hourly bars.
    hourly = {"SPX": {date: path}, "NDX": {...}}."""
    days = []
    for x in sessions:
        p, o = x.get("plan"), x.get("outcome")
        und = (p or {}).get("underlying")
        path = (hourly.get(und) or {}).get(x["session"]) if und else None
        if not p or not o or not p.get("em") or not path or len(path) < 6:
            continue
        days.append({"date": x["session"], "und": und, "ref": p["ref"], "em": p["em"], "regime": p.get("regime"),
                     "cw": p.get("cw"), "pw": p.get("pw"), "zg": p.get("zg"), "ag": p.get("ag"), "path": path})
    days.sort(key=lambda d: d["date"])
    out = {"sessions": len(days), "rules": []}
    for spec in GEX_RULES:
        tr = []
        for d in days:
            for v in spec["rule"](d):
                if v is not None:
                    v -= COST[d["und"]]
                    tr.append((d["date"], round(v, 3), v / d["em"]))
        st = stats(tr)
        mid = days[len(days) // 2]["date"] if days else ""
        ok = st.get("n", 0) >= 30 and st["avg_r"] > 0 and st["avg_pts"] > 0 and (st.get("t") or 0) >= 2 and _both_up(_halves(tr, mid))
        out["rules"].append({"id": spec["id"], "name": spec["name"], "uses": spec["uses"], "doc": (spec["rule"].__doc__ or "").strip(),
                             "stats": st, "passed": ok, "why": "passed every test" if ok else f"collecting evidence: {st.get('n', 0)} of 30+ trades"
                             if st.get("n", 0) < 30 else "has not passed (needs a profit, t >= 2 and both halves profitable)"})
    return out
