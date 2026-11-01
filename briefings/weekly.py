"""The weekly recap: how prices moved over one trading week and what was behind it, in fewer than 10 sentences.

Every sentence is measured: index moves from daily bars, each stock's share of the index move from its weight,
sectors from their funds, earnings and economic data from their calendars. "Behind it" means weight and timing:
what the arithmetic and the calendar show, not proof of cause. Headlines are shown as reported, with their source.

data (from the app shell, see gexpro/context.py); only the two main indexes are required:
  {"indexes": {"S&P 500": {date: {"open", "high", "low", "close"}}, "Nasdaq-100": ..., "Dow": ..., "Russell 2000": ..., "VIX": ...},
   "markets": {"10-year yield": bars, "dollar": bars, "oil": bars}, "sectors": {"Technology": bars, ...},
   "weights": {"S&P 500": {symbol: weight %}, "Nasdaq-100": {...}}, "closes": {symbol: {date: close}},
   "earnings": [{"date", "symbol", "time", "surprise"}], "economy": [{"date", "title", "actual", "consensus"}],
   "headlines": callable(date) -> [{"day", "title", "source", "url"}],
   "positioning": {"ES": {"asof", "groups": [{"key", "rank"}, ...]}, "NQ": ...}}     CFTC, see feeds/positioning.py
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from .schedule import TITLES

VERSION = 4             # a stored recap from an older version is rewritten while its week is current
MAIN = "S&P 500"
TECH = "Nasdaq-100"
OTHERS = ("Dow", "Russell 2000")
GAP_MIN = 1.0           # % from the previous close: smaller opening gaps are not worth mentioning
BIG_STOCK = 0.05        # % points of an index move: earnings smaller than this are not mentioned
MAX_DATA = 3            # economic releases named
SHARE_CLASS = {"GOOG": "GOOGL", "FOX": "FOXA", "NWS": "NWSA"}      # one company, two tickers: counted once


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


def _week_chg(closes: dict, end: date) -> Optional[float]:
    """A stock's % change over the week from its daily closes, or None without the week's first and last closes."""
    w = _week({d: {"close": c} for d, c in (closes or {}).items()}, end)
    return _pct(w[1], w[0][-1][1]["close"]) if w else None


def _one_ticker(weights: dict) -> dict:
    out: dict = {}
    for sym, w in (weights or {}).items():
        key = SHARE_CLASS.get(sym, sym)
        out[key] = out.get(key, 0) + w
    return out


def _contributors(weights: dict, closes: dict, end: date) -> list:
    """[(share of the index's move in % points, stock's % change, symbol)], most negative first."""
    out = []
    for sym, w in _one_ticker(weights).items():
        chg = _week_chg(closes.get(sym), end)
        if chg is not None:
            out.append((w * chg / 100, chg, sym))
    return sorted(out)


def _leaders(st: dict, rows: list) -> list:
    """The two stocks that did most to the index, on the side of its move."""
    if len(rows) < 10:
        return []
    side = rows[:2] if st["chg"] < 0 else rows[::-1][:2]
    return [r for r in side if (r[0] < 0) == (st["chg"] < 0)]


def _leader_text(n: dict, s: dict, rows: dict) -> Optional[str]:
    """Each stock's weight times its move, so the numbers are close to, not exactly, its part of the index move."""
    a, b = _leaders(n, rows[TECH]), _leaders(s, rows[MAIN])
    if not a and not b:
        return None
    who = lambda side: " and ".join(f"{sym} ({c:+.1f}%)" for _, c, sym in side)
    pts = lambda side: f"{sum(r[0] for r in side):+.2f}"
    if a and b and [r[2] for r in a] == [r[2] for r in b]:
        return f"{who(a)} accounted for about {pts(a)} points of the {TECH}'s {n['chg']:+.1f}% and {pts(b)} of the {MAIN}'s {s['chg']:+.1f}%."
    parts = [f"{who(x)} accounted for about {pts(x)} points of the {name}'s {st['chg']:+.1f}%" for x, name, st in ((a, TECH, n), (b, MAIN, s)) if x]
    return "; ".join(parts) + "."


def _reaction(e: dict, sym_closes: dict, days: list) -> Optional[tuple[str, float, bool]]:
    """(the session a report moved, the stock's % change that session, whether the report's time is known)."""
    ds = sorted(sym_closes)
    def move(day):
        if day not in days or day not in sym_closes:
            return None
        prior = [d for d in ds if d < day]
        return _pct(sym_closes[prior[-1]], sym_closes[day]) if prior else None
    after = [d for d in ds if d > e["date"]]
    same, nxt = (e["date"], move(e["date"])), (after[0], move(after[0])) if after else (None, None)
    if e.get("time") == "time-pre-market":
        pick = same
    elif e.get("time") == "time-after-hours":
        pick = nxt
    else:                                                       # the calendar gives no time: the session that moved more
        pick = max((same, nxt), key=lambda x: abs(x[1]) if x[1] is not None else -1)
    return (pick[0], pick[1], e.get("time") in ("time-pre-market", "time-after-hours")) if pick[1] is not None else None


def _earnings(data: dict, end: date, days: list) -> Optional[str]:
    """The reports that moved the index most, by the stock's weight times its move that session."""
    weights, closes = {k: _one_ticker((data.get("weights") or {}).get(k)) for k in (MAIN, TECH)}, data.get("closes") or {}
    best: dict = {}
    for e in data.get("earnings") or []:
        sym = e.get("symbol")
        w = 0 if sym in SHARE_CLASS else max(weights[k].get(sym, 0) for k in (MAIN, TECH))
        got = _reaction(e, closes.get(sym) or {}, days) if w else None
        if got and w * abs(got[1]) / 100 >= BIG_STOCK and (sym not in best or w * abs(got[1]) > best[sym][0]):
            best[sym] = (w * abs(got[1]), sym, got[0], got[1], got[2], e.get("surprise"))
    if not best:
        return None
    parts = []
    for _, sym, day, mv, timed, sur in sorted(best.values(), reverse=True)[:2]:
        vs = "" if sur is None else f" that {'beat' if sur > 0 else 'missed' if sur < 0 else 'matched'} estimates" + (f" by {abs(sur):.0f}%" if sur else "")
        parts.append(f"{sym} {'rose' if mv > 0 else 'fell'} {abs(mv):.1f}% on {_day(day)} {'after' if timed else 'around'} earnings{vs}")
    return " and ".join(parts) + "."


def _economy(data: dict) -> Optional[str]:
    seen, parts = set(), []
    for e in sorted(data.get("economy") or [], key=lambda x: x.get("rank", 99)):       # the most important releases first
        if e["title"] in seen or len(parts) >= MAX_DATA:
            continue
        seen.add(e["title"])
        vs = f" against {e['consensus']} expected" if e.get("consensus") else ""
        fed = "interest rate" in e["title"].lower()
        parts.append((f"the Fed set rates at {e['actual']}" if fed else f"{e['title']} came in at {e['actual']}") + vs + f" on {_day(e['date'])}")
    return "; ".join(parts) + "." if parts else None


def _backdrop(data: dict, end: date, vix: Optional[dict]) -> Optional[str]:
    parts = []
    if vix:
        parts.append(f"the VIX {'rose' if vix['close'] > vix['prev'] else 'fell' if vix['close'] < vix['prev'] else 'held'} from {vix['prev']:.1f} to {vix['close']:.1f}")
    m = data.get("markets") or {}
    y, oil, usd = stats(m.get("10-year yield") or {}, end), stats(m.get("oil") or {}, end), stats(m.get("dollar") or {}, end)
    if y:
        parts.append(f"the 10-year yield went from {y['prev']:.2f}% to {y['close']:.2f}%")
    if oil:
        parts.append(f"oil {'rose' if oil['chg'] > 0 else 'fell'} {abs(oil['chg']):.1f}%")
    if usd:
        parts.append(f"the dollar {'rose' if usd['chg'] > 0 else 'fell'} {abs(usd['chg']):.1f}%")
    if not parts:
        return None
    text = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] + _funds(data) + "."
    return text[0].upper() + text[1:]


def _funds(data: dict) -> str:
    """Where leveraged funds' net position sits in its own 3-year range, as a closing clause."""
    parts, asof = [], ""
    for m, s in sorted((data.get("positioning") or {}).items()):
        rank = next((g["rank"] for g in s.get("groups") or [] if g.get("key") == "lev_money"), None)
        if rank is not None:
            parts.append(f"{rank}% in {m}")
            asof = s.get("asof") or asof
    if not parts:
        return ""
    d = date.fromisoformat(asof)
    when = f"{d:%b} {d.day}"
    return f"; leveraged funds' net position was above {' and '.join(parts)} of the past 3 years (CFTC, {when})"


def recap(data: Optional[dict], end: date, slot: datetime, now: datetime) -> Optional[dict]:
    """The recap for the week ending on trading day `end`; None until the two main indexes have that day's bar."""
    data = data or {}
    idx = data.get("indexes") or {}
    s, n = stats(idx.get(MAIN) or {}, end), stats(idx.get(TECH) or {}, end)
    if not s or not n:
        return None
    other = {k: stats(idx.get(k) or {}, end) for k in OTHERS}
    vix = stats(idx.get("VIX") or {}, end)
    have = [(k, v) for k, v in other.items() if v]
    weights, closes = data.get("weights") or {}, data.get("closes") or {}
    rows = {k: _contributors(weights.get(k), closes, end) for k in (MAIN, TECH)}

    lines = [f"The {_move(MAIN, round(s['chg'], 1), s['close'])} this week, and the {_move(TECH, round(n['chg'], 1), n['close'])}."]
    second = ", and the ".join(_move(k, round(v["chg"], 1), v["close"]) for k, v in have)
    ups = sum(r[1] > 0 for r in rows[MAIN])
    breadth = f"{ups} of {len(rows[MAIN])} S&P 500 stocks rose" if len(rows[MAIN]) >= 100 else ""
    if second or breadth:
        lines.append(("The " + second if second else breadth.capitalize()) + (f", while {breadth}" if second and breadth else "") + ".")
    up_days = sum(c > 0 for _, c in s["days"])
    best, worst = max(s["days"], key=lambda x: x[1]), min(s["days"], key=lambda x: x[1])
    lines.append(f"The S&P 500 had {up_days} up {'day' if up_days == 1 else 'days'} out of {len(s['days'])}, with its best session on {_day(best[0])} ({best[1]:+.1f}%) and its worst on {_day(worst[0])} ({worst[1]:+.1f}%).")
    span = s["high"] - s["low"]
    where = (s["close"] - s["low"]) / span if span else 0.5
    place = "near the bottom of that range" if where < 0.25 else "near the top of that range" if where > 0.75 else "in the middle of that range"
    gap = max(s["gaps"], key=lambda x: abs(x[1]))
    gap_txt = f", and the biggest opening gap was {_day(gap[0])}, {gap[1]:+.1f}% from the previous close" if abs(gap[1]) >= GAP_MIN else ""
    lines.append(f"It traded between {s['low']:,.0f} and {s['high']:,.0f} and closed {place}{gap_txt}.")
    lead = _leader_text(n, s, rows)
    if lead:
        lines.append(lead)
    secs = sorted((v["chg"], k) for k, v in ((k, stats(b, end)) for k, b in (data.get("sectors") or {}).items()) if v)
    if len(secs) >= 4:
        lines.append(f"By sector, {secs[-1][1]} did best ({secs[-1][0]:+.1f}%) and {secs[0][1]} did worst ({secs[0][0]:+.1f}%).")
    days = [d for d, _ in s["days"]]
    for extra in (_earnings(data, end, days), _economy(data), _backdrop(data, end, vix)):
        if extra:
            lines.append(extra[0].upper() + extra[1:])

    news = []
    get_news = data.get("headlines")
    if get_news:
        for d in dict.fromkeys(x[0] for x in (worst, best)):
            try:
                news += get_news(date.fromisoformat(d)) or []
            except Exception:                                   # headlines are extra; the recap never waits for them
                continue
    chips = [{"name": k, "close": v["close"], "pct": round(v["chg"], 2)} for k, v in ((MAIN, s), (TECH, n), *have, ("VIX", vix)) if v]
    return {"kind": "weekly", "title": TITLES["weekly"], "slot": slot.isoformat(), "session": end.isoformat(), "version": VERSION,
            "generated_at": now.isoformat(), "headline": " ".join(lines[:9]), "sentences": len(lines[:9]), "indexes": chips,
            "headlines": news, "markets": [], "calendar": [], "posts": {}}
