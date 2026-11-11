"""Stress test E2: every timestamp path, every day of 2026-2027, against rules written out independently.

  python tools/stress/calendar_exact.py

Truth, written from the exchanges' own schedules (not from gexsys/marketcal.py):
  NYSE holidays and 13:00 early closes 2026-2028: nyse.com/markets/hours-calendars (read 2026-11-10)
  US Eastern time: UTC-4 from 02:00 on the 2nd Sunday of March to 02:00 on the 1st Sunday of November, else UTC-5
  CME equity index futures: Sunday 18:00 to Friday 17:00 ET, a daily halt 17:00-18:00; on a 13:00 cash early
      close the futures halt at 13:15; on a cash holiday Globex trades until 13:00 and reopens at 18:00 for the
      next trading day, except New Year's Day, Good Friday and Christmas (closed all day, no session the evening
      before)
Paths checked, every day: UTC <-> ET for the open, the close, the 17:00 halt and the 18:00 reopen; session state at
both edges of every boundary (one minute either side); the 15-minute data delay; the hourly publish slots; the plan
freeze (09:30 + 30 min); the grading close; the 1-minute bar window (09:30 to the close, end excluded); the reaction
study's per-minute scaling on a short session.
Tolerance (fixed before running): exact. Any off-by-one minute or day is a fail.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gexsys import marketcal, publish  # noqa: E402
from gexsys.providers import cboe  # noqa: E402
from trackrecord import component, reactions  # noqa: E402

NY = marketcal.NY
HOLIDAYS = {  # nyse.com, 2026-2028
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 31), date(2027, 6, 18),
    date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25), date(2027, 12, 24),
    date(2028, 1, 17), date(2028, 2, 21), date(2028, 4, 14), date(2028, 5, 29), date(2028, 6, 19), date(2028, 7, 4),
    date(2028, 9, 4), date(2028, 11, 23), date(2028, 12, 25)}
FULL_CLOSE = {date(2026, 1, 1), date(2026, 4, 3), date(2026, 12, 25), date(2027, 1, 1), date(2027, 3, 26),
              date(2027, 12, 24), date(2028, 4, 14), date(2028, 12, 25)}
EARLY = {date(2026, 11, 27), date(2026, 12, 24), date(2027, 11, 26), date(2028, 7, 3), date(2028, 11, 24)}


def utc_offset_h(d: date, clock: time) -> int:
    """-4 in daylight time, -5 otherwise, from the US rule (the switch happens at 02:00 local)."""
    def nth_sunday(y, m, n):
        x = date(y, m, 1)
        x += timedelta(days=(6 - x.weekday()) % 7)
        return x + timedelta(weeks=n - 1)
    start, end = nth_sunday(d.year, 3, 2), nth_sunday(d.year, 11, 1)
    if start < d < end:
        return -4
    if d == start:
        return -4 if clock >= time(3, 0) else -5      # 02:00-03:00 does not exist that day
    if d == end:
        return -5 if clock >= time(2, 0) else -4      # 01:00-02:00 happens twice; the code's wall clock is the first
    return -5


def et(d: date, hh: int, mm: int = 0) -> datetime:
    """An ET wall-clock time as an exact UTC instant, by the rule above (no tz database)."""
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=timezone.utc) - timedelta(hours=utc_offset_h(d, time(hh, mm)))


def trading(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def cash_close(d: date) -> time:
    return time(13, 0) if d in EARLY else time(16, 0)


def state(d: date, clock: time) -> str:
    """Session state from the rules in the docstring."""
    wd = d.weekday()
    if d in HOLIDAYS:
        if d not in FULL_CLOSE and clock < time(13, 0):
            return "ETH"
        return "ETH" if clock >= time(18, 0) and trading(d + timedelta(days=1)) else "HOLIDAY"
    if wd < 5 and time(9, 30) <= clock < cash_close(d):
        return "RTH"
    if d in EARLY and clock >= time(13, 15):
        return "CLOSED"
    if wd == 5 or (wd == 6 and clock < time(18, 0)) or (wd == 4 and clock >= time(17, 0)):
        return "CLOSED"
    if time(17, 0) <= clock < time(18, 0):
        return "CLOSED"
    nxt = d + timedelta(days=1)
    if clock >= time(18, 0) and nxt in FULL_CLOSE:
        return "CLOSED"
    return "ETH"


def main() -> int:
    bad: list[str] = []
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range((date(2027, 12, 31) - date(2026, 1, 1)).days + 1)]
    # calendar
    for y in (2026, 2027, 2028):
        got_h, got_e = set(marketcal.nyse_holidays(y)), set(marketcal.early_closes(y))
        want_h, want_e = {d for d in HOLIDAYS if d.year == y}, {d for d in EARLY if d.year == y}
        if got_h != want_h:
            bad.append(f"{y} holidays: extra {sorted(got_h - want_h)}, missing {sorted(want_h - got_h)}")
        if got_e != want_e:
            bad.append(f"{y} early closes: extra {sorted(got_e - want_e)}, missing {sorted(want_e - got_e)}")
    # UTC <-> ET and session state at every boundary
    edges = [(9, 30), (13, 0), (13, 15), (16, 0), (17, 0), (18, 0), (0, 0), (2, 0), (3, 0)]
    n_state = 0
    for d in days:
        for hh, mm in edges:
            for delta in (-1, 0, 1):
                wall = datetime.combine(d, time(hh, mm), NY) + timedelta(minutes=delta)
                if wall.date() != d:
                    continue
                c = wall.time()
                if d.month in (3, 11) and time(1, 0) <= c < time(3, 0) and utc_offset_h(d, c) != utc_offset_h(d, time(12, 0)):
                    continue                                          # the switch hour itself: checked separately
                want_utc = et(d, c.hour, c.minute)
                if wall.astimezone(timezone.utc) != want_utc:
                    bad.append(f"{d} {c} ET -> {wall.astimezone(timezone.utc):%H:%M} UTC, should be {want_utc:%H:%M}")
                s_got, s_want = marketcal.session_state(want_utc), state(d, c)
                n_state += 1
                if s_got != s_want:
                    bad.append(f"{d} {c} ET: state {s_got}, should be {s_want}")
    # the two switch instants
    for utc, want in ((datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc), (1, 59)), (datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc), (3, 0)),
                      (datetime(2026, 11, 1, 5, 59, tzinfo=timezone.utc), (1, 59)), (datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc), (1, 0)),
                      (datetime(2027, 3, 14, 7, 0, tzinfo=timezone.utc), (3, 0)), (datetime(2027, 11, 7, 6, 0, tzinfo=timezone.utc), (1, 0))):
        loc = utc.astimezone(NY)
        if (loc.hour, loc.minute) != want:
            bad.append(f"{utc:%Y-%m-%d %H:%M} UTC -> {loc:%H:%M} ET, should be {want[0]:02d}:{want[1]:02d}")
    # the 15-minute delay
    if cboe.DELAY != timedelta(minutes=15):
        bad.append(f"Cboe delay {cboe.DELAY}, should be 15 minutes")
    # publish slots: every hour on the hour while the futures trade
    cfg = publish.PublishConfig()
    n_slots = 0
    for d in days:
        got = publish._day_slots(d, cfg)
        want = [et(d, h) for h in range(24) if state(d, time(h, 0)) in ("RTH", "ETH")
                and not (d.month in (3, 11) and h == 2 and utc_offset_h(d, time(2, 0)) != utc_offset_h(d, time(12, 0)))]
        got = [g for g in got if not (d.month in (3, 11) and g.hour == 2 and utc_offset_h(d, time(2, 0)) != utc_offset_h(d, time(12, 0)))]
        n_slots += len(want)
        if [g.astimezone(timezone.utc) for g in got] != want:
            bad.append(f"{d} publish slots differ: {[g.strftime('%H:%M') for g in got][:6]}... vs {len(want)} expected")
    # plan freeze, grading close, the 1-minute window
    for d in days:
        if not trading(d):
            continue
        frz = datetime.combine(d, component.OPEN, NY) + component.FREEZE_AFTER
        if frz.astimezone(timezone.utc) != et(d, 10, 0):
            bad.append(f"{d} plan freeze {frz.astimezone(timezone.utc):%H:%M} UTC, should be {et(d, 10):%H:%M}")
        close = datetime.combine(d, marketcal.rth_close(d), NY)
        if close.astimezone(timezone.utc) != et(d, cash_close(d).hour):
            bad.append(f"{d} grading close {close:%H:%M} ET, should be {cash_close(d)}")
        end = reactions.session_minutes(close)
        want_end = 210 if d in EARLY else 390
        if end != want_end:
            bad.append(f"{d} minute window {end}, should be {want_end}")
        ts = [int(et(d, 9, 29).timestamp()), int(et(d, 9, 30).timestamp()), int((et(d, cash_close(d).hour) - timedelta(minutes=1)).timestamp()),
              int(et(d, cash_close(d).hour).timestamp())]
        raw = json.dumps({"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [{k: [1.0] * 4 for k in ("open", "high", "low", "close")}]}}]}})
        mins = [m for m, *_ in reactions.parse_minutes(raw.encode(), d, end)]
        if mins != [0, want_end - 1]:
            bad.append(f"{d} 1-minute window kept minutes {mins}, should be [0, {want_end - 1}]")
    # the reaction study's break threshold on a short session: the day's expected move spans that session
    rec = {"ratio": 1.0, "em": 100.0, "index_open": 1000.0, "close_min": 210,
           "bars": [[0, 1000, 1000, 1000], [1, 1010, 1000, 1010],      # 60 minutes later: between the 390- and 210-minute thresholds
                    [61, 1010, 1010, 1010 + reactions.MOVE * 100 * ((60 / 390) ** 0.5 + (60 / 210) ** 0.5) / 2]]}
    if reactions.react(rec, 1010.0)["out"].get(60) != "stall":
        bad.append("reaction thresholds on a 13:00 close use 390 minutes, not the session's 210")
    print(f"{len(days)} days; {n_state} session-state checks; {n_slots} publish slots; holidays and early closes 2026-2028")
    print("RESULT:", "PASS" if not bad else f"FAIL - {len(bad)}:\n  " + "\n  ".join(bad[:40]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
