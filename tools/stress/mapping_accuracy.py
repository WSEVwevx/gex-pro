"""Stress test C1: how exactly the indicator puts an index-price level on the futures chart.

  python tools/stress/mapping_accuracy.py

The indicator draws an index level L at L x (futures / index) from the newest minute both traded (the live ratio).
Free 1-minute bars (Yahoo: NQ=F with ^NDX, ES=F with ^GSPC; about 20 sessions) give that ratio every RTH minute:
  spec       placement by the live ratio vs placement by the carry fair value F = S exp((r - q) T) at the same
             minute (r 4%, q 0.7% NDX / 1.3% SPX, T to the front quarterly expiry), for a level at price, in points
  noise      how much the drawn level moves from one minute to the next because of the ratio alone
  overnight  the ratio held from 16:00 against the ratio at the next 09:30 open
  smoothing  the fix for the noise: the median of the last N matched minutes. N is chosen on the first half of the
             sessions and validated on the second, against a centered 31-minute median of the ratio (that window looks
             ahead, so it is only a yardstick here, never something the indicator could use)
Tolerance (fixed before running): the spec error's 95th percentile within 1 tick (0.25) in RTH.
Not testable from this data: a roll date and an early close (none in the free 1-minute window).
"""
from __future__ import annotations

import json
import math
import statistics
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gexsys import marketcal  # noqa: E402

NY = marketcal.NY
R = 0.04
PAIRS = {"NQ": ("NQ=F", "^NDX", 0.007), "ES": ("ES=F", "^GSPC", 0.013)}
TICK = 0.25


def minutes(sym: str) -> dict:
    out, p2 = {}, int(time.time())
    for _ in range(4):
        p1 = p2 - 7 * 86400
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym.replace('^', '%5E').replace('=', '%3D')}?interval=1m&period1={p1}&period2={p2}"
        try:
            d = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (GEX PRO stress)"}), timeout=30).read())["chart"]["result"][0]
            q = d["indicators"]["quote"][0]
            for i, ts in enumerate(d.get("timestamp") or []):
                if q["close"][i] is not None:
                    out[ts - ts % 60] = q["close"][i]
        except Exception as e:
            print(f"  {sym}: {e}")
        p2 = p1
    return out


def front_expiry(d: date) -> date:
    """Quarterly index futures expire on the 3rd Friday of Mar / Jun / Sep / Dec (the contract after the roll)."""
    y, m = d.year, d.month
    while True:
        if m in (3, 6, 9, 12):
            e = marketcal.third_friday(y, m)
            if e - timedelta(days=8) > d:          # the conventional roll: 8 days before expiry
                return e
        m += 1
        if m > 12:
            y, m = y + 1, 1


CANDIDATES = (1, 5, 10, 15, 20, 30)
YARD = 15                  # the yardstick: a centered 31-minute median


def smoothed(seq: list, n: int) -> list:
    """The indicator's ratio: the median of the last n matched minutes (seq: one session's minute ratios)."""
    return [statistics.median(seq[max(0, i - n + 1): i + 1]) for i in range(len(seq))]


def smoothing_errors(sessions: list, n: int) -> tuple[list, list]:
    """[(ratio, price)] per session -> (errors vs the yardstick, minute-to-minute jitter), in points at price."""
    err, jit = [], []
    for seq in sessions:
        r = [x for x, _ in seq]
        sm = smoothed(r, n)
        for i in range(YARD, len(seq) - YARD):
            err.append(abs(seq[i][1] * (sm[i] - statistics.median(r[i - YARD: i + YARD + 1]))))
            jit.append(abs(seq[i][1] * (sm[i] - sm[i - 1])))
    return err, jit


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * (len(xs) - 1)))] if xs else float("nan")


def main() -> int:
    fails, sessions = [], {}
    for mkt, (fsym, isym, q) in PAIRS.items():
        fut, idx = minutes(fsym), minutes(isym)
        both = sorted(t for t in idx if t in fut)
        rows = []
        for t in both:
            dt = datetime.fromtimestamp(t, NY)
            if marketcal.session_state(dt) != "RTH":
                continue
            s, f = idx[t], fut[t]
            T = (datetime.combine(front_expiry(dt.date()), datetime.min.time(), NY) - dt).total_seconds() / (365 * 86400)
            rows.append((dt, s, f / s, math.exp((R - q) * T)))
        if not rows:
            fails.append(f"{mkt}: no data")
            continue
        days = sorted({r[0].date() for r in rows})
        spec = [abs(s * (r - fair)) for _, s, r, fair in rows]
        bias = statistics.median(s * (r - fair) for _, s, r, fair in rows)
        noise = [abs(rows[i][1] * (rows[i][2] - rows[i - 1][2])) for i in range(1, len(rows))
                 if (rows[i][0] - rows[i - 1][0]).total_seconds() == 60]
        print(f"\n{mkt}: {len(rows)} RTH minutes over {len(days)} sessions ({days[0]} to {days[-1]})")
        print(f"  spec  live ratio vs carry fair value: median {statistics.median(spec):.2f} pts, 95th {pct(spec, .95):.2f}, "
              f"max {max(spec):.2f}; median signed {bias:+.2f} (the market's premium over a 4% carry)")
        for name, lo, hi in (("09:30-10:30", 570, 630), ("10:30-15:00", 630, 900), ("15:00-16:00", 900, 960)):
            part = [e for (dt, *_), e in zip(rows, spec) if lo <= dt.hour * 60 + dt.minute < hi]
            print(f"        {name}: 95th {pct(part, .95):.2f} pts")
        print(f"  noise minute-to-minute move of a level at price from the ratio alone: median {statistics.median(noise):.2f}, "
              f"95th {pct(noise, .95):.2f}, max {max(noise):.2f} pts")
        # overnight: the ratio held from the last RTH minute vs the next session's first
        held = []
        for a, b in zip(days, days[1:]):
            last = [r for r in rows if r[0].date() == a][-1]
            first = [r for r in rows if r[0].date() == b][0]
            held.append(abs(first[1] * (first[2] - last[2])))
        print(f"  overnight  held 16:00 ratio vs next 09:30: median {statistics.median(held):.2f}, max {max(held):.2f} pts")
        by_day: dict = {}
        for dt, sp, r, _ in rows:
            by_day.setdefault(dt.date(), []).append((r, sp))
        sessions[mkt] = [by_day[d] for d in days]
        if pct(spec, .95) > TICK:
            fails.append(f"{mkt} spec 95th {pct(spec, .95):.2f} > {TICK}")
    # one N for both markets (the indicator has one): the smallest summed 95th error relative to the newest minute,
    # on the first half of the sessions; then checked on the second half, which played no part in choosing it
    score = {n: 0.0 for n in CANDIDATES}
    for sess in sessions.values():
        half = len(sess) // 2
        fit = {n: pct(smoothing_errors(sess[:half], n)[0], .95) for n in CANDIDATES}
        for n in CANDIDATES:
            score[n] += fit[n] / fit[1]
    best = min(score, key=score.get)
    print("\nsmoothing (first half, summed 95th error relative to the newest minute): "
          + ", ".join(f"N={n} {v:.3f}" for n, v in score.items()) + f"  -> N={best}")
    for mkt, sess in sessions.items():
        half = len(sess) // 2
        e1, j1 = smoothing_errors(sess[half:], 1)
        eb, jb = smoothing_errors(sess[half:], best)
        print(f"  {mkt} validation ({len(sess) - half} later sessions): newest minute 95th {pct(e1, .95):.2f}, jitter 95th "
              f"{pct(j1, .95):.2f}; median of {best}: 95th {pct(eb, .95):.2f}, jitter 95th {pct(jb, .95):.2f} pts")
        if pct(eb, .95) >= pct(e1, .95) or pct(jb, .95) >= pct(j1, .95):
            fails.append(f"{mkt} smoothing does not validate")
    print("\nnot testable here: a roll date and an early close (none inside the free 1-minute window)")
    print("RESULT:", "PASS" if not fails else "FAIL - " + "; ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
