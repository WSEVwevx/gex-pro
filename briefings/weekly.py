"""The weekly recap: how prices moved over one trading week, in fewer than 10 sentences.

Written from daily bars only, so every sentence is a measured fact: nothing here guesses why a market moved.

data (from the app shell, see gexpro/context.py):
  {"indexes": {"S&P 500": {"YYYY-MM-DD": {"open", "high", "low", "close"}}, "Nasdaq-100": ..., "Dow": ...,
               "Russell 2000": ..., "VIX": ...},
   "stocks": [{"symbol", "name", "bars": {date: bar}}, ...]}     the largest index weights
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from .schedule import TITLES

MAIN = "S&P 500"
TECH = "Nasdaq-100"
OTHERS = ("Dow", "Russell 2000")
GAP_MIN = 1.0           # % from the previous close: smaller opening gaps are not worth a sentence
IN_LINE = 0.25          # % points: closer than this, the Nasdaq-100 and S&P 500 moved together


def _week(bars: dict, end: date) -> Optional[tuple[list, float]]:
    """(the week's [date, bar] rows, the close before the week), or None without a final bar for `end`."""
    monday = end - timedelta(days=end.weekday())
    rows = sorted((d, b) for d, b in (bars or {}).items() if monday.isoformat() <= d <= end.isoformat())
    before = sorted(d for d in (bars or {}) if d < monday.isoformat())
    if not rows or not before or rows[-1][0] != end.isoformat():
        return None
    return rows, bars[before[-1]]["close"]


def _pct(a: float, b: float) -> float:
    return (b / a - 1) * 100


def _day(d: str) -> str:
    return date.fromisoformat(d).strftime("%A")


def _move(name: str, chg: float, close: float) -> str:
    verb = "rose" if chg > 0 else "fell" if chg < 0 else "was unchanged"
    return f"{name} {verb}" + (f" {abs(chg):.1f}%" if chg else "") + f" to {close:,.0f}"


def stats(bars: dict, end: date) -> Optional[dict]:
    w = _week(bars, end)
    if not w:
        return None
    rows, prev = w
    closes = [prev] + [b["close"] for _, b in rows]
    days = [(d, _pct(closes[i], closes[i + 1])) for i, (d, _) in enumerate(rows)]
    gaps = [(d, _pct(closes[i], b["open"])) for i, (d, b) in enumerate(rows)]
    hi = max(rows, key=lambda r: r[1]["high"])
    lo = min(rows, key=lambda r: r[1]["low"])
    return {"chg": _pct(prev, closes[-1]), "close": closes[-1], "prev": prev, "days": days, "gaps": gaps,
            "high": hi[1]["high"], "high_day": hi[0], "low": lo[1]["low"], "low_day": lo[0]}


def recap(data: Optional[dict], end: date, slot: datetime, now: datetime) -> Optional[dict]:
    """The recap for the week ending on trading day `end`; None until the two main indexes have that day's bar."""
    idx = (data or {}).get("indexes") or {}
    s, n = stats(idx.get(MAIN) or {}, end), stats(idx.get(TECH) or {}, end)
    if not s or not n:
        return None
    other = {k: stats(idx.get(k) or {}, end) for k in OTHERS}
    vix = stats(idx.get("VIX") or {}, end)
    lines = [f"The {_move(MAIN, round(s['chg'], 1), s['close'])} this week, and the {_move(TECH, round(n['chg'], 1), n['close'])}."]
    have = [(k, v) for k, v in other.items() if v]
    if have:
        lines.append("The " + ", and the ".join(_move(k, round(v["chg"], 1), v["close"]) for k, v in have) + ".")
    ups = sum(c > 0 for _, c in s["days"])
    best, worst = max(s["days"], key=lambda x: x[1]), min(s["days"], key=lambda x: x[1])
    lines.append(f"The S&P 500 had {ups} up {'day' if ups == 1 else 'days'} out of {len(s['days'])}, with its best session on {_day(best[0])} ({best[1]:+.1f}%) and its worst on {_day(worst[0])} ({worst[1]:+.1f}%).")
    span = s["high"] - s["low"]
    where = (s["close"] - s["low"]) / span if span else 0.5
    place = "near the bottom of that range" if where < 0.25 else "near the top of that range" if where > 0.75 else "in the middle of that range"
    lines.append(f"It traded between {s['low']:,.0f} and {s['high']:,.0f}, with the high on {_day(s['high_day'])} and the low on {_day(s['low_day'])}, and closed {place}.")
    gap = max(s["gaps"], key=lambda x: abs(x[1]))
    if abs(gap[1]) >= GAP_MIN:
        lines.append(f"The biggest opening gap was {_day(gap[0])}, {gap[1]:+.1f}% from the previous close.")
    diff = n["chg"] - s["chg"]
    lines.append("The Nasdaq-100 and S&P 500 moved roughly in line." if abs(diff) < IN_LINE
                 else f"The Nasdaq-100 {'beat' if diff > 0 else 'lagged'} the S&P 500 by {abs(diff):.1f} percentage points.")
    if vix:
        lines.append(f"The VIX {'rose' if vix['close'] > vix['prev'] else 'fell' if vix['close'] < vix['prev'] else 'held'} from {vix['prev']:.1f} to {vix['close']:.1f}.")
    moves = []
    for st in (data.get("stocks") or []):
        v = stats(st.get("bars") or {}, end)
        if v:
            moves.append((v["chg"], st["symbol"]))
    moves.sort()
    if len(moves) >= 4:
        lines.append(f"Among the biggest stocks, {moves[-1][1]} ({moves[-1][0]:+.1f}%) did best and {moves[0][1]} ({moves[0][0]:+.1f}%) did worst.")
    chips = [{"name": k, "close": v["close"], "pct": round(v["chg"], 2)} for k, v in ((MAIN, s), (TECH, n), *have, ("VIX", vix)) if v]
    return {"kind": "weekly", "title": TITLES["weekly"], "slot": slot.isoformat(), "session": end.isoformat(),
            "generated_at": now.isoformat(), "headline": " ".join(lines), "sentences": len(lines), "indexes": chips,
            "markets": [], "calendar": [], "posts": {}}
