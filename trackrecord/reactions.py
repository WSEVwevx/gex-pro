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
            MOVE x the move normally expected in h minutes (expected move x sqrt(h / session minutes): 390, or 210 on a 13:00 close) is a BREAK; back on
            the side it came from by as much is a BOUNCE; anything in between is a STALL. A horizon that
            would run past 16:00 is not counted.
Baseline    for every real level, a strike at the same distance from the open (in expected moves, same
            side) on every other recorded session of that market: rounded to the strike grid (strikes are
            round numbers, so the baseline must be too) and dropped when it sits on one of that day's real
            levels. Same touch and outcome rules.
Uncertainty NQ and ES trade together, and one day's levels share that day's tape, so touches are not
            independent: standard errors are clustered by day, with Student's t on (days - 1) degrees of
            freedom. The page tests every level type x horizon at once, so verdicts use Holm's correction:
            the chance that ANY verdict on the page is a false edge stays at 5% (checked on random-walk days by
            tools/stress/reaction_null.py; with per-test 95% ranges, 52% of pure-noise pages showed a false edge).
"""
from __future__ import annotations

import json
import math
import urllib.request
from datetime import date, datetime, time
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
HORIZONS = (5, 15, 60)
TOUCH = 0.01            # a touch: within 1% of the daily expected move (well inside the 5-minute bounce distance)
MOVE = 0.25             # a bounce or break: a quarter of the move expected over the horizon
MIN_TOUCHES = 15        # below this the page says "too few touches" whatever the numbers
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
def session_minutes(close: datetime) -> int:
    """Minutes from 09:30 to the cash close (the app shell's session_close): 390, or 210 on a 13:00 early close."""
    c = close.astimezone(NY)
    return (c.hour * 60 + c.minute) - (9 * 60 + 30)


def parse_minutes(raw: bytes, d: date, end: int = 390) -> list[list]:
    """[[minute after 09:30, open, high, low, close]] for session d, from 09:30 to `end` minutes later (the close)."""
    res = json.loads(raw)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    o = datetime.combine(d, time(9, 30), NY)
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        m = int((datetime.fromtimestamp(ts, NY) - o).total_seconds() // 60)
        if 0 <= m < end and None not in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
            out.append([m, q["open"][i], q["high"][i], q["low"][i], q["close"][i]])
    return out


def fetch_minutes(market: str, d: date, end: int = 390, get=None) -> list[list]:
    """Yahoo keeps 1-minute bars for about 30 days, so each session is saved soon after its close."""
    o = int(datetime.combine(d, time(9, 0), NY).timestamp())
    url = YAHOO.format(sym=FUTURES[market].replace("=", "%3D"), p1=o, p2=o + 8 * 3600)
    if get is None:
        def get(u):
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (GEX PRO track record)"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read()
    return parse_minutes(get(url), d, end)


def minutes_record(session: dict, bars: list[list], end: int = 390) -> Optional[dict]:
    """What is kept per session: the 09:30 ratio and the bars, in futures points (about 10 KB)."""
    out, plan = session.get("outcome") or {}, session.get("plan") or {}
    if not bars or bars[0][0] != 0 or not out.get("open") or not plan.get("em"):
        return None
    ratio = bars[0][1] / out["open"]
    return {"session": session["session"], "market": session["market"], "underlying": plan.get("underlying"),
            "index_open": out["open"], "ratio": round(ratio, 6), "em": plan["em"],
            "close_min": end,
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
        th = MOVE * em * math.sqrt(hz / rec.get("close_min", 390))     # the day's band spans its own session
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


ALPHA = 0.05            # chance that ANY verdict on the page is a false edge (Holm across every test shown)


def _betacf(a: float, b: float, x: float) -> float:
    """Lentz's continued fraction for the regularised incomplete beta function."""
    tiny, qab, qap, qam = 1e-300, a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)), -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1 + aa * d
            d = 1 / (d if abs(d) > tiny else tiny)
            c = 1 + aa / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1) < 1e-15:
            break
    return h


def _t_sf2(t: float, df: int) -> float:
    """Two-sided p-value of Student's t with df degrees of freedom: I_{df/(df+t^2)}(df/2, 1/2)."""
    if df <= 0 or math.isnan(t):
        return 1.0
    x = df / (df + t * t)
    a, b = df / 2.0, 0.5
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return min(1.0, front * _betacf(a, b, x) / a)
    return min(1.0, max(0.0, 1 - front * _betacf(b, a, 1 - x) / b))


def _t_quantile(conf: float, df: int) -> float:
    """t such that the two-sided p-value is 1 - conf (bisection)."""
    lo, hi = 0.0, 200.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if _t_sf2(mid, df) > 1 - conf:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _cluster(per: list) -> dict:
    """Level rate, random-strike rate and their difference with day-clustered (linearised) standard errors.
    per: one [level hits, level touches, random hits, random touches] per day."""
    k, n, k0, n0 = (sum(c[i] for c in per) for i in range(4))
    out = {"k": k, "n": n, "k0": k0, "n0": n0}
    if n:
        out["p1"] = k / n
    if n0:
        out["p0"] = k0 / n0
    if not n or not n0:
        return out                                      # a rate without its comparison: no test
    p1, p0 = out["p1"], out["p0"]
    used = [c for c in per if c[1] or c[3]]
    D = len(used)
    if D < 2:
        return out
    f = D / (D - 1)
    e1 = [(c[0] - p1 * c[1]) / n for c in used]           # each day's contribution to the level rate's error
    e0 = [(c[2] - p0 * c[3]) / n0 for c in used]
    out.update(se1=math.sqrt(f * sum(x * x for x in e1)),
               sed=math.sqrt(f * sum((x - y) ** 2 for x, y in zip(e1, e0))),   # same days: their covariance counts
               df=D - 1)
    return out


def summarize(obs: list[dict], seed: int = 7) -> dict:
    """{"types": [...], "days": n} with, per type and horizon, the level's and the random strikes' rates of
    bounce / break / stall, a 95% range for the level's rate, a p-value for the difference, and a verdict.

    Inference: day-clustered standard errors (NQ and ES share a day's tape, and one day's levels share it too)
    and Student's t with (days - 1) degrees of freedom. Every bounce and break test on the page (each level
    type x horizon with enough touches) is one family; Holm's correction keeps the chance of any false
    verdict on the page at ALPHA. Checked by tools/stress/reaction_null.py on random-walk days.
    `seed` is unused (the method has no randomness); kept so callers need not change."""
    days = sorted({o["day"] for o in obs})
    counts: dict = {d: {} for d in days}
    for o in obs:
        for hz, res in o["out"].items():
            for what in ("bounce", "break", "stall"):
                c = counts[o["day"]].setdefault((o["type"], int(hz), what), [0, 0, 0, 0])
                j = 0 if o["real"] else 2
                c[j] += res == what
                c[j + 1] += 1
    out, tests = [], []
    for typ, name in TYPES:
        row = {"type": typ, "name": name, "h": {}}
        for hz in HORIZONS:
            cell = {}
            for what in ("bounce", "break", "stall"):
                st = _cluster([counts[d].get((typ, hz, what), [0, 0, 0, 0]) for d in days])
                rate, ci, p = st.get("p1"), None, None
                if st.get("se1") is not None:
                    q = _t_quantile(0.95, st["df"])
                    ci = [round(max(0.0, rate - q * st["se1"]), 3), round(min(1.0, rate + q * st["se1"]), 3)]
                if st.get("sed") is not None:
                    diff = st["p1"] - st["p0"]
                    p = (1.0 if diff == 0 else 0.0) if st["sed"] == 0 else _t_sf2(diff / st["sed"], st["df"])
                cell[what] = {"k": st["k"], "n": st["n"], "rate": round(rate, 3) if rate is not None else None, "ci": ci,
                              "random": round(st["p0"], 3) if st.get("p0") is not None else None, "random_n": st["n0"],
                              "p": round(p, 6) if p is not None else None}
                if what != "stall" and p is not None and st["n"] >= MIN_TOUCHES:
                    tests.append((p, typ, hz, what, st["p1"] - st["p0"]))
            cell["touches"] = cell["bounce"]["n"]
            cell["verdict"] = "few" if cell["touches"] < MIN_TOUCHES else "none"
            row["h"][str(hz)] = cell
        out.append(row)
    tests.sort(key=lambda t: t[0])
    best: dict = {}
    for i, (p, typ, hz, what, diff) in enumerate(tests):     # Holm: stop at the first test that fails
        if p > ALPHA / (len(tests) - i):
            break
        if (typ, hz) not in best:
            best[(typ, hz)] = (what, diff)
    for row in out:
        for hz in HORIZONS:
            hit = best.get((row["type"], hz))
            if hit:
                what, diff = hit
                row["h"][str(hz)]["verdict"] = what if diff > 0 else ("fewer_bounces" if what == "bounce" else "fewer_breaks")
    return {"days": len(days), "types": out, "tests": len(tests),
            "rules": {"touch_em": TOUCH, "move": MOVE, "horizons": list(HORIZONS), "min_touches": MIN_TOUCHES,
                      "alpha": ALPHA, "method": "day-clustered t test, Holm across the page"}}
