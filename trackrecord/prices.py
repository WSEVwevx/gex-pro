"""Free price history for grading: daily and intraday index bars, and implied-vol index closes.

  SPX   daily: Cboe (cdn.cboe.com, since 1975), fallback Yahoo ^GSPC     intraday: Cboe 1-minute, today only
  NDX   daily: Yahoo ^NDX (Cboe does not publish NDX history)            intraday: Cboe 1-minute, today only
  VIX / VXN   daily closes: Cboe CSV (VIX since 1990, VXN since 2009), fallback Yahoo ^VIX / ^VXN

All of it is end-of-day or delayed, which is all grading needs. Bars are index points, matching the plans.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Optional

log = logging.getLogger("trackrecord.prices")
UA = {"User-Agent": "Mozilla/5.0 (GEX PRO track record)", "Accept": "*/*"}
CBOE = "https://cdn.cboe.com/api/global"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&period1={p1}&period2={p2}"
DAILY = {"SPX": [("cboe", "_SPX"), ("yahoo", "^GSPC")], "NDX": [("yahoo", "^NDX")]}
VOL_INDEX = {"SPX": "VIX", "NDX": "VXN"}


def _get(url: str, timeout: float = 25) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:      # follows Cboe's redirect to cdn-api
        return r.read()


def _bar(d, o, h, l, c, src) -> Optional[dict]:
    try:
        o, h, l, c = float(o), float(h), float(l), float(c)
    except (TypeError, ValueError):
        return None
    if min(o, h, l, c) <= 0 or h < l:                          # Cboe's oldest rows have no open
        return None
    return {"date": d, "open": o, "high": h, "low": l, "close": c, "source": src}


def parse_cboe_daily(raw: bytes) -> dict[str, dict]:
    out = {}
    for r in json.loads(raw).get("data", []):
        b = _bar(r.get("date"), r.get("open"), r.get("high"), r.get("low"), r.get("close"), "Cboe daily")
        if b:
            out[b["date"]] = b
    return out


def parse_yahoo_daily(raw: bytes, label: str) -> dict[str, dict]:
    res = json.loads(raw)["chart"]["result"][0]
    tz = res["meta"].get("exchangeTimezoneName", "America/New_York")
    from zoneinfo import ZoneInfo
    q = res["indicators"]["quote"][0]
    out = {}
    for i, t in enumerate(res.get("timestamp") or []):
        d = datetime.fromtimestamp(t, ZoneInfo(tz)).date().isoformat()
        b = _bar(d, q["open"][i], q["high"][i], q["low"][i], q["close"][i], label)
        if b:
            out[d] = b
    return out


def daily(underlying: str, since: date = date(1990, 1, 1)) -> dict[str, dict]:
    """date (YYYY-MM-DD) -> bar. The current day may be a partial bar; callers decide when a day is final."""
    for kind, sym in DAILY.get(underlying, []):
        try:
            if kind == "cboe":
                bars = parse_cboe_daily(_get(f"{CBOE}/delayed_quotes/charts/historical/{sym}.json"))
            else:
                p1 = int(datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp())
                p2 = int(datetime.now(timezone.utc).timestamp()) + 86400
                bars = parse_yahoo_daily(_get(YAHOO.format(sym=urllib.parse.quote(sym), p1=p1, p2=p2)), f"Yahoo {sym} daily")
            if bars:
                return bars
        except Exception as e:                                   # try the next source
            log.warning("daily %s from %s failed: %s", underlying, kind, e)
    return {}


def parse_cboe_intraday(raw: bytes) -> Optional[dict]:
    """Today's session from 1-minute bars: {"date", OHLC, "last": "HH:MM"} (ET), or None."""
    rows = json.loads(raw).get("data", [])
    rows = [r for r in rows if r.get("price") and r.get("datetime")]
    if not rows:
        return None
    p = [r["price"] for r in rows]
    b = _bar(rows[0]["datetime"][:10], p[0]["open"], max(x["high"] for x in p), min(x["low"] for x in p), p[-1]["close"], "Cboe 1-minute")
    if b:
        b["last"] = rows[-1]["datetime"][11:16]
    return b


def intraday(underlying: str) -> Optional[dict]:
    try:
        return parse_cboe_intraday(_get(f"{CBOE}/delayed_quotes/charts/intraday/_{underlying}.json"))
    except Exception as e:
        log.warning("intraday %s failed: %s", underlying, e)
        return None


def parse_cboe_vol_csv(raw: bytes) -> dict[str, float]:
    out = {}
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))):
        try:
            m, d, y = r["DATE"].split("/")
            v = float(r["CLOSE"])
        except (KeyError, ValueError):
            continue
        if v > 0:
            out[f"{y}-{int(m):02d}-{int(d):02d}"] = v
    return out


def vol_index(underlying: str) -> dict[str, float]:
    """date -> closing implied-vol index level (percent, e.g. 18.4)."""
    name = VOL_INDEX.get(underlying)
    if not name:
        return {}
    try:
        v = parse_cboe_vol_csv(_get(f"{CBOE}/us_indices/daily_prices/{name}_History.csv"))
        if v:
            return v
    except Exception as e:
        log.warning("%s history from Cboe failed: %s", name, e)
    try:
        bars = parse_yahoo_daily(_get(YAHOO.format(sym=urllib.parse.quote("^" + name), p1=631152000,
                                                   p2=int(datetime.now(timezone.utc).timestamp()) + 86400)), "Yahoo")
        return {d: b["close"] for d, b in bars.items()}
    except Exception as e:
        log.warning("%s history from Yahoo failed: %s", name, e)
        return {}
