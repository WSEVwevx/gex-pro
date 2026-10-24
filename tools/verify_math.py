"""Independent re-derivation of the GEX numbers from the raw Cboe responses.

Shares NOTHING with gexsys's math: own OCC parsing, own expiry times, own BSM gamma, own ETF handling
(ETF options are valued in the ETF's OWN price/strike/dividend, never converted), own strike buckets,
own walls and own zero-gamma search.  The raw JSON is fetched once and fed to both sides.

Run from the project folder: python tools/verify_math.py (or all checks: python tools/check.py).
EARLY lists the half-day closes; add next year's when the calendar rolls over.
"""
import json
import math
import re
import sys
import urllib.request
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, ".")
NY = ZoneInfo("America/New_York")
YEAR = 365.0 * 86400
R = 0.04
Q = {"SPX": 0.013, "SPY": 0.013, "NDX": 0.007, "QQQ": 0.006}
EARLY = {date(2026, 11, 27): time(13, 0), date(2026, 12, 24): time(13, 0)}
MAX_DTE = 45


def fetch(sym):
    req = urllib.request.Request(f"https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json",
                                 headers={"User-Agent": "Mozilla/5.0 (verify)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def occ(s):
    m = re.fullmatch(r"([A-Z]{1,6})(\d{6})([CP])(\d{8})", s or "")
    if not m:
        return None
    d = datetime.strptime(m.group(2), "%y%m%d").date()
    return m.group(1), d, m.group(3), int(m.group(4)) / 1000


def expiry(root, d):
    if root in ("SPX", "NDX"):                       # AM-settled monthlies: opening print
        return datetime.combine(d, time(9, 30), NY)
    return datetime.combine(d, EARLY.get(d, time(16, 0)), NY)


def gamma(s, k, t, q, v):
    t = max(t, 1 / (365 * 24 * 60))
    d1 = (math.log(s / k) + (R - q + v * v / 2) * t) / (v * math.sqrt(t))
    return math.exp(-q * t) * math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi) / (s * v * math.sqrt(t))


def price(s, k, t, q, v, call):
    t = max(t, 1 / (365 * 24 * 60))
    d1 = (math.log(s / k) + (R - q + v * v / 2) * t) / (v * math.sqrt(t))
    d2 = d1 - v * math.sqrt(t)
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    if call:
        return s * math.exp(-q * t) * N(d1) - k * math.exp(-R * t) * N(d2)
    return k * math.exp(-R * t) * N(-d2) - s * math.exp(-q * t) * N(-d1)


def solve_iv(target, s, k, t, q, call):
    lo, hi = 1e-4, 5.0
    if not (price(s, k, t, q, lo, call) <= target <= price(s, k, t, q, hi, call)):
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if price(s, k, t, q, mid, call) < target else (lo, mid)
    return (lo + hi) / 2


def rows_of(raw, key, asof, q_solve=None):
    today = datetime.strptime(raw["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(NY).date()
    out, strikes, smile = [], set(), []
    for o in raw["data"]["options"]:
        p = occ(o.get("option"))
        if not p:
            continue
        root, d, cp, k = p
        if not (0 <= (d - today).days <= MAX_DTE):
            continue
        strikes.add(k)
        e = expiry(root, d)
        t = (e - asof).total_seconds() / YEAR
        oi, iv = o.get("open_interest") or 0, o.get("iv") or 0
        if t <= 0 or t * 365 > MAX_DTE + 1e-9:
            continue
        quoted = 0 < iv <= 5
        if quoted:
            smile.append((e, k, float(iv)))
        if oi <= 0:
            continue
        if not quoted:                                 # Cboe IV missing/bad: solve it from the bid/ask mid
            b, a = o.get("bid"), o.get("ask")
            iv = None
            if b is not None and a is not None and a > 0 and b >= 0 and a >= b:
                iv = solve_iv((a + b) / 2, float(raw["data"]["current_price"]), k, t, q_solve, cp == "C")
        out.append({"root": root, "cp": cp, "k": k, "t": t, "e": e, "oi": float(oi), "iv": iv})
    return out, sorted(strikes), smile


def snap_to(k, strikes, tol):
    import bisect
    i = bisect.bisect_left(strikes, k)
    near = min((strikes[j] for j in (i - 1, i) if 0 <= j < len(strikes)), key=lambda s: abs(s - k))
    return near if abs(near - k) <= tol else round(k, 2)


def independent(raw_i, raw_e, idx, etf, asof):
    S, Se = float(raw_i["data"]["current_price"]), float(raw_e["data"]["current_price"])
    ri, istrikes, ismile = rows_of(raw_i, idx, asof, Q[idx])
    re_, _, esmile = rows_of(raw_e, etf, asof, Q[etf])   # ETF IV solved in its own terms
    gaps = sorted(b - a for a, b in zip(istrikes, istrikes[1:]))
    tol = 0.75 * gaps[len(gaps) // 2]
    ratio = S / Se
    # no usable IV at all: borrow the nearest strike's (index terms) in the same expiration
    smile = {}
    for e, k, v in ismile:
        smile.setdefault(e, []).append((k, v))
    for e, k, v in esmile:
        smile.setdefault(e, []).append((snap_to(k * ratio, istrikes, tol), v))
    def fill(r, k_idx):
        if r["iv"] is None and smile.get(r["e"]):
            r["iv"] = min(smile[r["e"]], key=lambda kv: abs(kv[0] - k_idx))[1]
        return r["iv"]
    legs = []                      # (index-terms strike, cp, oi in its own contracts, own S, own K, own q, t, iv)
    for r in ri:
        if fill(r, r["k"]):
            legs.append((r["k"], r["cp"], r["oi"], S, r["k"], Q[idx], r["t"], r["iv"]))
    for r in re_:
        k_idx = snap_to(r["k"] * ratio, istrikes, tol)
        if fill(r, k_idx):
            legs.append((k_idx, r["cp"], r["oi"], Se, r["k"], Q[etf], r["t"], r["iv"]))

    def dollar(leg, move=1.0):     # $ gamma per 1% for the leg, with the underlying scaled by `move`
        _, cp, oi, s, k, q, t, iv = leg
        s = s * move
        return (1 if cp == "C" else -1) * oi * gamma(s, k, t, q, iv) * 100 * s * s * 0.01

    by = {}
    for leg in legs:
        v = dollar(leg)
        b = by.setdefault(leg[0], {"call": 0.0, "put": 0.0, "abs": 0.0})
        b["call" if leg[1] == "C" else "put"] += v
        b["abs"] += abs(v)
    net = sum(b["call"] + b["put"] for b in by.values())
    cw = max((k for k in by if k >= S and by[k]["call"]), key=lambda k: abs(by[k]["call"]))
    pw = max((k for k in by if k <= S and by[k]["put"]), key=lambda k: abs(by[k]["put"]))
    ag = max(by, key=lambda k: by[k]["abs"])
    # zero gamma: same grid (+-5%, 201 points), every leg re-priced with its own underlying moved by the same %
    grid = [(1 - 0.05) + 0.10 * i / 200 for i in range(201)]
    prof = [(S * m, sum(dollar(leg, m) for leg in legs)) for m in grid]
    xs = [p0 + (p1 - p0) * (-v0) / (v1 - v0) for (p0, v0), (p1, v1) in zip(prof, prof[1:]) if v0 * v1 < 0]
    zg = min(xs, key=lambda x: abs(x - S)) if xs else None
    return {"spot": S, "ratio": ratio, "legs": len(legs), "net": net, "cw": cw, "pw": pw, "ag": ag, "zg": zg}


def main():
    from gexsys import config as cfgmod
    from gexsys.pipeline import run_once
    from gexsys.providers.cboe import CboeProvider
    bad = 0
    for cfg, idx, etf, sym_i, sym_e in (("configs/free_es_cboe.json", "SPX", "SPY", "_SPX", "SPY"),
                                        ("configs/free_nq_cboe.json", "NDX", "QQQ", "_NDX", "QQQ")):
        raw = {sym_i: fetch(sym_i), sym_e: fetch(sym_e)}
        prov = CboeProvider(http=lambda url, headers, limiter=None: raw[url.rsplit("/", 1)[1][:-5]], include_etf=True)
        c = cfgmod.load(cfg)
        res = run_once(c, prov)
        s = res["summary"]
        asof = datetime.fromisoformat(s["asof"])
        ind = independent(raw[sym_i], raw[sym_e], idx, etf, asof)
        p = lambda x: (x or {}).get("price") if isinstance(x, dict) else x
        checks = [
            ("reference price", s["ref_price"], ind["spot"], 1e-9),
            ("net GEX $/1%", s["net"], ind["net"], 2e-3),
            ("call wall", p(s["call_wall"]), ind["cw"], 0),
            ("put wall", p(s["put_wall"]), ind["pw"], 0),
            ("abs gamma strike", p(s["abs_gamma"]), ind["ag"], 0),
            ("zero gamma", p(s["zero_gamma"]), ind["zg"], 1e-3),
        ]
        print(f"\n{idx}+{etf}  ratio {ind['ratio']:.4f}  legs {ind['legs']}  asof {asof:%H:%M:%S}Z")
        for name, a, b, tol in checks:
            if a is None or b is None:
                ok = a == b
            else:
                ok = abs(a - b) <= tol * max(abs(b), 1) if tol else a == b
            bad += not ok
            print(f"  {'OK  ' if ok else 'DIFF'} {name:18s} engine {a!s:>22}   independent {b!s:>22}")
        # futures mapping: payload factor x index level = mapped level (tick-rounded)
        m = res["mapped"]
        fac = m["mapping"].get("factor") if m else None
        if m and fac:
            zg_f = p(m["zero_gamma"])
            ok = abs(zg_f - p(s["zero_gamma"]) * fac) <= 0.25
            bad += not ok
            print(f"  {'OK  ' if ok else 'DIFF'} futures mapping    ZG {p(s['zero_gamma']):.2f} x {fac:.6f} = {zg_f}")
    print("\nALL MATCH" if not bad else f"\n{bad} DIFFERENCES")
    return bad


if __name__ == "__main__":
    sys.exit(main())
