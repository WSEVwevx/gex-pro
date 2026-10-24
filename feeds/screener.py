"""Stock screener for the website: Yahoo Finance's public predefined screens (no key, free).

  GET https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={id}&count=100
  -> finance.result[0].quotes: one row per stock (price, change, volume, market cap, P/E, 52-week range...)

US equities, exchange data delayed about 15-20 minutes. Fetched at most every `ttl_s` (default 120 s);
a screen that fails keeps its last good copy, marked stale.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Optional

log = logging.getLogger("feeds.screener")
URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={id}&count=100"

# (id, label) - in the order the page shows them
SCREENS = [
    ("most_actives", "Most active"), ("day_gainers", "Gainers"), ("day_losers", "Losers"),
    ("small_cap_gainers", "Small-cap momentum"), ("most_shorted_stocks", "Most shorted"),
    ("growth_technology_stocks", "Tech growth"), ("undervalued_large_caps", "Value large caps"),
]


def _f(q: dict, k: str) -> Optional[float]:
    v = q.get(k)
    return float(v) if isinstance(v, (int, float)) and v == v else None


def parse(raw: bytes) -> Optional[list]:
    """The screen's rows, or None if the response is unusable."""
    try:
        quotes = json.loads(raw)["finance"]["result"][0]["quotes"]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    rows = []
    for q in quotes:
        price, sym = _f(q, "regularMarketPrice"), q.get("symbol")
        if not sym or not price or price <= 0:
            continue
        vol, avg = _f(q, "regularMarketVolume"), _f(q, "averageDailyVolume3Month")
        hi = _f(q, "fiftyTwoWeekHigh")
        rows.append({"symbol": sym, "name": q.get("displayName") or q.get("shortName") or q.get("longName") or sym,
                     "exchange": q.get("fullExchangeName") or q.get("exchange") or "",
                     "price": price, "change": _f(q, "regularMarketChange"), "pct": _f(q, "regularMarketChangePercent"),
                     "volume": vol, "avg_volume": avg, "rel_volume": vol / avg if vol and avg else None,
                     "mcap": _f(q, "marketCap"), "pe": _f(q, "trailingPE"),
                     "high52": hi, "low52": _f(q, "fiftyTwoWeekLow"), "from_high": (price / hi - 1) * 100 if hi else None,
                     "earnings": int(q["earningsTimestamp"]) if isinstance(q.get("earningsTimestamp"), int) else None})
    return rows


class Screener:
    def __init__(self, ttl_s: float = 120.0, opener: Callable = urllib.request.urlopen, clock: Callable[[], float] = time.time,
                 screens: list = SCREENS):
        self.ttl_s, self.opener, self.clock, self.screens = ttl_s, opener, clock, screens
        self._lock = threading.Lock()
        self._last: dict[str, dict] = {}
        self._fetched = -1e18

    def _one(self, sid: str) -> Optional[list]:
        req = urllib.request.Request(URL.format(id=sid), headers={"User-Agent": "Mozilla/5.0 (GEX PRO screener)"})
        try:
            with self.opener(req, timeout=15) as r:
                return parse(r.read())
        except Exception as e:
            log.info("screen %s failed: %s", sid, e)
            return None

    def get(self) -> dict:
        with self._lock:
            now = self.clock()
            if now - self._fetched >= self.ttl_s:
                self._fetched = now
                with ThreadPoolExecutor(max_workers=4) as ex:
                    got = dict(zip([s[0] for s in self.screens], ex.map(self._one, [s[0] for s in self.screens])))
                stamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
                for sid, _ in self.screens:
                    if got.get(sid) is not None:
                        self._last[sid] = {"rows": got[sid], "time": stamp, "stale": False}
                    elif sid in self._last:
                        self._last[sid]["stale"] = True
            screens = [dict(self._last[sid], id=sid, label=label) for sid, label in self.screens if sid in self._last]
            return {"fetched": datetime.fromtimestamp(self._fetched, timezone.utc).isoformat() if self._fetched > 0 else None,
                    "source": "Yahoo Finance screens (US stocks, exchange data delayed)", "screens": screens}
