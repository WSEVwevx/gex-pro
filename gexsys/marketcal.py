"""Market calendar: NYSE/Cboe holidays and early closes, CME Globex sessions,
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
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

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


def nyse_holidays(year: int) -> dict[date, str]:
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
    return h


def early_closes(year: int) -> dict[date, time]:
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
    return out


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def rth_close(d: date) -> time:
    return early_closes(d.year).get(d, time(16, 0))


def session_state(dt: datetime) -> str:
    """RTH | ETH (Globex open, cash closed) | CLOSED | HOLIDAY."""
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    t = dt.astimezone(NY)
    d, clock, wd = t.date(), t.time(), t.weekday()
    if d in nyse_holidays(d.year):
        return "HOLIDAY"
    if wd < 5 and time(9, 30) <= clock < rth_close(d):
        return "RTH"
    # Globex equity index: Sun 18:00 -> Fri 17:00 ET, daily halt 17:00-18:00 ET
    if wd == 5 or (wd == 6 and clock < time(18, 0)) or (wd == 4 and clock >= time(17, 0)):
        return "CLOSED"
    if time(17, 0) <= clock < time(18, 0):
        return "CLOSED"
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
