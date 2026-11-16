"""The session brief: one screen, every sentence a computed fact with its number. Written twice for each session:
the Asia brief the evening before (19:00 ET) and the NY AM brief before the open (09:00 ET). Same five blocks; only
the NY AM brief is graded afterwards, so a session is never scored twice.

Five blocks, in this order:
  1. regime      today's gamma regime and distance from zero gamma, and what that regime did in graded sessions
  2. key levels  the three named levels nearest to price, measured in expected moves (a fixed rule, never a judgment)
  3. changed     levels, regime and expected move against the previous close (at today's futures basis)
  4. events      today's scheduled US releases; how event days ranged, once enough of them are graded
  5. yesterday   the previous session's plan as the Track record graded it

Rules fixed before any brief was graded:
  MIN = 20       a historical figure is printed only from 20 graded sessions (or touches); below that the brief
                 says "not enough yet". The same threshold the Track record uses.
  No hindsight   history uses graded sessions BEFORE this brief's session only; every input is older than the brief.
  Gradeable statements, scored after the close against the index's open/high/low/close (the Track record's bar):
    band          the close ended inside the expected range              baseline 68.27% (what 1 sigma means)
    regime_range  a negative-gamma session ranged wider than the median graded session so far, a positive-gamma
                  one narrower (only once MIN sessions are graded)       baseline 50%
    key_level     the session traded within 5% of an expected move of the level
                                                                         baseline: a random walk reaching that
                                                                         distance, 2 * (1 - Phi(distance))
    wall_holds    a key wall that was touched closed on the side price started
                                                                         baseline 50%
  A statement type is flagged when, from MIN grades on, even the top of its 95% range is below its baseline.

Inputs (from the app shell, see gexpro/context.py): the snapshot compose.py documents, where each market also has
  "factor", "offset"   futures = index * factor + offset (to grade futures levels on the index bar)
  "prev"               {"day", "zero_gamma", "call_wall", "put_wall", "regime", "em"} at the previous close, or None
record: the Track record's sessions [{"session", "market", "plan": {...}, "outcome": {...} | None}].
past:   earlier NY AM briefs (for which sessions had a high-impact release).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from statistics import median
from typing import Optional

from .schedule import NY, TITLES

VERSION = 2
MIN = 20
TOUCH = 0.05
STALE_S = 2 * 3600
RULE = "The three named levels nearest to price, measured in expected moves."
REGIME = {"POSITIVE": "positive gamma", "NEGATIVE": "negative gamma", "INDETERMINATE": "balanced gamma"}
ROLE = {"Call wall": "largest call gamma strike", "Put wall": "largest put gamma strike",
        "Zero gamma": None, "Abs gamma": "most total gamma (calls and puts)"}
BASE = {"band": 0.6827, "regime_range": 0.5, "wall_holds": 0.5}
LABEL = {"band": "Close inside the expected range", "regime_range": "Regime called the range (wide or narrow)",
         "key_level": "A key level was reached", "wall_holds": "A key wall held when touched"}


def _f(p) -> str:
    return "-" if p is None else f"{p:,.2f}"


def _t(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(NY)


def _clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def _day(iso_date: str) -> str:
    return date.fromisoformat(iso_date).strftime("%a %b ") + str(date.fromisoformat(iso_date).day)


def _graded(record: list, before: str) -> list:
    """Graded sessions strictly before `before` (YYYY-MM-DD): the only history a brief may use."""
    return [r for r in record or [] if r.get("outcome") and r.get("plan") and r.get("session", "9") < before]


# ---------------------------------------------------------------- block 1: regime
def regime_block(m: dict, graded: list) -> dict:
    regime, zg, em = m.get("regime"), m.get("zero_gamma"), (m.get("em") or {}).get("daily")
    sig = None if zg is None or not em else (m["price"] - zg) / em
    line = f"{m['market']} {_f(m['price'])} is in {REGIME.get(regime, 'no clear gamma regime')}"
    if sig is not None:
        line += f", {abs(sig):.1f}σ {'above' if sig >= 0 else 'below'} zero gamma {_f(zg)}"
    same = [r["outcome"] for r in graded if r["plan"].get("regime") == regime and r["outcome"].get("range_em") is not None]
    every = [r["outcome"]["range_em"] for r in graded if r["outcome"].get("range_em") is not None]
    name = REGIME.get(regime, "this regime")
    if len(same) < MIN:
        hist = f"{len(same)} {name} sessions graded so far: not enough yet ({MIN} needed)."
    else:
        avg = sum(o["range_em"] for o in same) / len(same)
        hist = (f"{len(same)} {name} sessions graded: range averaged {avg:.2f}× the expected move "
                f"(all {len(every)}: {sum(every) / len(every):.2f}×).")
        touched = [w for o in same for w in (o.get("cw"), o.get("pw")) if w and w.get("touched")]
        if len(touched) >= MIN:
            hist += f" Walls held on {sum(1 for w in touched if w['held'])} of {len(touched)} touches."
        else:
            hist += f" Wall touches so far: {len(touched)} of the {MIN} needed."
    return {"line": line + ".", "history": hist, "n": len(same), "sigma": None if sig is None else round(sig, 2),
            "range_ref": round(median(every), 3) if len(every) >= MIN else None}


# ---------------------------------------------------------------- block 2: the three levels
def key_levels(m: dict, n: int = 3) -> list:
    price, em = m["price"], (m.get("em") or {}).get("daily")
    near = m.get("nearest") or {}
    lab = near.get("label")
    cands = [(k, m.get(f)) for k, f in (("Call wall", "call_wall"), ("Put wall", "put_wall"), ("Zero gamma", "zero_gamma"), ("Abs gamma", "abs_gamma"))]
    if lab:
        cands += [(f"{lab[0].upper()}{lab[1:]} {k.lower()}", near.get(f)) for k, f in (("Call wall", "call_wall"), ("Put wall", "put_wall"), ("Zero gamma", "zero_gamma"))]
    merged: dict = {}
    for name, p in cands:
        if p is not None:
            merged.setdefault(round(p, 2), []).append(name)
    out = []
    for p, names in sorted(merged.items(), key=lambda kv: (abs(kv[0] - price), kv[0]))[:n]:
        first = names[0]
        base = next((k for k in ROLE if first.lower().endswith(k.lower())), first)
        if base == "Zero gamma":
            why = f"gamma turns {'positive above' if price < p else 'negative below'} it"
        else:
            why = ROLE.get(base) or ""
        out.append({"name": " · ".join(names), "price": p, "dist": round(p - price, 2),
                    "dist_em": None if not em else round(abs(p - price) / em, 2),
                    "side": "above" if p >= price else "below", "why": why,
                    "wall": "call" if "call wall" in first.lower() else "put" if "put wall" in first.lower() else None})
    return out


# ---------------------------------------------------------------- block 3: what changed
def changes_block(m: dict) -> dict:
    prev = m.get("prev")
    if not prev:
        return {"since": None, "items": ["The previous close's levels are not saved here: no comparison."]}
    items = []
    if prev.get("regime") and prev["regime"] != m.get("regime"):
        items.append(f"Regime: {REGIME.get(prev['regime'], prev['regime'])} → {REGIME.get(m.get('regime'), m.get('regime'))}.")
    for name, k in (("Zero gamma", "zero_gamma"), ("Call wall", "call_wall"), ("Put wall", "put_wall")):
        a, b = prev.get(k), m.get(k)
        if a is not None and b is not None and abs(b - a) >= 0.25:
            items.append(f"{name} {_f(a)} → {_f(b)} ({b - a:+,.2f}).")
    a, b = prev.get("em"), (m.get("em") or {}).get("daily")
    if a and b and abs(b - a) >= 1:
        items.append(f"Expected move ±{a:,.0f} → ±{b:,.0f} pts.")
    since = _day(prev["day"])
    return {"since": since, "items": items or [f"No change since {since}'s close."]}


# ---------------------------------------------------------------- block 5: yesterday, graded
def yesterday_block(market: str, record: list, session: str) -> Optional[dict]:
    rows = sorted((r for r in record or [] if r.get("market") == market and r.get("plan") and r.get("session", "9") < session),
                  key=lambda r: r["session"])
    if not rows:
        return None
    r = rows[-1]
    day, o = _day(r["session"]), r.get("outcome")
    if not o:
        return {"session": r["session"], "text": f"{day}: not graded yet."}
    parts = [f"{day}: closed {'inside' if o['em_close'] else 'outside'} the expected range (move {o['move_em']:+.2f}σ), "
             f"range {o['range_em']:.2f}× the expected move"]
    for name, k in (("call wall", "cw"), ("put wall", "pw")):
        w = o.get(k)
        if w:
            parts.append(f"{name} {'held' if w['held'] else 'broke' if w['touched'] else 'not reached'}")
    if o.get("zg"):
        parts.append(f"zero gamma {'crossed' if o['zg']['crossed'] else 'not crossed'}")
    if o.get("bias_hit") is not None:
        parts.append(f"{r['plan'].get('bias', 'bias').lower()} call {'right' if o['bias_hit'] else 'wrong'}")
    return {"session": r["session"], "text": "; ".join(parts) + "."}


# ---------------------------------------------------------------- block 4: events
def _high_days(past: list) -> set:
    """Sessions whose NY AM brief listed a high-impact US release."""
    out = set()
    for b in past or []:
        if b.get("kind") == "nyam" and any(e.get("impact") == "High" for c in b.get("calendar") or [] for e in c.get("items") or []):
            out.add(b.get("session"))
    return out


def event_history(graded: list, past: list) -> Optional[str]:
    briefed = {b.get("session") for b in past or [] if b.get("kind") == "nyam"}
    hot = _high_days(past)
    ev = [r["outcome"]["range_em"] for r in graded if r["session"] in hot and r["outcome"].get("range_em") is not None]
    rest = [r["outcome"]["range_em"] for r in graded if r["session"] in briefed - hot and r["outcome"].get("range_em") is not None]
    if len(ev) < MIN or len(rest) < MIN:
        return f"High-impact days graded so far: {len(ev)} of the {MIN} needed to say how they range."
    return (f"On {len(ev)} graded sessions with a high-impact release the range averaged {sum(ev) / len(ev):.2f}× the expected move, "
            f"against {sum(rest) / len(rest):.2f}× on {len(rest)} others.")


# ---------------------------------------------------------------- the brief
def market_brief(m: dict, record: list, session: str, now: datetime, kind: str = "nyam") -> dict:
    graded = _graded(record, session)
    reg = regime_block(m, graded)
    em = m.get("em") or {}
    rng = None
    if em.get("anchor") is not None and em.get("daily"):
        lo, hi = em["anchor"] - em["daily"], em["anchor"] + em["daily"]
        rng = {"low": round(lo, 2), "high": round(hi, 2), "em": round(em["daily"], 2), "text": f"Expected range {'today' if kind == 'nyam' else 'next session'} {_f(lo)} to {_f(hi)} (±{em['daily']:,.0f} pts, 1σ)."}
    stale = None
    data = ""
    if m.get("asof"):
        t = _t(m["asof"])
        if t > now:                                        # no hindsight: a brief never holds data newer than itself
            raise ValueError(f"{m['market']} levels are stamped {t.isoformat()}, after the brief ({now.isoformat()})")
        data = (f"{m.get('options', '')} options, {'real time' if m.get('quality') == 'RT' else '15-min delayed'}, calculated "
                f"{_clock(t)} ET; open interest from the last close.")
        if (now - t).total_seconds() > STALE_S:
            stale = f"Levels were last calculated {t:%a} {_clock(t)} ET: older than usual for a brief."
    return {"market": m["market"], "price": m["price"], "regime": m.get("regime"), "zero_gamma": m.get("zero_gamma"), "asof": m.get("asof"),
            "sigma": reg["sigma"], "regime_line": reg["line"], "history": reg["history"], "history_n": reg["n"],
            "levels": key_levels(m), "range": rng, "changes": changes_block(m),
            "yesterday": yesterday_block(m["market"], record, session), "data": data, "stale": stale,
            # what the grade needs, frozen with the brief
            "claims": {"factor": m.get("factor") or 1.0, "offset": m.get("offset") or 0.0, "em": em.get("daily"),
                       "range_ref": reg["range_ref"]}}


OVERNIGHT = {"JPY", "CNY", "AUD", "NZD", "EUR", "GBP", "CHF", "All"}


def compose_brief(kind: str, ctx: dict, slot: datetime, session: date, record: Optional[list] = None, past: Optional[list] = None,
                  events_fn=None) -> dict:
    """kind "nyam": written before `session`'s open. kind "asia": written the evening before it."""
    now = datetime.fromisoformat(ctx["now"]).astimezone(NY)
    sid = session.isoformat()
    markets = [market_brief(m, record or [], sid, now, kind) for m in ctx.get("markets", []) if m.get("price")]
    sess = datetime.combine(session, datetime.min.time(), NY)
    ev = lambda a, b, cur: events_fn(ctx.get("events", []), a, b, cur) if events_fn else []
    items = ev(sess, sess + timedelta(days=1), {"USD"})
    high = [e for e in items if e["impact"] == "High"]
    cal = {"title": "US releases today (ET)" if kind == "nyam" else f"US releases {session:%a %b} {session.day} (ET)", "items": items,
           "history": event_history(_graded(record or [], sid), [b for b in past or [] if b.get("session", "9") < sid]) if high else None}
    cals = [cal] if kind == "nyam" else [{"title": "Overnight: Asia and Europe (ET)", "history": None,
                                          "items": ev(slot - timedelta(hours=1), sess.replace(hour=9, minute=30), OVERNIGHT)}, cal]
    head = " ".join(f"{mb['market']}: {REGIME.get(mb['regime'], 'no clear regime')}"
                    + (f", {abs(mb['sigma']):.1f}σ {'above' if mb['sigma'] >= 0 else 'below'} zero gamma." if mb["sigma"] is not None else ".")
                    for mb in markets) or "No GEX levels available yet."
    if high:
        head += f" {len(high)} high-impact release{'s' if len(high) > 1 else ''}: " + ", ".join(f"{e['title']} {e['clock']}" for e in high[:3]) + "."
    return {"kind": kind, "version": VERSION, "title": TITLES[kind], "slot": slot.isoformat(), "session": sid,
            "generated_at": now.isoformat(), "late": (now - slot).total_seconds() > 30 * 60, "headline": head, "rule": RULE,
            "markets": markets, "calendar": cals,
            "note": "Computed from options positioning and graded sessions. Facts and their history, not predictions or advice."}


# ---------------------------------------------------------------- grading
def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def grade(mb: dict, outcome: dict) -> list:
    """Score one market's brief against its session: [{"type", "hit", "base"}]. `outcome` is the Track record's
    (index open/high/low/close); the brief's futures prices are taken back to index points with its own factor."""
    c = mb.get("claims") or {}
    f, off, em = c.get("factor") or 1.0, c.get("offset") or 0.0, c.get("em")
    if not em or not all(outcome.get(k) is not None for k in ("high", "low", "close")):
        return []
    idx = lambda p: (p - off) / f
    hi, lo, close, em_i = outcome["high"], outcome["low"], outcome["close"], em / f
    out = []
    if mb.get("range"):
        out.append({"type": "band", "hit": idx(mb["range"]["low"]) <= close <= idx(mb["range"]["high"]), "base": BASE["band"]})
    if c.get("range_ref") is not None and mb.get("regime") in ("POSITIVE", "NEGATIVE"):
        wide = (hi - lo) / em_i > c["range_ref"]
        out.append({"type": "regime_range", "hit": wide == (mb["regime"] == "NEGATIVE"), "base": BASE["regime_range"]})
    ref = idx(mb["price"])
    for lv in mb.get("levels") or []:
        p, tol = idx(lv["price"]), TOUCH * em_i
        touched = lo - tol <= p <= hi + tol
        d = max(0.0, abs(p - ref) / em_i - TOUCH)
        out.append({"type": "key_level", "hit": touched, "base": round(min(1.0, 2 * (1 - _phi(d))), 4)})
        if lv.get("wall") and touched and abs(p - ref) > tol:
            out.append({"type": "wall_holds", "hit": close <= p if p > ref else close >= p, "base": BASE["wall_holds"]})
    return out


def _wilson(k: int, n: int) -> list:
    z = 1.96
    p, d = k / n, 1 + z * z / n
    mid, half = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, mid - half), 4), round(min(1.0, mid + half), 4)]


def score(grades: list) -> list:
    """Running score per statement type from every stored grade row ({"type", "hit", "base"})."""
    out = []
    for t in ("band", "regime_range", "key_level", "wall_holds"):
        rows = [g for g in grades if g.get("type") == t]
        n, k = len(rows), sum(1 for g in rows if g["hit"])
        base = round(sum(g["base"] for g in rows) / n, 4) if n else BASE.get(t)
        ci = _wilson(k, n) if n else None
        out.append({"type": t, "label": LABEL[t], "k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci": ci,
                    "baseline": base, "enough": n >= MIN, "flagged": bool(n >= MIN and ci[1] < base)})
    return out
