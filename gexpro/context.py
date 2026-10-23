"""The data snapshot other components (today: briefings) read, built from the GEX and feeds components.

This is the only place that knows both sides, so feature packages stay independent of each other.
Shape: see briefings/compose.py.
"""
from __future__ import annotations

from datetime import datetime, timezone


def _p(v):
    return v.get("price") if isinstance(v, dict) else v


def market_snapshot(w) -> dict | None:
    r = w.result
    if not r or r["summary"].get("status") == "UNAVAILABLE":
        return None
    s = r["summary"]
    L = r.get("mapped") or s                          # futures prices when mapped, else index prices
    X = L.get("extras") or {}
    em, near, b = X.get("expected_move") or {}, X.get("nearest") or {}, r.get("bias")
    return {
        "market": w.cfg.market, "price": L.get("futures_equiv_of_ref") or s.get("ref_price"),
        "asof": s.get("asof"), "quality": s.get("ref_quality"),
        "options": (s.get("options_source") or w.cfg.source) + ("+" + s["etf"] if s.get("etf") else ""),
        "regime": s.get("regime"), "net": s.get("net"),
        "zero_gamma": _p(L.get("zero_gamma")), "call_wall": _p(L.get("call_wall")),
        "put_wall": _p(L.get("put_wall")), "abs_gamma": _p(L.get("abs_gamma")),
        "nearest": {"label": near.get("label"), "zero_gamma": _p(near.get("zero_gamma")),
                    "call_wall": _p(near.get("call_wall")), "put_wall": _p(near.get("put_wall"))},
        "em": {"anchor": em.get("anchor_fut", em.get("anchor")), "daily": em.get("daily_points_fut", em.get("daily_points")),
               "weekly": em.get("weekly_points_fut", em.get("weekly_points")), "weekly_expiry": em.get("weekly_expiry")},
        "bias": {k: b.get(k) for k in ("bias", "confidence", "day_type", "target", "range", "summary")} if b else None,
        "delta": r.get("delta"),
    }


def snapshot(gex, feeds) -> dict:
    """gex: GexComponent (its workers), feeds: FeedsComponent."""
    markets = [m for m in (market_snapshot(w) for w in gex.workers.values()) if m]
    try:
        events = feeds.calendar.get().get("events", [])
    except Exception:
        events = []
    try:
        posts = feeds.posts.get().get("posts", [])
    except Exception:
        posts = []
    return {"now": datetime.now(timezone.utc).isoformat(), "markets": markets, "events": events, "posts": posts}
