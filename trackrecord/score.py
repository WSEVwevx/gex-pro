"""The plan and its grade.

A PLAN is what GEX PRO said before a session: the levels from the last calculation whose data is
timestamped before the 09:30 ET open (index points, so no futures basis gets in the way). After the
close it is graded against that session's open, high, low and close. The rules are fixed here, in
code, before any outcome is known; nothing is fitted to past results.

Grades (em = the daily expected move, ref = the price the plan was made at):
  expected move   close within ref +/- em ("1 sigma": about 68% if implied vol were a fair forecast);
                  whole range inside the band; breaks above / below
  regime          realized range / em, compared between positive and negative gamma sessions
                  (the model says negative gamma sessions should run wider)
  walls           a wall above (call) or below (put) ref is TOUCHED when the session trades within
                  5% of em of it, and HELD when it was touched but the close stayed on the near side
  zero gamma      whether the session traded through it
  bias            direction call (Bullish / Bearish) vs the close relative to ref; Neutral is not graded.
                  The base-case target BEATS NO CHANGE when it is closer to the close than ref is.
  magnet          on positive gamma sessions: the close ended nearer the absolute gamma strike than the open
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

TOUCH = 0.05          # a level counts as touched within 5% of the expected move
MIN_SAMPLE = 20       # below this many sessions the page says the numbers are too early to mean much
Z95 = 1.96


def _r(x, d=2):
    return None if x is None else round(float(x), d)


def make_plan(inp: dict, session: str, frozen_at: str) -> Optional[dict]:
    """inp: the pre-open levels from the app shell (index points). None when unusable."""
    ref, em = inp.get("ref"), inp.get("em")
    if not ref or not em or em <= 0:
        return None
    b = inp.get("bias") or {}
    return {
        "session": session, "market": inp["market"], "underlying": inp.get("underlying"),
        "asof": inp.get("asof"), "frozen_at": frozen_at,
        "ref": _r(ref), "em": _r(em), "em_iv": _r(inp.get("em_iv"), 4),
        "regime": inp.get("regime"), "net": _r(inp.get("net"), 0),
        "zg": _r(inp.get("zg")), "cw": _r(inp.get("cw")), "pw": _r(inp.get("pw")), "ag": _r(inp.get("ag")),
        "bias": b.get("bias"), "confidence": b.get("confidence"), "day_type": b.get("day_type"),
        "side": b.get("side"), "target": _r(b.get("target")),
    }


def _wall(level, ref, em, high, low, close, above: bool) -> Optional[dict]:
    if level is None or (above and level <= ref) or (not above and level >= ref):
        return None                                          # price already past it when the plan was made
    tol = TOUCH * em
    touched = high >= level - tol if above else low <= level + tol
    beyond = close > level if above else close < level
    return {"level": level, "dist_em": _r(abs(level - ref) / em, 3), "touched": touched,
            "closed_beyond": beyond, "held": touched and not beyond}


def grade(plan: dict, bar: dict) -> dict:
    """bar: {"open", "high", "low", "close", "source"} for the plan's session, in index points."""
    o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
    ref, em = plan["ref"], plan["em"]
    out = {"open": _r(o), "high": _r(h), "low": _r(l), "close": _r(c), "source": bar.get("source"),
           "move": _r(c - ref), "move_em": _r((c - ref) / em, 3), "range_em": _r((h - l) / em, 3),
           "em_close": abs(c - ref) <= em, "em_range": h <= ref + em and l >= ref - em,
           "em_up_break": h > ref + em, "em_down_break": l < ref - em,
           "cw": _wall(plan.get("cw"), ref, em, h, l, c, True), "pw": _wall(plan.get("pw"), ref, em, h, l, c, False),
           "zg": None, "bias_hit": None, "target_beat": None, "magnet": None}
    zg = plan.get("zg")
    if zg is not None:
        out["zg"] = {"open_side": "above" if o >= zg else "below", "crossed": l <= zg <= h}
    if plan.get("bias") in ("Bullish", "Bearish") and c != ref:
        out["bias_hit"] = (c > ref) == (plan["bias"] == "Bullish")
    t = plan.get("target")
    if t is not None and abs(t - ref) > 1e-9:
        out["target_beat"] = abs(c - t) < abs(c - ref)
    ag = plan.get("ag")
    if ag is not None and plan.get("regime") == "POSITIVE" and abs(o - ag) > 1e-9:
        out["magnet"] = abs(c - ag) < abs(o - ag)
    return out


# ---------------------------------------------------------------------------- summary statistics
def wilson(k: int, n: int) -> Optional[list]:
    """95% Wilson interval for k successes out of n (honest with small samples)."""
    if n <= 0:
        return None
    p = k / n
    d = 1 + Z95 ** 2 / n
    mid = (p + Z95 ** 2 / (2 * n)) / d
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n * n)) / d
    return [round(max(0.0, mid - half), 4), round(min(1.0, mid + half), 4)]


def rate(flags: Iterable) -> dict:
    v = [bool(f) for f in flags if f is not None]
    k, n = sum(v), len(v)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci": wilson(k, n)}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return {"mean": round(sum(xs) / len(xs), 3) if xs else None, "n": len(xs)}


def summarize(rows: list[dict]) -> dict:
    """rows: graded sessions ({"plan": ..., "outcome": ...}) for one market or all of them."""
    rows = [r for r in rows if r.get("outcome")]
    out = [r["outcome"] for r in rows]
    plans = [r["plan"] for r in rows]
    walls = [o[k] for o in out for k in ("cw", "pw") if o.get(k)]
    graded_bias = [(p, o) for p, o in zip(plans, out) if o.get("bias_hit") is not None]
    ups = sum(1 for _, o in graded_bias if o["move"] > 0)
    majority = max(ups, len(graded_bias) - ups)
    pos = [o["range_em"] for p, o in zip(plans, out) if p.get("regime") == "POSITIVE"]
    neg = [o["range_em"] for p, o in zip(plans, out) if p.get("regime") == "NEGATIVE"]
    return {
        "sessions": len(rows), "early": len(rows) < MIN_SAMPLE,
        "em_close": dict(rate(o["em_close"] for o in out), expected=0.6827),
        "em_range": rate(o["em_range"] for o in out),
        "em_up_break": rate(o["em_up_break"] for o in out),
        "em_down_break": rate(o["em_down_break"] for o in out),
        "move_em": _mean(abs(o["move_em"]) for o in out),
        "range_em": {"all": _mean(o["range_em"] for o in out), "positive": _mean(pos), "negative": _mean(neg)},
        "call_wall": {"touched": rate(o["cw"]["touched"] for o in out if o.get("cw")),
                      "held": rate(o["cw"]["held"] for o in out if o.get("cw") and o["cw"]["touched"])},
        "put_wall": {"touched": rate(o["pw"]["touched"] for o in out if o.get("pw")),
                     "held": rate(o["pw"]["held"] for o in out if o.get("pw") and o["pw"]["touched"])},
        "walls_held": rate(w["held"] for w in walls if w["touched"]),
        "zg_crossed": rate(o["zg"]["crossed"] for o in out if o.get("zg")),
        "bias": dict(rate(o["bias_hit"] for _, o in graded_bias),
                     baseline=round(majority / len(graded_bias), 4) if graded_bias else None),
        "target_beat": rate(o["target_beat"] for o in out),
        "magnet": rate(o["magnet"] for o in out),
    }
