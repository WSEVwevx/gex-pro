"""Session context from the saved snapshots: what changed today, where the levels stood at the open, and how
price has reacted at each kind of level.

  key_levels(summary)     the levels a trader watches, from one snapshot (index prices):
                          C1 C2 P1 P2 Ab1 (first expiry, the indicator's 'auto' chain), flip (its zero gamma),
                          ZG CW PW (all expiries) and the regime
  changes(snaps)          the day's steady changes, e.g. C1 29800 -> 29885 at 10:42 ET; a change counts once
                          it holds for two snapshots, so one-snapshot flickers are ignored
  open_levels(snaps)      the levels in the first snapshot at or after today's 09:30 ET cash open
  reaction_stats(...)     every past touch of each level kind, replayed on futures candles: did price hold
                          (no close beyond it within an hour) and how far it moved back away (the bounce)

Everything stays in index prices except the stats, which are measured on futures candles with the futures
factor (prices) and reported in futures points.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Iterable, Optional

from . import marketcal

WATCH = ("C1", "C2", "P1", "P2", "Ab1", "flip", "ZG", "CW", "PW")
STAT_KINDS = ("C1", "P1", "Ab1", "flip", "ZG", "CW", "PW")


def _p(v):
    return v.get("price") if isinstance(v, dict) else v


def key_levels(s: dict) -> dict:
    """The watched levels from one summary (index prices); missing ones are left out."""
    out: dict = {"regime": s.get("regime")}
    n = (s.get("extras") or {}).get("nearest") or {}
    rk = n.get("ranked_etf") if (n.get("etf_share") or 0) >= 0.5 and n.get("ranked_etf") else n.get("ranked")
    rk = rk or {}
    for side, code, k in (("call", "C", 2), ("put", "P", 2), ("abs", "Ab", 1)):
        for i, x in enumerate((rk.get(side) or [])[:k]):
            out[f"{code}{i + 1}"] = _p(x)
    if _p(n.get("zero_gamma")) is not None:
        out["flip"] = _p(n["zero_gamma"])
    for k, key in (("ZG", "zero_gamma"), ("CW", "call_wall"), ("PW", "put_wall")):
        if _p(s.get(key)) is not None:
            out[k] = _p(s[key])
    return out


def session_start(now: datetime) -> datetime:
    """Start of the futures session that contains `now`: 18:00 ET on the previous evening."""
    t = now.astimezone(marketcal.NY)
    start = datetime.combine(t.date(), time(18), marketcal.NY)
    return start if t >= start else start - timedelta(days=1)


def summaries_since(folder: Path, since: datetime) -> list:
    """Saved summaries (not raw chains) with asof >= since, oldest first; only the day folders that can hold them."""
    out = []
    first = (since - timedelta(days=1)).strftime("%Y%m%d")
    for day in sorted(folder.glob("????????")):
        if not day.is_dir() or day.name < first:
            continue
        for f in sorted(day.glob("*.json")):
            if f.name.endswith(".chain.json"):
                continue
            try:
                s = json.loads(f.read_text(encoding="utf-8"))
                if datetime.fromisoformat(s["asof"]) >= since and s.get("status") != "UNAVAILABLE":
                    out.append(s)
            except (OSError, ValueError, KeyError):
                continue
    out.sort(key=lambda s: s["asof"])
    return out


def changes(snaps: Iterable[dict], limit: int = 40) -> list:
    """[{t, what, frm, to}] newest first: a watched level (or the regime) moved and the new value held for
    two snapshots in a row."""
    seq = [(s["asof"], key_levels(s)) for s in snaps]
    out = []
    for k in WATCH + ("regime",):
        cur = None
        vals = [(t, lv.get(k)) for t, lv in seq]
        for i, (t, v) in enumerate(vals):
            if v is None:
                continue
            if cur is None:
                cur = v
                continue
            nxt = vals[i + 1][1] if i + 1 < len(vals) else None
            if v != cur and nxt == v:
                out.append({"t": t, "what": k, "frm": cur, "to": v})
                cur = v
    out.sort(key=lambda c: c["t"], reverse=True)
    return out[:limit]


def open_levels(snaps: Iterable[dict], now: datetime) -> Optional[dict]:
    """Levels at today's cash open (the first snapshot within an hour after 09:30 ET), from 09:30 until the
    18:00 ET session change; None outside that window or if no snapshot was taken near the open."""
    t = now.astimezone(marketcal.NY)
    if not marketcal.is_trading_day(t.date()) or not time(9, 30) <= t.time() < time(18):
        return None
    o = datetime.combine(t.date(), time(9, 30), marketcal.NY)
    first = next((s for s in snaps if o <= datetime.fromisoformat(s["asof"]) <= o + timedelta(hours=1)), None)
    return dict(key_levels(first), asof=first["asof"]) if first else None


def reaction_stats(snaps: list, candles: list, factor: float, offset: float = 0.0,
                   tol_pct: float = 0.0002, break_pct: float = 0.0005, horizon: int = 12, gap: int = 6) -> dict:
    """{kind: {n, held, bounce}} from every touch of each level kind on the candles ([t, o, h, l, c], one bar
    each, e.g. 5 minutes).

    A touch: a bar reaching within tol of the level in force at that time (the latest snapshot before the
    bar), at least `gap` bars after the previous touch of that kind. Held: no close beyond the level by
    break_pct within `horizon` bars (an hour on 5-minute bars). Bounce: the furthest price then moved back
    away from the level on the side it came from, in futures points. Median bounce over held touches."""
    if not snaps or not candles or not factor:
        return {}
    seq = [(datetime.fromisoformat(s["asof"]).timestamp(), key_levels(s)) for s in snaps]
    res: dict = {k: {"n": 0, "held": 0, "b": []} for k in STAT_KINDS}
    last_touch = {k: -10 ** 9 for k in STAT_KINDS}
    j = -1
    for i, (t, o, h, lo, c) in enumerate(candles):
        while j + 1 < len(seq) and seq[j + 1][0] <= t:
            j += 1
        if j < 0 or i == 0:
            continue
        prev_close = candles[i - 1][4]
        for k in STAT_KINDS:
            v = seq[j][1].get(k)
            if v is None:
                continue
            lv = v * factor + offset
            tol, brk = lv * tol_pct, lv * break_pct
            if not (lo <= lv + tol and h >= lv - tol) or i - last_touch[k] < gap:
                continue
            last_touch[k] = i
            above = prev_close >= lv                        # approached from above: a support test
            after = candles[i + 1:i + 1 + horizon]
            if len(after) < horizon // 2:
                continue                                    # too recent to judge
            broke = any((x[4] < lv - brk) if above else (x[4] > lv + brk) for x in after)
            r = res[k]
            r["n"] += 1
            if not broke:
                r["held"] += 1
                r["b"].append(max((x[2] - lv) if above else (lv - x[3]) for x in after))
    return {k: {"n": r["n"], "held": r["held"], "bounce": round(statistics.median(r["b"]), 1) if r["b"] else None}
            for k, r in res.items() if r["n"]}


def stats_token(stats: dict) -> str:
    """S token for the paste: kind:touches:held:median bounce, e.g. C1:10:7:18.5,P1:6:4:22"""
    return ",".join(f"{k}:{v['n']}:{v['held']}:{'' if v['bounce'] is None else v['bounce']}" for k, v in stats.items())


def open_token(lv: dict) -> str:
    """O token: the open's levels in index prices, e.g. C1:29800.00,P1:29560.00,Ab1:29700.00,flip:29470.00"""
    return ",".join(f"{k}:{lv[k]:.2f}" for k in ("C1", "P1", "Ab1", "flip") if lv.get(k) is not None)
