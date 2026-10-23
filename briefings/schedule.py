"""When each briefing is due (US Eastern time).

  nyam : 09:00 ET on every trading day, for that day's session. Valid until 16:00 ET.
  asia : 19:00 ET on evenings whose next calendar day is a trading day (Sunday-Thursday, not before a
         holiday), for the next day's session. Globex is open again and Asia is starting (Tokyo opens at
         19:00 ET in winter, 20:00 in summer). Valid until 09:00 ET next morning, when the NY AM briefing takes over.

A briefing missed because the app was off is written as soon as it starts, as long as its window is
still open (marked as late). `is_trading_day(date) -> bool` comes from the app shell.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
KINDS = ("nyam", "asia")
TITLES = {"nyam": "NY AM briefing", "asia": "Asia session briefing"}
SLOT = {"nyam": time(9, 0), "asia": time(19, 0)}


def _slot_for_day(kind: str, d: date, is_trading_day: Callable) -> Optional[tuple[datetime, date, datetime]]:
    """(slot time, session date, window end) if `kind` has a slot on calendar day d."""
    if kind == "nyam":
        if not is_trading_day(d):
            return None
        return datetime.combine(d, SLOT[kind], NY), d, datetime.combine(d, time(16, 0), NY)
    nxt = d + timedelta(days=1)
    if not is_trading_day(nxt):
        return None
    return datetime.combine(d, SLOT[kind], NY), nxt, datetime.combine(nxt, SLOT["nyam"], NY)   # NY AM takes over


def latest(kind: str, now: datetime, is_trading_day: Callable) -> Optional[tuple[datetime, date, datetime]]:
    """The most recent slot at or before `now` (looks back 10 days)."""
    d = now.astimezone(NY).date()
    for back in range(11):
        s = _slot_for_day(kind, d - timedelta(days=back), is_trading_day)
        if s and s[0] <= now:
            return s
    return None


def due(kind: str, now: datetime, is_trading_day: Callable) -> Optional[tuple[datetime, date]]:
    """(slot, session) whose briefing should exist right now, or None outside every window."""
    s = latest(kind, now, is_trading_day)
    return (s[0], s[1]) if s and now < s[2] else None


def next_slot(kind: str, now: datetime, is_trading_day: Callable) -> Optional[datetime]:
    d = now.astimezone(NY).date()
    for ahead in range(11):
        s = _slot_for_day(kind, d + timedelta(days=ahead), is_trading_day)
        if s and s[0] > now:
            return s[0]
    return None


def slot_id(kind: str, slot: datetime) -> str:
    return f"{slot.astimezone(NY):%Y-%m-%d}-{kind}"
