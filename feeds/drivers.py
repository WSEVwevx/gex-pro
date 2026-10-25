"""NQ / ES drivers for the website's Screener: the stocks that move the two futures, and by how much.

  weights    Nasdaq-100 and S&P 500 index weights, slickcharts.com (public pages, refreshed every 12 h;
             the last good copy is kept, and feeds/index_weights.json is a dated fallback)
  prices     Yahoo Finance chart data incl. pre-market and after-hours (exchange data delayed)
  volume     today's volume vs the 3-month average (daily bars, refreshed every 12 h)
  earnings   Nasdaq.com's earnings calendar, the next 30 days (refreshed every 6 h)

Points contribution = index weight x the stock's % move x the futures price: roughly how many NQ / ES
points that stock's move is worth. An approximation (weights drift intraday, futures carry a basis).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("feeds.drivers")
NY = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept": "text/html,application/json"}
WEIGHTS_URL = {"NQ": "https://www.slickcharts.com/nasdaq100", "ES": "https://www.slickcharts.com/sp500"}
INTRADAY = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=5m&includePrePost=true"
DAILY = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=3mo&interval=1d"
EARNINGS = "https://api.nasdaq.com/api/calendar/earnings?date={d}"
FUTURES = {"NQ": "NQ=F", "ES": "ES=F"}
FALLBACK = Path(__file__).with_name("index_weights.json")
ROW = re.compile(r'<tr><td>\d+</td><td[^>]*><a href="/symbol/([^"]+)">([^<]*)</a></td><td><a[^>]*>[^<]*</a></td><td>([\d.]+)%</td>')
WHEN = {"time-pre-market": "before open", "time-after-hours": "after close"}


def parse_weights(html: str) -> list:
    """[[symbol, company, weight %], ...] in index order."""
    return [[s, name.strip(), float(w)] for s, name, w in ROW.findall(html)]


def parse_intraday(raw: bytes) -> Optional[dict]:
    """Last regular-session price and change, plus the latest pre-market / after-hours print."""
    try:
        r = json.loads(raw)["chart"]["result"][0]
        m = r["meta"]
        price, prev = float(m["regularMarketPrice"]), float(m["chartPreviousClose"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if price <= 0 or prev <= 0:
        return None
    out = {"price": price, "prev": prev, "pct": (price / prev - 1) * 100, "volume": m.get("regularMarketVolume"), "ext": None}
    reg = (m.get("currentTradingPeriod") or {}).get("regular") or {}
    closes = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    last = next(((t, c) for t, c in zip(reversed(r.get("timestamp") or []), reversed(closes)) if c), None)
    if last and reg.get("start") and reg.get("end"):
        t, c = last
        session = "after" if t >= reg["end"] else "pre" if t < reg["start"] else None
        if session and abs(c / price - 1) > 1e-6:
            out["ext"] = {"session": session, "price": round(c, 4), "pct": (c / price - 1) * 100,
                          "time": datetime.fromtimestamp(t, timezone.utc).isoformat()}
    return out


def parse_daily(raw: bytes) -> Optional[dict]:
    """3-month average volume (the last bar is excluded: it may be today) and the last 20 closes."""
    try:
        q = json.loads(raw)["chart"]["result"][0]["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    vols = [v for v in (q.get("volume") or [])[:-1] if v]
    closes = [round(c, 2) for c in (q.get("close") or []) if c]
    return {"avg_volume": sum(vols) / len(vols) if vols else None, "spark": closes[-21:-1] if len(closes) > 1 else closes}


def parse_earnings(raw: bytes, day: str) -> dict:
    """{symbol: {"date", "when"}} from one day of Nasdaq.com's earnings calendar."""
    try:
        rows = json.loads(raw)["data"]["rows"] or []
    except (KeyError, TypeError, ValueError):
        return {}
    return {r["symbol"]: {"date": day, "when": WHEN.get(r.get("time"), "")} for r in rows if r.get("symbol")}


class Drivers:
    def __init__(self, cache_path: Optional[Path] = None, ttl_s: float = 120.0, top: int = 15,
                 opener: Callable = urllib.request.urlopen, clock: Callable[[], float] = time.time):
        self.cache_path, self.ttl_s, self.top, self.opener, self.clock = cache_path, ttl_s, top, opener, clock
        self._lock = threading.Lock()
        self._slow = {"weights": None, "weights_at": 0.0, "earnings": {}, "earnings_at": 0.0, "daily": {}}
        self._prices: dict = {}
        self._out: Optional[dict] = None
        self._fetched = -1e18
        if cache_path and cache_path.exists():
            try:
                self._slow.update(json.loads(cache_path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    def _get(self, url: str, timeout: float = 15) -> bytes:
        with self.opener(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.read()

    def _try(self, url: str) -> Optional[bytes]:
        try:
            return self._get(url)
        except Exception as e:
            log.info("drivers: %s failed: %s", url, e)
            return None

    # ---- slow data: weights (12 h), earnings (6 h), average volume and sparkline (12 h), saved between runs
    def _refresh_slow(self, now: float, symbols_hint: list) -> None:
        S = self._slow
        if now - S["weights_at"] >= 12 * 3600 or not S["weights"]:
            got = {}
            for mkt, url in WEIGHTS_URL.items():
                raw = self._try(url)
                rows = parse_weights(raw.decode("utf-8", "replace")) if raw else []
                if len(rows) >= 50:
                    got[mkt] = rows
            if len(got) == 2:
                S["weights"] = {"asof": datetime.fromtimestamp(now, timezone.utc).isoformat(), "source": "slickcharts.com", **got}
                S["weights_at"] = now
            elif not S["weights"]:
                try:
                    S["weights"] = json.loads(FALLBACK.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    S["weights"] = None
        if now - S["earnings_at"] >= 6 * 3600:
            today = datetime.fromtimestamp(now, NY).date()
            days = [today + timedelta(days=i) for i in range(-1, 31)]
            days = [d for d in days if d.weekday() < 5]
            with ThreadPoolExecutor(max_workers=4) as ex:
                raws = list(ex.map(lambda d: self._try(EARNINGS.format(d=d.isoformat())), days))
            if any(raws):
                cal: dict = {}
                for d, raw in zip(days, raws):
                    for sym, e in (parse_earnings(raw, d.isoformat()) if raw else {}).items():
                        cal.setdefault(sym, e)            # earliest date first: the next report
                S["earnings"], S["earnings_at"] = cal, now
        stale = [s for s in symbols_hint if now - (S["daily"].get(s) or {}).get("at", 0) >= 12 * 3600]
        if stale:
            with ThreadPoolExecutor(max_workers=6) as ex:
                raws = list(ex.map(lambda s: self._try(DAILY.format(sym=urllib.parse.quote(s))), stale))
            for s, raw in zip(stale, raws):
                d = parse_daily(raw) if raw else None
                if d:
                    S["daily"][s] = dict(d, at=now)
        if self.cache_path:
            try:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(json.dumps(S), encoding="utf-8")
            except OSError:
                pass

    def universe(self) -> list:
        """The top `top` names by weight in each index, merged: [(yahoo symbol, name, w_nq, w_es)]."""
        W = self._slow["weights"] or {}
        nq = {s: (n, w) for s, n, w in W.get("NQ") or []}
        es = {s: (n, w) for s, n, w in W.get("ES") or []}
        pick = [s for s, _, _ in (W.get("NQ") or [])[:self.top]] + [s for s, _, _ in (W.get("ES") or [])[:self.top]]
        seen, out = set(), []
        for s in pick:
            if s in seen:
                continue
            seen.add(s)
            name = (nq.get(s) or es.get(s))[0]
            out.append((s.replace(".", "-"), name, nq.get(s, (None, 0.0))[1], es.get(s, (None, 0.0))[1]))
        return out

    def get(self) -> dict:
        with self._lock:
            now = self.clock()
            if self._out is not None and now - self._fetched < self.ttl_s:
                return self._out
            self._fetched = now
            self._refresh_slow(now, [])
            uni = self.universe()
            syms = [u[0] for u in uni]
            self._refresh_slow(now, syms)
            want = syms + list(FUTURES.values())
            with ThreadPoolExecutor(max_workers=6) as ex:
                raws = list(ex.map(lambda s: self._try(INTRADAY.format(sym=urllib.parse.quote(s))), want))
            for s, raw in zip(want, raws):
                p = parse_intraday(raw) if raw else None
                if p:
                    self._prices[s] = dict(p, stale=False)
                elif s in self._prices:
                    self._prices[s]["stale"] = True
            fut = {m: self._prices.get(sym) for m, sym in FUTURES.items()}
            stocks = []
            for sym, name, w_nq, w_es in uni:
                p = self._prices.get(sym)
                if not p:
                    continue
                d = self._slow["daily"].get(sym) or {}
                e = self._slow["earnings"].get(sym.replace("-", ".")) or self._slow["earnings"].get(sym)
                row = {"symbol": sym, "name": name, "price": p["price"], "pct": p["pct"], "change": p["price"] - p["prev"],
                       "ext": p["ext"], "volume": p["volume"], "avg_volume": d.get("avg_volume"),
                       "rel_volume": p["volume"] / d["avg_volume"] if p["volume"] and d.get("avg_volume") else None,
                       "w_nq": w_nq, "w_es": w_es, "spark": (d.get("spark") or []) + [round(p["price"], 2)],
                       "earnings": e, "stale": p["stale"]}
                for m, w in (("nq", w_nq), ("es", w_es)):
                    f = fut[m.upper()]
                    row["pts_" + m] = w / 100 * p["pct"] / 100 * f["price"] if f and w else None
                    row["ext_pts_" + m] = w / 100 * p["ext"]["pct"] / 100 * f["price"] if f and w and p["ext"] else None
                stocks.append(row)
            totals = {}
            for m in ("NQ", "ES"):
                k, f = m.lower(), fut[m]
                rows = [r for r in stocks if r["w_" + k]]
                totals[m] = {"futures": {"price": f["price"], "change": f["price"] - f["prev"], "pct": f["pct"]} if f else None,
                             "names": len(rows), "weight": sum(r["w_" + k] for r in rows),
                             "pts": sum(r["pts_" + k] or 0 for r in rows), "ext_pts": sum(r["ext_pts_" + k] or 0 for r in rows),
                             "up": sum(r["pct"] > 0 for r in rows), "down": sum(r["pct"] < 0 for r in rows)}
            W = self._slow["weights"] or {}
            self._out = {"fetched": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                         "weights_asof": W.get("asof"), "weights_source": W.get("source"),
                         "source": "Weights: slickcharts.com. Prices: Yahoo Finance, delayed. Earnings: Nasdaq.com.",
                         "totals": totals, "stocks": stocks}
            return self._out
