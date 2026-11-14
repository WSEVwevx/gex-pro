"""The Bias chart's replay: the levels the site showed at each minute of one session, and price, with no hindsight.

  build(folder, market, method, candles, now)   the session timeline (dict, sent as JSON)

Which session: the one in progress, or after its close (and before the next open) the last one.
Levels: a saved snapshot counts from the minute it was FETCHED (its `asof`), never from Cboe's data time: the data
is 15 minutes delayed, so placing it at its data time would show levels before the site had them. Each snapshot is
mapped to futures with its own factor, saved beside it since 2026-11-14 (`futures_map`). Older snapshots were saved
without it: their factor is estimated from the futures bar at the index price's own time (flagged, and the page
says so). A snapshot with neither is left out, and the levels before it are held: gaps stay visible.
Rows are written only when a level changes: [minute, zero gamma, call wall, put wall, abs gamma, 0DTE max pain,
estimated (1/0), moved (bit c set when column c's OPTIONS level changed, not just the futures basis under it)].
`seen` lists every snapshot's fetch time, for the "levels from" age.
Price: 1-minute futures bars (the heatmap's, no extra request); a bar is shown once it has closed.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import marketcal
from .bias import OPEN
from .mapping import FUTURES, round_to_tick
from .session import summaries_since

COLS = ("Zero gamma", "Call wall", "Put wall", "Abs gamma", "Max pain 0DTE")
LOOKBACK = timedelta(hours=18)          # the last snapshot before the open: the levels shown at the open


def session_bounds(now: datetime) -> tuple[datetime, datetime]:
    """(open, close) of the session in progress, or of the last one."""
    d = now.astimezone(marketcal.NY).date()
    while True:
        if marketcal.is_trading_day(d):
            o = datetime.combine(d, OPEN, marketcal.NY)
            if o <= now:
                return o, datetime.combine(d, marketcal.rth_close(d), marketcal.NY)
        d -= timedelta(days=1)


def _p(v):
    return v.get("price") if isinstance(v, dict) else v


def _estimate(s: dict, bars: dict, method: str) -> Optional[tuple[float, float]]:
    """(factor, offset) from the futures bar holding the index price's own time, for snapshots saved without one."""
    try:
        rt, ref = datetime.fromisoformat(s["ref_time"]), float(s["ref_price"])
    except (KeyError, TypeError, ValueError):
        return None
    c = bars.get(int(rt.timestamp()) // 60 * 60)
    if not c or not ref > 0:
        return None
    return (c / ref, 0.0) if method == "ratio" else (1.0, c - ref)


def build(folder: Path, market: str, method: str, candles: list, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    o, c = session_bounds(now)
    T = round((c - o).total_seconds() / 60)
    end = min(now, c)
    tick = FUTURES[market].tick_size
    bars = {int(b[0]): b[4] for b in candles or []}
    rows: list = []
    seen: list = []
    estimated = 0
    prev_raw = None
    for s in summaries_since(folder, o - LOOKBACK):
        t = datetime.fromisoformat(s["asof"])
        if t > end:
            break
        fm = s.get("futures_map")
        if fm and fm.get("factor"):
            f, off, est = fm["factor"], fm.get("offset") or 0.0, 0
        else:
            got = _estimate(s, bars, method)
            if not got:
                continue
            (f, off), est = got, 1
        raw = [_p(s.get("zero_gamma")), _p(s.get("call_wall")), _p(s.get("put_wall")), _p(s.get("abs_gamma")), s.get("mp0")]
        vals = [None if v is None else round_to_tick(v * f + off, tick) for v in raw]
        moved = sum(1 << i for i, v in enumerate(raw) if prev_raw is not None and v != prev_raw[i])
        prev_raw = raw
        sec = (t - o).total_seconds()
        m = max(0, math.ceil(sec / 60))                 # visible from the first whole minute at or after the fetch
        if sec < 0:                                     # before the open: only the last one counts (shown at 09:30)
            seen[:] = []
            rows[:] = []
            estimated = 0
            moved = 0                                   # a change before the open is not a move during the session
        seen.append(round(sec))
        estimated += est
        row = [m, *vals, est, moved]
        if rows and rows[-1][0] == m:
            row[-1] |= rows[-1][-1]                     # both became visible at the same minute
            rows[-1] = row
        elif not rows or rows[-1][1:6] != row[1:6]:
            rows.append(row)
    price = []
    for b in candles or []:
        m = (b[0] - o.timestamp()) / 60
        if 0 <= m < T and b[0] + 60 <= end.timestamp():
            price.append([int(m), b[4]])
    return {"market": market, "cols": list(COLS), "tick": tick,
            "session": {"open": o.isoformat(), "close": c.isoformat(), "minutes": T,
                        "live": o <= now < c, "now_minute": min(T, int((end - o).total_seconds() // 60))},
            "rows": rows, "seen": seen, "price": price, "estimated": estimated}
