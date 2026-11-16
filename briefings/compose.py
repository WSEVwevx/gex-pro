"""Writes a session brief from a plain data snapshot: the NY AM brief and the Asia brief share one format
(morning.py: five blocks of computed facts). Rule-based text: the same data always gives the same words.

Snapshot shape (built by the app shell, gexpro/context.py):
  {"now": iso,
   "markets": [{"market": "NQ", "price": 29107.5, "asof": iso, "quality": "DL", "options": "NDX+QQQ",
                "regime": "POSITIVE|NEGATIVE|INDETERMINATE", "net": float ($ per 1% move),
                "zero_gamma", "call_wall", "put_wall", "abs_gamma": float | None,
                "nearest": {"label": "0DTE" | "next MM-DD", "zero_gamma", "call_wall", "put_wall"},
                "em": {"anchor", "daily", "weekly", "weekly_expiry"},
                "factor", "offset": futures = index * factor + offset,
                "prev": the levels at the previous close, or None (see morning.py)}],
   "events": [{"title", "country", "time": iso, "impact", "forecast", "previous"}]}
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from . import morning
from .schedule import NY


def _events(events: list, start: datetime, end: datetime, currencies: Optional[set], impacts=("High", "Medium")) -> list:
    out = []
    for e in events:
        try:
            t = datetime.fromisoformat(e["time"]).astimezone(NY)
        except (KeyError, ValueError, TypeError):
            continue
        if start <= t < end and e.get("impact") in impacts and (currencies is None or e.get("country") in currencies):
            fp = " · ".join(x for x in (f"F {e['forecast']}" if e.get("forecast") else "", f"P {e['previous']}" if e.get("previous") else "") if x)
            out.append({"time": t.isoformat(), "clock": t.strftime("%I:%M %p").lstrip("0"), "day": t.strftime("%a"), "country": e.get("country"),
                        "impact": e.get("impact"), "title": e.get("title"), "detail": fp})
    return sorted(out, key=lambda x: x["time"])


def compose(kind: str, ctx: dict, slot: datetime, session: date, record: Optional[list] = None, past: Optional[list] = None) -> dict:
    """kind: "nyam" or "asia". `record`: the Track record's sessions; `past`: earlier briefs (both for the history lines)."""
    return morning.compose_brief(kind, ctx, slot, session, record, past, events_fn=_events)
