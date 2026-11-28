"""Market calendar: NYSE holidays and early closes, CME Globex sessions,
futures roll schedule, option expiry times, and session-aware refresh cadence.

All wall-clock rules are expressed in America/New_York and converted with
zoneinfo, so daylight-saving transitions are handled by the tz database rather
than by fixed UTC offsets.

Simplifications (documented in docs/LIMITATIONS.md):
* Holiday rules cover the standard NYSE schedule from 2022 (Juneteenth onward).
  Ad-hoc closures (national days of mourning, weather) must be added to
  EXTRA_CLOSURES.
* CME Globex trades abbreviated sessions on many NYSE holidays; this module
  treats an NYSE holiday as "HOLIDAY" (no fresh options data expected).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from datetime import date, datetime, time, timedelta
from typing import Mapping, Optional
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

EXTRA_CLOSURES: dict[date, str] = {
    date(2025, 1, 9): "National Day of Mourning (President Carter)",
}

QUARTER_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}
AM_SETTLED_ROOTS = {"SPX", "NDX", "RUT"}       # standard monthly index options
FUTURES_QUARTERLY_ROOTS = {"ES", "NQ"}         # quarterly futures options: settle to SOQ


def easter(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def nyse_holidays(year: int) -> Mapping[date, str]:
    h: dict[date, str] = {}
    ny = date(year, 1, 1)
    if ny.weekday() != 5:        # NYSE does not observe a Saturday New Year on Friday Dec 31
        h[_observed(ny)] = "New Year's Day"
    h[_nth_weekday(year, 1, 0, 3)] = "Martin Luther King Jr. Day"
    h[_nth_weekday(year, 2, 0, 3)] = "Washington's Birthday"
    h[easter(year) - timedelta(days=2)] = "Good Friday"
    h[_last_weekday(year, 5, 0)] = "Memorial Day"
    if year >= 2022:
        h[_observed(date(year, 6, 19))] = "Juneteenth"
    h[_observed(date(year, 7, 4))] = "Independence Day"
    h[_nth_weekday(year, 9, 0, 1)] = "Labor Day"
    h[_nth_weekday(year, 11, 3, 4)] = "Thanksgiving Day"
    h[_observed(date(year, 12, 25))] = "Christmas Day"
    for d, name in EXTRA_CLOSURES.items():
        if d.year == year:
            h[d] = name
    return MappingProxyType(h)            # cached per year (rebuilt ~35,000 times a refresh before): read-only


@lru_cache(maxsize=None)
def early_closes(year: int) -> Mapping[date, time]:
    """13:00 ET equity/index-option early closes."""
    hol = nyse_holidays(year)
    out: dict[date, time] = {}
    j3 = date(year, 7, 3)
    if j3.weekday() < 4 and j3 not in hol:      # Mon-Thu, i.e. July 4 falls Tue-Fri
        out[j3] = time(13, 0)
    out[_nth_weekday(year, 11, 3, 4) + timedelta(days=1)] = time(13, 0)
    c24 = date(year, 12, 24)
    if c24.weekday() < 5 and c24 not in hol:
        out[c24] = time(13, 0)
    return MappingProxyType(out)


FULL_CLOSURES = {"New Year's Day", "Good Friday", "Christmas Day"}    # CME equity futures closed all day


def globex_morning(d: date) -> bool:
    """A cash holiday on which CME equity index futures still trade until 13:00 ET (Thanksgiving, MLK Day, ...):
    every NYSE holiday except New Year's Day, Good Friday, Christmas Day and the special closures."""
    name = nyse_holidays(d.year).get(d)
    return bool(name) and name not in FULL_CLOSURES and d not in EXTRA_CLOSURES


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


RTH_OPEN = time(9, 30)
GLOBEX_REOPEN, GLOBEX_HALT = time(18, 0), time(17, 0)     # CME equity index: daily halt 17:00-18:00 ET


def rth_close(d: date) -> time:
    return early_closes(d.year).get(d, time(16, 0))


def rth_open_dt(d: date) -> datetime:
    """d's cash open, ET."""
    return datetime.combine(d, RTH_OPEN, NY)


def rth_close_dt(d: date) -> datetime:
    """d's cash close, ET (13:00 on early closes)."""
    return datetime.combine(d, rth_close(d), NY)


def previous_trading_day(d: date) -> date:
    p = d - timedelta(days=1)
    while not is_trading_day(p):
        p -= timedelta(days=1)
    return p


def globex_day(d: date) -> tuple[datetime, datetime]:
    """The futures bars that belong to trading day d: from the reopen after the previous trading day (18:00 ET) to
    d's 17:00 ET halt. A weekend's Sunday open and a holiday's Globex morning fall inside it."""
    return datetime.combine(previous_trading_day(d), GLOBEX_REOPEN, NY), datetime.combine(d, GLOBEX_HALT, NY)


def last_close(t: datetime) -> datetime:
    """The most recent regular-session close at or before t."""
    d = t.astimezone(NY).date()
    for _ in range(12):
        if is_trading_day(d):
            c = datetime.combine(d, rth_close(d), NY)
            if c <= t:
                return c
        d -= timedelta(days=1)
    return t


def session_state(dt: datetime) -> str:
    """RTH | ETH (Globex open, cash closed) | CLOSED | HOLIDAY."""
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    t = dt.astimezone(NY)
    d, clock, wd = t.date(), t.time(), t.weekday()
    if d in nyse_holidays(d.year):
        if globex_morning(d) and clock < time(13, 0):          # the overnight session runs on to a 13:00 ET halt
            return "ETH"
        # Globex reopens at 18:00 ET for the next trading day (not after Good Friday: that is the weekend)
        return "ETH" if clock >= time(18, 0) and is_trading_day(d + timedelta(days=1)) else "HOLIDAY"
    if wd < 5 and time(9, 30) <= clock < rth_close(d):
        return "RTH"
    if d in early_closes(d.year) and clock >= time(13, 15):     # CME halts index futures at 13:15 ET
        return "CLOSED"
    # Globex equity index: Sun 18:00 -> Fri 17:00 ET, daily halt 17:00-18:00 ET
    if wd == 5 or (wd == 6 and clock < time(18, 0)) or (wd == 4 and clock >= time(17, 0)):
        return "CLOSED"
    if time(17, 0) <= clock < time(18, 0):
        return "CLOSED"
    nxt = d + timedelta(days=1)
    if clock >= time(18, 0) and nxt in nyse_holidays(nxt.year) and not globex_morning(nxt):
        return "CLOSED"                                        # no evening session before New Year's Day / Good Friday
    return "ETH"


@dataclass
class RefreshPolicy:
    rth_seconds: int = 60
    eth_seconds: int = 900
    closed_seconds: int = 3600


def refresh_interval(dt: datetime, policy: Optional[RefreshPolicy] = None) -> int:
    p = policy or RefreshPolicy()
    st = session_state(dt)
    return {"RTH": p.rth_seconds, "ETH": p.eth_seconds}.get(st, p.closed_seconds)


def third_friday(year: int, month: int) -> date:
    return _nth_weekday(year, month, 4, 3)


def quarterly_expiry(year: int, month: int) -> date:
    d = third_friday(year, month)
    while not is_trading_day(d):      # exchange-holiday adjustment: move to preceding business day
        d -= timedelta(days=1)
    return d


def roll_date(year: int, month: int) -> date:
    """Conventional equity-index roll: 8 calendar days before the third Friday (second Thursday)."""
    return third_friday(year, month) - timedelta(days=8)


def roll_week(d: date) -> bool:
    """The 8 days before a quarterly expiry (the conventional roll date to the expiry, inclusive)."""
    m = ((d.month - 1) // 3 + 1) * 3
    return roll_date(d.year, m) <= d <= quarterly_expiry(d.year, m)


def sessions_ahead(d: date, n: int) -> list[date]:
    """The trading day before d, then d's (if it trades) and the following trading days: n days in all."""
    out, x = [previous_trading_day(d)], d
    while len(out) < n:
        if is_trading_day(x):
            out.append(x)
        x += timedelta(days=1)
    return out


def state_changes(start: datetime, end: datetime) -> list[tuple[datetime, str]]:
    """session_state at start, then every minute it changes up to end."""
    out: list[tuple[datetime, str]] = []
    t = start.replace(second=0, microsecond=0)
    while t <= end:
        s = session_state(t)
        if not out or out[-1][1] != s:
            out.append((t, s))
        t += timedelta(minutes=1)
    return out


def front_contract(root: str, on: date) -> str:
    """Active (post-roll) quarterly contract, e.g. front_contract('NQ', date(2026,12,10)) -> 'NQH7'."""
    y, m = on.year, on.month
    for _ in range(6):
        qm = ((m - 1) // 3 + 1) * 3
        if on < roll_date(y, qm):
            return f"{root}{QUARTER_CODES[qm]}{y % 10}"
        m = qm + 1
        if m > 12:
            m, y = 1, y + 1
    raise RuntimeError("unreachable")


def continuous_contract(root: str, on: datetime) -> str:
    """The quarterly a continuous chart shows (TradingView NQ1!, Yahoo NQ=F): the expiring contract until its
    09:30 ET settlement on expiry day, then the next. Not the trader's roll 8 days earlier: Yahoo's NQ=F and
    ES=F switched on the Monday after expiry every quarter Dec 2025 - Sep 2026 (stress test C2)."""
    t = on.astimezone(NY)
    y, m = t.year, ((t.month - 1) // 3 + 1) * 3
    for _ in range(3):
        if t < datetime.combine(quarterly_expiry(y, m), time(9, 30), NY):
            return f"{root}{QUARTER_CODES[m]}{y % 10}"
        m += 3
        if m > 12:
            m, y = 3, y + 1
    raise RuntimeError("unreachable")


def option_expiry_time(d: date, root: str) -> datetime:
    """Expiry reference time used for time-to-expiry.

    AM-settled (SPX/NDX standard monthlies, ES/NQ quarterly options): 09:30 ET,
    the opening print used for settlement.  Everything else (SPXW, NDXP, SPY,
    QQQ, weekly futures options): the close, 13:00 on early-close days.
    """
    r = root.upper()
    if r in AM_SETTLED_ROOTS or r in FUTURES_QUARTERLY_ROOTS:
        return datetime.combine(d, time(9, 30), NY)
    return datetime.combine(d, rth_close(d), NY)
