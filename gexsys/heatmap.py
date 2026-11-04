"""The heatmap page's data: futures candles plus the GEX history drawn underneath them.

  candles   NQ / ES futures from Yahoo Finance's public chart data (about 10 minutes delayed)
  columns   one per saved snapshot: net GEX by price band ($M per 1%), from the snapshot's "heat"
            profile; older snapshots without it fall back to the relative profile (marked rel)
  levels    zero gamma and the call / put walls at each snapshot, as step lines

Snapshot prices are index points; they are mapped to futures with the worker's current factor (the
basis moves only slowly over a few days, so this is close, not exact).
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("gexsys.heatmap")
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={tf}&range={rng}"
SYMBOL = {"NQ": "NQ%3DF", "ES": "ES%3DF"}
RANGE = {"1m": "2d", "5m": "5d", "15m": "10d"}
MAX_COLUMNS = 700


def parse_candles(raw: bytes) -> list:
    """[[unix seconds, open, high, low, close], ...] without empty bars."""
    r = json.loads(raw)["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(r.get("timestamp") or []):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None not in (o, h, l, c) and min(o, h, l, c) > 0:
            out.append([int(t), round(o, 2), round(h, 2), round(l, 2), round(c, 2)])
    return clean_candles(out)


def clean_candles(bars: list) -> list:
    """Fix bad prints: Yahoo sometimes sends a bar that OPENS at a stale price far from the market, and that
    stale open is also its high or low (e.g. 2026-10-30 15:00 ET, NQ open = high = 29562 with the market at
    28240). A bar's open counts as bad when it is more than 10 typical bar ranges AND 1% of price away from
    its own close, the previous close and the next open; it is set to the previous close, and the high or low
    it made is cut back to the bar's real prices. Real spikes open near the previous close and stay as they
    are, wicks and all (the 2025-04-07 headline spike, for example)."""
    if len(bars) < 3:
        return bars
    ranges = sorted(b[2] - b[3] for b in bars)
    typical = ranges[len(ranges) // 2] or min((r for r in ranges if r > 0), default=0)
    for i, b in enumerate(bars):
        t, o, h, low, c = b
        ref = [c] + ([bars[i - 1][4]] if i else []) + ([bars[i + 1][1]] if i + 1 < len(bars) else [])
        limit = max(10 * typical, 0.01 * c)
        if min(ref) - limit <= o <= max(ref) + limit:
            continue
        new_o = bars[i - 1][4] if i else c
        new_h = h if h < o else max(new_o, c)          # the high was the stale open: the bar's real top is unknown
        new_l = low if low > o else min(new_o, c)
        bars[i] = [t, new_o, max(new_h, new_o, c), min(new_l, new_o, c), c]
        log.info("candle %s: bad open %s replaced by the previous close %s", t, o, new_o)
    return bars


def fetch_candles(market: str, tf: str) -> list:
    req = urllib.request.Request(YAHOO.format(sym=SYMBOL[market], tf=tf, rng=RANGE[tf]), headers={"User-Agent": "Mozilla/5.0 (GEX PRO)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return parse_candles(r.read())


def _p(v):
    return v.get("price") if isinstance(v, dict) else v


def columns_from(folder: Path, since: datetime) -> list:
    """Every saved snapshot after `since` in a worker's snapshot folder, oldest first."""
    cols = []
    for day in sorted(folder.glob("????????")):
        if not day.is_dir() or day.name < since.strftime("%Y%m%d"):
            continue
        for f in sorted(day.glob("*.json")):
            if f.name.endswith(".chain.json"):
                continue
            try:
                s = json.loads(f.read_text(encoding="utf-8"))
                t = datetime.fromisoformat(s["asof"])
            except (OSError, ValueError, KeyError):
                continue
            if t < since or s.get("status") == "UNAVAILABLE":
                continue
            heat = s.get("heat")
            if heat and heat.get("v"):
                col = {"t": int(t.timestamp()), "base": heat["base"], "w": heat["w"], "v": heat["v"]}
            else:
                pr = (s.get("extras") or {}).get("profile")
                if not pr:
                    continue
                col = {"t": int(t.timestamp()), "base": pr["base"], "w": pr["width"], "v": pr["values"], "rel": True}
            col.update(zg=_p(s.get("zero_gamma")), cw=_p(s.get("call_wall")), pw=_p(s.get("put_wall")))
            cols.append(col)
    cols.sort(key=lambda c: c["t"])
    if len(cols) > MAX_COLUMNS:                        # keep the shape, drop density
        step = len(cols) / MAX_COLUMNS
        cols = [cols[int(i * step)] for i in range(MAX_COLUMNS)] + [cols[-1]]
    return cols


def build(worker, tf: str = "5m", candles: Optional[list] = None) -> dict:
    """The page's payload for one worker (one market) and one candle timeframe."""
    market = worker.cfg.market
    candles = candles if candles is not None else fetch_candles(market, tf)
    r = worker.result or {}
    m = (r.get("mapped") or {}).get("mapping") or {}
    since = datetime.fromtimestamp(candles[0][0], timezone.utc) - timedelta(hours=1) if candles else datetime.now(timezone.utc) - timedelta(days=5)
    cols = columns_from(worker.store.root / worker.key, since)
    return {"market": market, "tf": tf, "factor": m.get("factor") or 1.0, "offset": m.get("offset") or 0.0,
            "built": datetime.now(timezone.utc).isoformat(), "candles": candles, "columns": cols,
            "unit": "$M of dealer gamma per 1% move", "source": "candles: Yahoo Finance (delayed); GEX: Cboe options, 15-min delayed"}


class HeatmapCache:
    """Cached per (market, timeframe) for the local app: 60 s, the last good copy kept if Yahoo fails."""

    def __init__(self, ttl_s: float = 60.0):
        self.ttl_s = ttl_s
        self._lock = threading.Lock()
        self._data: dict = {}
        self.status: dict = {}            # market -> {"ok": last good fetch (ISO), "error": last failure or None}

    def note(self, market: str, error: Optional[str] = None) -> None:
        s = self.status.setdefault(market, {"ok": None, "error": None})
        if error:
            s["error"] = error
        else:
            s.update(ok=datetime.now(timezone.utc).isoformat(), error=None)

    def get(self, worker, tf: str) -> dict:
        key = (worker.key, tf)
        with self._lock:
            got = self._data.get(key)
            if got and time.time() - got[0] < self.ttl_s:
                return got[1]
        try:
            out = build(worker, tf)
            self.note(worker.cfg.market)
        except Exception as e:
            log.warning("heatmap %s %s failed: %s", worker.key, tf, e)
            self.note(worker.cfg.market, f"{type(e).__name__}: {e}")
            if got:
                return got[1]
            out = build(worker, tf, candles=[])
        with self._lock:
            self._data[key] = (time.time(), out)
        return out
