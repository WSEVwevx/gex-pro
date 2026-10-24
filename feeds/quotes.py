"""Market quotes for the website's scrolling ticker: real prices from Yahoo Finance's public chart data.

  GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d
  -> chart.result[0].meta: regularMarketPrice, chartPreviousClose, regularMarketTime, currency

Exchange data is delayed (indexes and futures about 10-15 minutes; crypto near real time). Fetched at
most every `ttl_s` (default 60 s); a symbol that fails keeps its last good quote, marked stale.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Optional

log = logging.getLogger("feeds.quotes")
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=1d"

# (label, Yahoo symbol, decimals, kind) - the big ones a futures trader watches
SYMBOLS = [
    ("ES", "ES=F", 2, "future"), ("NQ", "NQ=F", 2, "future"), ("SPX", "^GSPC", 2, "index"), ("NDX", "^NDX", 2, "index"),
    ("DOW", "^DJI", 2, "index"), ("RUT", "^RUT", 2, "index"), ("VIX", "^VIX", 2, "index"), ("DXY", "DX-Y.NYB", 3, "index"),
    ("10Y", "^TNX", 3, "yield"), ("GOLD", "GC=F", 1, "future"), ("OIL", "CL=F", 2, "future"),
    ("BTC", "BTC-USD", 0, "crypto"), ("ETH", "ETH-USD", 2, "crypto"), ("SOL", "SOL-USD", 2, "crypto"),
    ("NVDA", "NVDA", 2, "stock"), ("AAPL", "AAPL", 2, "stock"), ("MSFT", "MSFT", 2, "stock"), ("TSLA", "TSLA", 2, "stock"),
]


def parse(raw: bytes) -> Optional[dict]:
    """price, previous close, change and its time from one chart response; None if unusable."""
    try:
        m = json.loads(raw)["chart"]["result"][0]["meta"]
        price, prev = float(m["regularMarketPrice"]), float(m["chartPreviousClose"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if price <= 0 or prev <= 0:
        return None
    return {"price": price, "prev": prev, "change": price - prev, "pct": (price / prev - 1) * 100,
            "time": datetime.fromtimestamp(int(m.get("regularMarketTime") or 0), timezone.utc).isoformat()}


class Quotes:
    def __init__(self, ttl_s: float = 60.0, opener: Callable = urllib.request.urlopen, clock: Callable[[], float] = time.time,
                 symbols: list = SYMBOLS):
        self.ttl_s, self.opener, self.clock, self.symbols = ttl_s, opener, clock, symbols
        self._lock = threading.Lock()
        self._last: dict[str, dict] = {}
        self._fetched = -1e18

    def _one(self, sym: str) -> Optional[dict]:
        req = urllib.request.Request(URL.format(sym=urllib.parse.quote(sym)), headers={"User-Agent": "Mozilla/5.0 (GEX PRO ticker)"})
        try:
            with self.opener(req, timeout=10) as r:
                return parse(r.read())
        except Exception as e:
            log.info("quote %s failed: %s", sym, e)
            return None

    def get(self) -> dict:
        with self._lock:
            now = self.clock()
            if now - self._fetched >= self.ttl_s:
                self._fetched = now
                with ThreadPoolExecutor(max_workers=6) as ex:
                    got = dict(zip([s[1] for s in self.symbols], ex.map(self._one, [s[1] for s in self.symbols])))
                for label, sym, _, _ in self.symbols:
                    if got.get(sym):
                        self._last[label] = dict(got[sym], stale=False)
                    elif label in self._last:
                        self._last[label]["stale"] = True
            quotes = [dict(self._last[label], label=label, symbol=sym, dp=dp, kind=kind)
                      for label, sym, dp, kind in self.symbols if label in self._last]
            return {"fetched": datetime.fromtimestamp(self._fetched, timezone.utc).isoformat() if self._fetched > 0 else None,
                    "source": "Yahoo Finance (exchange data delayed)", "quotes": quotes}
