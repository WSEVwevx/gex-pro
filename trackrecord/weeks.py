"""A week of 9:30 pastes as one TradingView paste, for backtesting a whole week at once.

The indicator draws each day's 9:30 levels across that day's 09:30-16:00 ET only (token W), so five days
fit on one chart without one day's levels running over another's. Per day:
  yyyymmdd:zero gamma:call wall:put wall:abs gamma:C1/C2/C3:P1/P2/P3      (index points; empty = none)
The paste keeps the identifying tokens of the week's last paste (market, source, mapping) so the chart maps
it like any paste, and marks it as a backtest of the last day (bt), so it is never "stale" and stays silent.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

HEADER = ("fv", "prov", "mkt", "src", "etf", "kind", "tv", "map", "fac", "off", "ts", "q", "oi", "gk", "model", "unit", "st")


def _tokens(text: str) -> dict:
    out = {}
    for t in (text or "").split(";"):
        k, sep, v = t.partition("=")
        if sep:
            out[k] = v
    return out


def _ranked(r: str, side: str, n: int = 3) -> str:
    out = [item[1:].split(":")[0] for item in (r or "").split(",") if item[:1] == side]
    return "/".join(p for p in out[:n] if p)


def day_entry(text: str) -> str:
    t = _tokens(text)
    return ":".join([t.get("bt", ""), t.get("zg", ""), t.get("cw", ""), t.get("pw", ""), t.get("ag", ""),
                     _ranked(t.get("R", ""), "C"), _ranked(t.get("R", ""), "P")])


def week_paste(texts: Iterable[str]) -> str:
    """texts: one market's 9:30 pastes for the week, any order. Days without a bt mark are skipped."""
    days = sorted((t for t in texts if _tokens(t).get("bt")), key=lambda t: _tokens(t)["bt"])
    if not days:
        return ""
    last = _tokens(days[-1])
    head = ";".join(f"{k}={last[k]}" for k in HEADER if k in last)
    return f"GEX1;{head};bt={last['bt']};W={','.join(day_entry(t) for t in days)};END"


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weeks(pastes: list[dict]) -> list[dict]:
    """[{"week": Monday (ISO), "market", "days", "paste"}], newest week first, from [{"session", "market", "paste"}]."""
    groups: dict = {}
    for p in pastes:
        try:
            wk = monday(date.fromisoformat(p["session"])).isoformat()
        except (KeyError, ValueError):
            continue
        groups.setdefault((wk, p["market"]), []).append(p["paste"])
    out = []
    for (wk, m), texts in groups.items():
        text = week_paste(texts)
        if text:
            out.append({"week": wk, "market": m, "days": len(texts), "paste": text})
    return sorted(out, key=lambda x: (x["week"], x["market"]), reverse=True)
