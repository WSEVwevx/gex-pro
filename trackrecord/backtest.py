"""Historical backtest of the expected-move method, from implied-vol indexes (decades of free data).

The live track record can only start on the day GEX PRO began saving its levels, because free
historical option open interest does not exist. Implied volatility history does: VIX (S&P 500, since
1990) and VXN (Nasdaq-100, since 2009) are the 30-day implied vols of the same index options GEX PRO
reads. So the expected-move band is tested on every day since then, with the same convention GEX PRO
uses: em = previous close x IV x sqrt(calendar days to the session's close / 365).

This is a PROXY: GEX PRO's own band uses each day's nearest-expiration IV, which is usually higher
than the 30-day VIX on calm days and lower around events. Labelled as such on the page.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

from .score import rate

BIN = 0.25
EDGE = 3.0


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def days(bars: dict[str, dict], vol: dict[str, float], until: Optional[str] = None) -> list[dict]:
    """One graded row per session that has the previous session's close and vol index close."""
    ds = sorted(d for d in bars if until is None or d <= until)
    out = []
    for prev, d in zip(ds, ds[1:]):
        v = vol.get(prev)
        if not v:
            continue
        p, b = bars[prev]["close"], bars[d]
        gap = (date.fromisoformat(d) - date.fromisoformat(prev)).days
        em = p * v / 100 * math.sqrt(gap / 365)
        if em <= 0:
            continue
        out.append({"date": d, "gap": gap, "vol": v, "em": em, "move_em": (b["close"] - p) / em,
                    "range_em": (b["high"] - b["low"]) / em,
                    "close_in": abs(b["close"] - p) <= em,
                    "range_in": b["high"] <= p + em and b["low"] >= p - em,
                    "up": b["high"] > p + em, "down": b["low"] < p - em})
    return out


def _stats(rows: list[dict]) -> dict:
    n = len(rows)
    return {"n": n, "close_in": rate(r["close_in"] for r in rows), "range_in": rate(r["range_in"] for r in rows),
            "up_break": rate(r["up"] for r in rows), "down_break": rate(r["down"] for r in rows),
            "mean_abs_move_em": round(sum(abs(r["move_em"]) for r in rows) / n, 3) if n else None,
            "mean_range_em": round(sum(r["range_em"] for r in rows) / n, 3) if n else None,
            "avg_vol": round(sum(r["vol"] for r in rows) / n, 2) if n else None}


def run(underlying: str, vol_name: str, bars: dict[str, dict], vol: dict[str, float], until: Optional[str] = None) -> Optional[dict]:
    rows = days(bars, vol, until)
    if len(rows) < 30:
        return None
    years: dict[str, list] = {}
    for r in rows:
        years.setdefault(r["date"][:4], []).append(r)
    by_year = [dict(_stats(v), year=y) for y, v in sorted(years.items())]
    # vol regimes: quintiles of the vol index level
    vs = sorted(r["vol"] for r in rows)
    cuts = [vs[int(len(vs) * q / 5)] for q in range(1, 5)]
    buckets = [[] for _ in range(5)]
    for r in rows:
        buckets[sum(r["vol"] >= c for c in cuts)].append(r)
    edges = [vs[0]] + cuts + [vs[-1]]
    by_vol = [dict(_stats(b), lo=round(edges[i], 2), hi=round(edges[i + 1], 2)) for i, b in enumerate(buckets) if b]
    # distribution of close-to-close moves in expected moves, next to a normal curve
    nb = int(2 * EDGE / BIN)
    counts = [0] * nb
    for r in rows:
        counts[min(nb - 1, max(0, int((r["move_em"] + EDGE) / BIN)))] += 1
    normal = [round(len(rows) * (_ncdf(-EDGE + (i + 1) * BIN) - _ncdf(-EDGE + i * BIN)), 2) for i in range(nb)]
    normal[0] += round(len(rows) * _ncdf(-EDGE), 2)
    normal[-1] += round(len(rows) * (1 - _ncdf(EDGE)), 2)
    return {"underlying": underlying, "vol_index": vol_name, "start": rows[0]["date"], "end": rows[-1]["date"],
            "overall": _stats(rows), "recent": _stats(rows[-252:]),
            "after_gap": {"one_day": _stats([r for r in rows if r["gap"] == 1]),
                          "weekend_or_holiday": _stats([r for r in rows if r["gap"] > 1])},
            "by_year": by_year, "by_vol": by_vol,
            "hist": {"bin": BIN, "edge": EDGE, "counts": counts, "normal": normal},
            "last": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()} for r in rows[-60:]]}
