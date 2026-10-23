"""Writes a briefing from a plain data snapshot. Rule-based text: the same data always gives the same words.

Snapshot shape (built by the app shell, gexpro/context.py):
  {"now": iso,
   "markets": [{"market": "NQ", "price": 29107.5, "asof": iso, "quality": "DL", "options": "NDX+QQQ",
                "regime": "POSITIVE|NEGATIVE|INDETERMINATE", "net": float ($ per 1% move),
                "zero_gamma", "call_wall", "put_wall", "abs_gamma": float | None,
                "nearest": {"label": "0DTE" | "next MM-DD", "zero_gamma", "call_wall", "put_wall"},
                "em": {"anchor", "daily", "weekly", "weekly_expiry"},
                "bias": {"bias", "confidence", "day_type", "target", "range": [lo, hi], "summary"} | None,
                "delta": {"zero_gamma", "net_change", "regime_changed", "prev_regime"} | None}],
   "events": [{"title", "country", "time": iso, "impact", "forecast", "previous"}],
   "posts":  [{"time": iso, "text", "kind", "url", "market_words": [...], "tone": "bullish|bearish|None"}]}
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from .schedule import NY, TITLES

REGIME = {"POSITIVE": "positive gamma", "NEGATIVE": "negative gamma", "INDETERMINATE": "balanced gamma"}
ASIA_CCY = {"JPY", "CNY", "AUD", "NZD"}


def _f(p) -> str:
    return "-" if p is None else f"{p:,.2f}"


def _d(p, ref) -> str:
    return "" if p is None or ref is None else f" ({'+' if p >= ref else '-'}{abs(p - ref):,.1f})"


def _t(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(NY)


def _clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def _sigma(m: dict) -> Optional[float]:
    zg, em = m.get("zero_gamma"), (m.get("em") or {}).get("daily")
    return None if zg is None or not em else (m["price"] - zg) / em


def market_block(m: dict, kind: str, morning: Optional[dict] = None) -> dict:
    p, regime = m["price"], m.get("regime")
    sig = _sigma(m)
    flip = "" if sig is None else (f", {abs(sig):.1f}σ {'above' if sig >= 0 else 'below'} zero gamma {_f(m['zero_gamma'])}")
    headline = f"{m['market']} {_f(p)}: {REGIME.get(regime, 'no clear gamma read')}{flip}."
    lv = [(n, m.get(k)) for n, k in (("Call wall", "call_wall"), ("Zero gamma", "zero_gamma"),
                                     ("Abs gamma", "abs_gamma"), ("Put wall", "put_wall")) if m.get(k) is not None]
    levels = [{"name": n, "price": v, "text": f"{n} {_f(v)}{_d(v, p)}"} for n, v in sorted(lv, key=lambda x: -x[1])]
    em = m.get("em") or {}
    rng = None
    if em.get("anchor") is not None and em.get("daily"):
        lo, hi = em["anchor"] - em["daily"], em["anchor"] + em["daily"]
        rng = {"low": lo, "high": hi, "text": f"Expected range {'today' if kind == 'nyam' else 'next session'}: "
                                             f"{_f(lo)} to {_f(hi)} (±{em['daily']:,.0f} pts, 1σ)"}
    near = m.get("nearest") or {}
    odte = None
    if near.get("zero_gamma") or near.get("call_wall") or near.get("put_wall"):
        lab = near.get("label") or "0DTE"
        odte = f"{lab}: zero gamma {_f(near.get('zero_gamma'))}, call wall {_f(near.get('call_wall'))}, put wall {_f(near.get('put_wall'))}"
    b = m.get("bias") or {}
    bias = None
    if b:
        bias = (f"{b['bias']} bias ({b['confidence'].lower()} confidence), {b['day_type'].lower()}. "
                f"Base case {_f(b['target'])}{_d(b['target'], p)}; positioning range {_f(b['range'][0])} to {_f(b['range'][1])}.")
    zg, cw, pw = m.get("zero_gamma"), m.get("call_wall"), m.get("put_wall")
    if regime == "POSITIVE":
        plan = (f"Positive gamma: dealer hedging tends to slow moves, so fades toward the walls tend to work. "
                f"Range edges to watch: put wall {_f(pw)} and call wall {_f(cw)}.")
    elif regime == "NEGATIVE":
        plan = (f"Negative gamma: dealer hedging tends to add to moves, so breakouts can run. "
                f"Losing the put wall {_f(pw)} can speed up selling; getting back above zero gamma {_f(zg)} would calm things down.")
    else:
        plan = f"Near the flip at {_f(zg)}: holding above it favours a calmer day, losing it favours a trending one."
    changes = []
    dl = m.get("delta") or {}
    if kind == "asia" and morning and morning.get("zero_gamma") is not None and zg is not None:
        changes.append(f"Zero gamma {_f(morning['zero_gamma'])} this morning, {_f(zg)} now{_d(zg, morning['zero_gamma'])}.")
        if morning.get("regime") and morning["regime"] != regime:
            changes.append(f"Regime flipped from {REGIME.get(morning['regime'], morning['regime'])} to {REGIME.get(regime, regime)}.")
    elif dl.get("zero_gamma") is not None:
        changes.append(f"Zero gamma moved {dl['zero_gamma']:+,.1f} pts since the previous update.")
    if dl.get("regime_changed"):
        changes.append(f"Regime changed from {REGIME.get(dl.get('prev_regime'), dl.get('prev_regime'))} at the last update.")
    return {"market": m["market"], "price": p, "regime": regime, "headline": headline, "levels": levels,
            "range": rng, "odte": odte if kind == "nyam" else None, "bias": bias, "plan": plan, "changes": changes,
            "zero_gamma": zg, "data": f"{m.get('options', '')} options, {'real time' if m.get('quality') == 'RT' else '15-min delayed'}"
                                         f" as of {_clock(_t(m['asof']))} ET; open interest from the last close"
                                         if m.get("asof") else ""}


def _events(events: list, start: datetime, end: datetime, currencies: Optional[set], impacts=("High", "Medium")) -> list:
    out = []
    for e in events:
        try:
            t = _t(e["time"])
        except (KeyError, ValueError, TypeError):
            continue
        if start <= t < end and e.get("impact") in impacts and (currencies is None or e.get("country") in currencies):
            fp = " · ".join(x for x in (f"F {e['forecast']}" if e.get("forecast") else "", f"P {e['previous']}" if e.get("previous") else "") if x)
            out.append({"time": t.isoformat(), "clock": _clock(t), "day": t.strftime("%a"), "country": e.get("country"),
                        "impact": e.get("impact"), "title": e.get("title"), "detail": fp})
    return sorted(out, key=lambda x: x["time"])


def _posts(posts: list, since: datetime, limit: int = 5) -> list:
    out = []
    for p in posts:
        try:
            t = _t(p["time"])
        except (KeyError, ValueError, TypeError):
            continue
        if t >= since and p.get("market_words"):
            text = (p.get("text") or "").replace("\n", " ").strip()
            out.append({"time": t.isoformat(), "clock": f"{t:%a} {_clock(t)}", "tone": p.get("tone"),
                        "words": p["market_words"], "text": text[:220] + ("..." if len(text) > 220 else ""), "url": p.get("url")})
    return sorted(out, key=lambda x: x["time"], reverse=True)[:limit]


def compose(kind: str, ctx: dict, slot: datetime, session: date, morning: Optional[dict] = None) -> dict:
    """`morning`: this session's NY AM briefing markets by name ({"NQ": {...}}), for the Asia 'what changed'."""
    now = datetime.fromisoformat(ctx["now"]).astimezone(NY)
    markets = [market_block(m, kind, (morning or {}).get(m["market"])) for m in ctx.get("markets", []) if m.get("price")]
    sess = datetime.combine(session, datetime.min.time(), NY)
    if kind == "nyam":
        cal = [{"title": "US calendar today (ET)", "items": _events(ctx.get("events", []), sess, sess + timedelta(days=1), {"USD"})}]
        posts = _posts(ctx.get("posts", []), slot - timedelta(hours=17))
        posts_title = "Market-moving posts since yesterday's close"
    else:
        open_ = sess.replace(hour=9, minute=30)
        cal = [{"title": "Overnight: Asia and Europe (ET)", "items": _events(ctx.get("events", []), slot - timedelta(hours=1), open_,
                                                                                {"JPY", "CNY", "AUD", "NZD", "EUR", "GBP", "CHF", "All"})},
               {"title": f"US calendar {session:%a %b %d} (ET)", "items": _events(ctx.get("events", []), sess, sess + timedelta(days=1), {"USD"})}]
        posts = _posts(ctx.get("posts", []), slot - timedelta(hours=3))
        posts_title = "Market-moving posts since the US close"
    high = [e for c in cal for e in c["items"] if e["impact"] == "High"]
    head = " ".join(mb["headline"] for mb in markets) or "No GEX levels available yet."
    if high:
        head += f" {len(high)} high-impact event{'s' if len(high) > 1 else ''}: " + ", ".join(f"{e['title']} {e['day']} {e['clock']}" for e in high[:3]) + "."
    return {"kind": kind, "title": TITLES[kind], "slot": slot.isoformat(), "session": session.isoformat(),
            "generated_at": now.isoformat(), "late": (now - slot).total_seconds() > 30 * 60,
            "headline": head, "markets": markets, "calendar": cal, "posts": {"title": posts_title, "items": posts},
            "note": "Model estimates from options positioning, not predictions or trading advice."}
