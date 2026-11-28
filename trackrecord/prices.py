"""Free price history for grading: daily index bars and implied-vol index closes, all from Yahoo Finance.

  SPX   daily: Yahoo ^GSPC        NDX   daily: Yahoo ^NDX
  VIX / VXN   daily closes: Yahoo ^VIX / ^VXN (VIX since 1990)

All of it is end-of-day or delayed, which is all grading needs. Bars are index points, matching the plans. A session is
graded on its daily bar once that bar is final (trackrecord/component.py session_bar).
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Optional

log = logging.getLogger("trackrecord.prices")
UA = {"User-Agent": "Mozilla/5.0 (GEX PRO track record)", "Accept": "*/*"}
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&period1={p1}&period2={p2}"
DAILY = {"SPX": "^GSPC", "NDX": "^NDX"}
VOL_INDEX = {"SPX": "VIX", "NDX": "VXN"}


def _get(url: str, timeout: float = 25) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _bar(d, o, h, l, c, src) -> Optional[dict]:
    try:
        o, h, l, c = float(o), float(h), float(l), float(c)
    except (TypeError, ValueError):
        return None
    if min(o, h, l, c) <= 0 or h < l:                          # some old rows have no open
        return None
    return {"date": d, "open": o, "high": h, "low": l, "close": c, "source": src}


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
    sym = DAILY.get(underlying)
    if not sym:
        return {}
    try:
        p1 = int(datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp())
        p2 = int(datetime.now(timezone.utc).timestamp()) + 86400
        return parse_yahoo_daily(_get(YAHOO.format(sym=urllib.parse.quote(sym), p1=p1, p2=p2)), f"Yahoo {sym} daily")
    except Exception as e:
        log.warning("daily %s from Yahoo failed: %s", underlying, e)
        return {}


def yahoo_daily(sym: str, days: int = 45) -> dict[str, dict]:
    """date -> bar for any Yahoo symbol over the last `days` days; {} when the source fails."""
    p2 = int(datetime.now(timezone.utc).timestamp()) + 86400
    try:
        return parse_yahoo_daily(_get(YAHOO.format(sym=urllib.parse.quote(sym), p1=p2 - (days + 1) * 86400, p2=p2)), f"Yahoo {sym} daily")
    except Exception as e:
        log.warning("daily %s failed: %s", sym, e)
        return {}


PUBLIC_MINUTES = "https://raw.githubusercontent.com/WSEVwevx/gex-pro/track-record/minutes/{name}"


def minutes(session: dict, recent: bool = True, end: int = 390) -> Optional[dict]:
    """A graded session's 1-minute futures record (trackrecord/reactions.py): the public track record's saved
    copy first (so the local app matches the hosted site), else Yahoo while it still has the day (~30 days)."""
    from . import reactions
    d = date.fromisoformat(session["session"])
    try:
        rec = json.loads(_get(PUBLIC_MINUTES.format(name=f"{session['session']}_{session['market']}.json"), timeout=15))
        if rec.get("bars"):
            return rec
    except Exception:
        pass                                                     # not saved there (yet)
    return reactions.minutes_record(session, reactions.fetch_minutes(session["market"], d, end), end) if recent else None


def vol_index(underlying: str) -> dict[str, float]:
    """date -> closing implied-vol index level (percent, e.g. 18.4)."""
    name = VOL_INDEX.get(underlying)
    if not name:
        return {}
    try:
        bars = parse_yahoo_daily(_get(YAHOO.format(sym=urllib.parse.quote("^" + name), p1=631152000,
                                                   p2=int(datetime.now(timezone.utc).timestamp()) + 86400)), "Yahoo")
        return {d: b["close"] for d, b in bars.items()}
    except Exception as e:
        log.warning("%s history from Yahoo failed: %s", name, e)
        return {}
