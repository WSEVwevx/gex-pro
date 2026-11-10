"""How price reacted the first time it reached each GEX PRO level, against random strikes at the same distance.

The question: when price first trades to a level after the 09:30 open, does it bounce, break or stall more
often than it does at an ordinary strike the same distance away? Every rule below was fixed before any
result was looked at; nothing is tuned to make the levels look good.

Levels      the 09:30 plan (zero gamma, call wall, put wall, abs gamma; every session since the record began)
            plus, where the 09:30 paste was saved, the ranked call / put levels, the 0DTE levels, the
            expected-move edges and the volume / open-interest walls. Index points, as computed.
Prices      1-minute futures bars (NQ=F / ES=F, Yahoo, free), 09:30-16:00 ET. Levels are converted to
            futures with that morning's ratio (futures open / index open at 09:30), as the indicator does.
Touch       a level above the open is tested from below, one below from above; the first bar that trades
            within TOUCH (1%) of the daily expected move of it. Levels that close to the open are skipped.
Outcome     h = 5, 15 and 60 minutes after the touch bar: price past the level by at least
            MOVE x the move normally expected in h minutes (expected move x sqrt(h / 390)) is a BREAK; back on
            the side it came from by as much is a BOUNCE; anything in between is a STALL. A horizon that
            would run past 16:00 is not counted.
Baseline    for every real level, a strike at the same distance from the open (in expected moves, same
            side) on every other recorded session of that market: rounded to the strike grid (strikes are
            round numbers, so the baseline must be too) and dropped when it sits on one of that day's real
            levels. Same touch and outcome rules.
Uncertainty NQ and ES trade together, and one day's levels share that day's tape, so touches are not
            independent. The 95% ranges come from resampling whole days (bootstrap, fixed seed), and a
            level type has an edge only when the range of (level rate - random rate) excludes zero.
"""
from __future__ import annotations

import json
import math
import random
import urllib.request
from datetime import date, datetime, time
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from gexsys.marketcal import rth_close

NY = ZoneInfo("America/New_York")
HORIZONS = (5, 15, 60)
TOUCH = 0.01            # a touch: within 1% of the daily expected move (well inside the 5-minute bounce distance)
MOVE = 0.25             # a bounce or break: a quarter of the move expected over the horizon
MIN_TOUCHES = 15        # below this the page says "too few touches" whatever the numbers
BOOT = 2000
GRID = {"NDX": 10.0, "SPX": 5.0}                     # index strike spacing near the money
FUTURES = {"NQ": "NQ=F", "ES": "ES=F"}
TYPES = [("zg", "Zero gamma"), ("cw", "Call wall"), ("pw", "Put wall"), ("ag", "Abs gamma"),
         ("calls", "Other call levels"), ("puts", "Other put levels"), ("odte", "0DTE levels"),
         ("em", "Expected-move edges"), ("flow", "Volume / OI walls")]
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&period1={p1}&period2={p2}"


# ---------------------------------------------------------------------------- levels
def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def paste_tokens(text: str) -> dict:
    out = {}
    for t in (text or "").split(";"):
        k, sep, v = t.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def session_levels(plan: dict, paste: Optional[str] = None) -> list[tuple[str, float]]:
    """[(type, index price)], one entry per type and price (a price can be several types)."""
    lv = [(k, _num(plan.get(k))) for k in ("zg", "cw", "pw", "ag")]
    t = paste_tokens(paste) if paste else {}
    if t:
        for item in t.get("R", "").split(","):
            p = _num(item[1:].split(":")[0]) if item[:1] in "CP" else None
            if p and p != _num(plan.get("cw" if item[0] == "C" else "pw")):
                lv.append(("calls" if item[0] == "C" else "puts", p))
        lv += [("odte", _num(t.get(k))) for k in ("z0", "c0", "p0")]
        ema, emd = _num(t.get("ema")), _num(t.get("emd"))
        if ema and emd:
            lv += [("em", ema + emd), ("em", ema - emd)]
        lv += [("flow", _num(t.get(k))) for k in ("vc", "vp", "oc", "op")]
    seen, out = set(), []
    for k, p in lv:
        if p and (k, round(p, 2)) not in seen:
            seen.add((k, round(p, 2)))
            out.append((k, p))
    return out


# ---------------------------------------------------------------------------- 1-minute futures bars
def session_minutes(d: date) -> int:
    """Minutes from 09:30 to the cash close: 390, or 210 on a 13:00 early close."""
    c = rth_close(d)
    return (c.hour * 60 + c.minute) - (9 * 60 + 30)


def parse_minutes(raw: bytes, d: date) -> list[list]:
    """[[minute after 09:30, open, high, low, close]] for session d, from 09:30 to the cash close (ET)."""
    res = json.loads(raw)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    o = datetime.combine(d, time(9, 30), NY)
    end = session_minutes(d)
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        m = int((datetime.fromtimestamp(ts, NY) - o).total_seconds() // 60)
        if 0 <= m < end and None not in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
            out.append([m, q["open"][i], q["high"][i], q["low"][i], q["close"][i]])
    return out


def fetch_minutes(market: str, d: date, get=None) -> list[list]:
    """Yahoo keeps 1-minute bars for about 30 days, so each session is saved soon after its close."""
    o = int(datetime.combine(d, time(9, 0), NY).timestamp())
    url = YAHOO.format(sym=FUTURES[market].replace("=", "%3D"), p1=o, p2=o + 8 * 3600)
    if get is None:
        def get(u):
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (GEX PRO track record)"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read()
    return parse_minutes(get(url), d)


def minutes_record(session: dict, bars: list[list]) -> Optional[dict]:
    """What is kept per session: the 09:30 ratio and the bars, in futures points (about 10 KB)."""
    out, plan = session.get("outcome") or {}, session.get("plan") or {}
    if not bars or bars[0][0] != 0 or not out.get("open") or not plan.get("em"):
        return None
    ratio = bars[0][1] / out["open"]
    return {"session": session["session"], "market": session["market"], "underlying": plan.get("underlying"),
            "index_open": out["open"], "ratio": round(ratio, 6), "em": plan["em"],
            "close_min": session_minutes(date.fromisoformat(session["session"])),
            "bars": [[m, round(h, 2), round(lo, 2), round(c, 2)] for m, _o, h, lo, c in bars]}


# ---------------------------------------------------------------------------- one level, one session
def react(rec: dict, level_idx: float) -> Optional[dict]:
    """The first touch of one level (index points) in one session: {"side", "dist", "touched", out per horizon}.
    None when the level sits at the open (no side to come from)."""
    r, em = rec["ratio"], rec["em"] * rec["ratio"]
    L, o = level_idx * r, rec["index_open"] * r
    tol = TOUCH * em
    if abs(L - o) <= tol:
        return None
    side = 1 if L > o else -1                     # +1: tested from below (resistance), -1: from above (support)
    bars = rec["bars"]
    hit = next((i for i, (m, h, lo, c) in enumerate(bars) if (h >= L - tol if side > 0 else lo <= L + tol)), None)
    res = {"side": side, "dist": round((L - o) / em, 4), "touched": hit is not None, "minute": None, "out": {}}
    if hit is None:
        return res
    t0 = bars[hit][0]
    res["minute"] = t0
    at = {m: c for m, h, lo, c in bars}
    for hz in HORIZONS:
        if t0 + hz >= rec.get("close_min", 390):
            continue                                # would run past the close (16:00, or 13:00 on early closes)
        c = at.get(t0 + hz)
        if c is None:                               # a missing minute: the last close before it
            prior = [x for x in bars if x[0] <= t0 + hz]
            c = prior[-1][3]
        th = MOVE * em * math.sqrt(hz / 390.0)
        through = (c - L) * side
        res["out"][hz] = "break" if through >= th else "bounce" if through <= -th else "stall"
    return res


# ---------------------------------------------------------------------------- the study
def _strike(p: float, grid: float) -> float:
    return round(p / grid) * grid


def observations(records: Iterable[dict], levels: dict) -> list[dict]:
    """Every real and random-strike touch: {"day", "type", "real", "out": {h: result}}.
    records: minutes records; levels: {(session, market): [(type, index price)]}."""
    recs = [r for r in records if levels.get((r["session"], r["market"]))]
    obs = []
    for rec in recs:
        key = (rec["session"], rec["market"])
        mine = levels[key]
        for typ, p in mine:
            x = react(rec, p)
            if x and x["touched"]:
                obs.append({"day": rec["session"], "type": typ, "real": True, "out": x["out"]})
            if not x:
                continue
            for other in recs:                      # the same distance on every other day of this market
                if other is rec or other["market"] != rec["market"]:
                    continue
                grid = GRID.get(other.get("underlying") or "", 5.0)
                q = _strike(other["index_open"] + x["dist"] * other["em"], grid)
                tol = TOUCH * other["em"]
                if any(abs(q - lp) <= tol for _, lp in levels[(other["session"], other["market"])]):
                    continue                        # that day's real level: not a random strike
                y = react(other, q)
                if y and y["touched"]:
                    obs.append({"day": other["session"], "type": typ, "real": False, "out": y["out"]})
    return obs


def summarize(obs: list[dict], seed: int = 7) -> dict:
    """{"types": [...], "days": n} with, per type and horizon, the level's and the random strikes' rates of
    bounce / break / stall, a day-bootstrap 95% range for the level's rate and for the difference, and a verdict."""
    days = sorted({o["day"] for o in obs})
    # per day: counts[day][(type, h, what)] = [level hits, level touches, random hits, random touches]
    counts: dict = {d: {} for d in days}
    for o in obs:
        for hz, res in o["out"].items():
            for what in ("bounce", "break", "stall"):
                c = counts[o["day"]].setdefault((o["type"], int(hz), what), [0, 0, 0, 0])
                j = 0 if o["real"] else 2
                c[j] += res == what
                c[j + 1] += 1
    rng = random.Random(seed)
    samples = [[rng.randrange(len(days)) for _ in days] for _ in range(BOOT)] if days else []
    ci = lambda xs: [round(xs[int(0.025 * (len(xs) - 1))], 3), round(xs[int(0.975 * (len(xs) - 1))], 3)] if len(xs) > 50 else None
    out = []
    for typ, name in TYPES:
        row = {"type": typ, "name": name, "h": {}}
        for hz in HORIZONS:
            cell = {}
            for what in ("bounce", "break", "stall"):
                per = [counts[d].get((typ, hz, what), [0, 0, 0, 0]) for d in days]
                k, n, k0, n0 = (sum(c[i] for c in per) for i in range(4))
                rates, diffs = [], []
                for smp in samples:
                    a = an = b = bn = 0
                    for i in smp:
                        c = per[i]
                        a, an, b, bn = a + c[0], an + c[1], b + c[2], bn + c[3]
                    if an and bn:
                        rates.append(a / an)
                        diffs.append(a / an - b / bn)
                rates.sort()
                diffs.sort()
                cell[what] = {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "ci": ci(rates),
                              "random": round(k0 / n0, 3) if n0 else None, "random_n": n0, "diff_ci": ci(diffs)}
            n = cell["bounce"]["n"]
            verdict = "few"
            if n >= MIN_TOUCHES:
                verdict = "none"
                for what in ("bounce", "break"):
                    d = cell[what]["diff_ci"]
                    if d and d[0] > 0:
                        verdict = what               # reliably more bounces (or breaks) than random strikes
                if verdict == "none" and cell["bounce"]["diff_ci"] and cell["bounce"]["diff_ci"][1] < 0:
                    verdict = "fewer_bounces"
            cell["touches"], cell["verdict"] = n, verdict
            row["h"][str(hz)] = cell
        out.append(row)
    return {"days": len(days), "types": out,
            "rules": {"touch_em": TOUCH, "move": MOVE, "horizons": list(HORIZONS), "min_touches": MIN_TOUCHES, "boot": BOOT}}
