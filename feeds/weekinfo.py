"""What the weekly recap reads to explain a week's prices. All free, all fetched once a week, each one optional.

  closes     Yahoo Finance spark: daily closes for every index member, 20 symbols a request
  earnings   Nasdaq.com's earnings calendar for a past day: who reported, and the surprise against estimates
  economy    Nasdaq.com's economic calendar for a past day: actual vs consensus
  headlines  Google News RSS, limited to the days around one session
"""
from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("feeds.weekinfo")
NY = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept": "*/*"}
SPARK = "https://query1.finance.yahoo.com/v7/finance/spark?symbols={syms}&range=1mo&interval=1d"
EARNINGS = "https://api.nasdaq.com/api/calendar/earnings?date={d}"
ECONOMY = "https://api.nasdaq.com/api/calendar/economicevents?date={d}"
NEWS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
BATCH = 20
# the releases that move index futures, most important first; a recap names the top ones of the week
BIG_DATA = ("fed interest rate", "nonfarm payrolls", "cpi", "core pce price index", "gdp", "unemployment rate", "retail sales", "ppi", "ism")
NOT_DATA = ("gdpnow", "gdp price", "gdp sales", "gdp deflator", "gdp capital", "core retail", "ism prices", "ism employment", "ism new orders",
            "ism inventories", "cpi index", "cpi n.s.a", "cleveland")


def _get(url: str, timeout: float = 20) -> Optional[bytes]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.read()
    except Exception as e:
        log.warning("%s failed: %s", url.split("?")[0], e)
        return None


def parse_spark(raw: bytes) -> dict:
    """{symbol: {date: close}}."""
    out = {}
    for item in json.loads(raw).get("spark", {}).get("result") or []:
        try:
            r = item["response"][0]
            closes = r["indicators"]["quote"][0]["close"]
            out[item["symbol"]] = {datetime.fromtimestamp(t, NY).date().isoformat(): c for t, c in zip(r["timestamp"], closes) if c is not None}
        except (KeyError, IndexError, TypeError):
            continue
    return out


def closes(symbols: list) -> dict:
    groups = [symbols[i:i + BATCH] for i in range(0, len(symbols), BATCH)]
    def one(g):
        raw = _get(SPARK.format(syms=urllib.parse.quote(",".join(g), safe=",")))
        try:
            return parse_spark(raw) if raw else {}
        except ValueError:
            return {}
    out: dict = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for got in ex.map(one, groups):
            out.update(got)
    return out


def parse_earnings(raw: bytes, day: str) -> list:
    rows = ((json.loads(raw).get("data") or {}).get("rows")) or []
    out = []
    for r in rows:
        try:
            surprise = float(r.get("surprise"))
        except (TypeError, ValueError):
            surprise = None
        out.append({"date": day, "symbol": str(r.get("symbol") or "").replace(".", "-"), "time": r.get("time"), "surprise": surprise})
    return out


def parse_economy(raw: bytes, day: str) -> list:
    """The big US releases with a result; Nasdaq's rows carry no market impact, so they are picked by name."""
    rows = ((json.loads(raw).get("data") or {}).get("rows")) or []
    out = []
    for r in rows:
        name = html.unescape(str(r.get("eventName") or "")).strip()
        actual = str(r.get("actual") or "").replace("&nbsp;", "").strip()
        low = name.lower()
        rank = next((i for i, k in enumerate(BIG_DATA) if k in low), None)
        if r.get("country") == "United States" and actual and rank is not None and not any(k in low for k in NOT_DATA):
            out.append({"date": day, "title": name, "rank": rank, "actual": actual, "consensus": str(r.get("consensus") or "").replace("&nbsp;", "").strip()})
    return out


def _days(start: date, end: date) -> list:
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def earnings(start: date, end: date) -> list:
    out = []
    for d in _days(start, end):
        raw = _get(EARNINGS.format(d=d))
        try:
            out += parse_earnings(raw, d) if raw else []
        except ValueError:
            continue
    return out


def economy(start: date, end: date) -> list:
    out = []
    for d in _days(start, end):
        raw = _get(ECONOMY.format(d=d))
        try:
            out += parse_economy(raw, d) if raw else []
        except ValueError:
            continue
    return out


def parse_news(raw: bytes, day: str, limit: int) -> list:
    """[{day, title, source, url}] from a Google News RSS page. Titles arrive as 'Headline - Source'."""
    text = raw.decode("utf-8", "ignore")
    out = []
    for item in re.findall(r"<item>(.*?)</item>", text, re.S)[:limit]:
        t = re.search(r"<title>(.*?)</title>", item, re.S)
        u = re.search(r"<link>(.*?)</link>", item, re.S)
        if t and u:
            title, _, source = html.unescape(html.unescape(t.group(1))).rpartition(" - ")
            out.append({"day": day, "title": title or source, "source": source if title else "", "url": html.unescape(u.group(1)).strip()})
    return out


def headlines(day: date, limit: int = 2) -> list:
    q = urllib.parse.quote(f"stock market after:{day - timedelta(days=1)} before:{day + timedelta(days=1)}")
    raw = _get(NEWS.format(q=q))
    return parse_news(raw, day.isoformat(), limit) if raw else []
