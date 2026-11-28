"""Independent re-derivation of the GEX numbers from the raw OCC and Yahoo responses.

Shares NOTHING with gexsys's math: own OCC parsing, own session dates (the days ^GSPC traded, from Yahoo's own daily
bars, never gexsys.marketcal), own vol date and VIX-family curve, own expiry times, own BSM gamma, own ETF handling
(ETF options are valued in the ETF's OWN price/strike/dividend, never converted), own strike buckets, own walls and own
zero-gamma search. Every raw answer is fetched once and fed to both sides; the engine reads it through a stub opener
at the same frozen clock.

Run from the project folder: python tools/verify_math.py (or all checks: python tools/check.py).
EARLY lists the half-day closes; add next year's when the calendar rolls over.
"""
import io
import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, ".")
NY = ZoneInfo("America/New_York")
YEAR = 365.0 * 86400
R = 0.04
Q = {"SPX": 0.013, "SPY": 0.013, "NDX": 0.007, "QQQ": 0.006}
EARLY = {date(2026, 11, 27): time(13, 0), date(2026, 12, 24): time(13, 0)}
MAX_DTE = 45
STANDARD = {"SPX": {"SPX", "SPXW"}, "NDX": {"NDX", "NDXP"}, "SPY": {"SPY"}, "QQQ": {"QQQ"}}
CURVE = {"VIX1D": 1, "VIX9D": 9, "VIX": 30, "VIX3M": 93}
YSYM = {"NDX": "^NDX", "SPX": "^GSPC", "QQQ": "QQQ", "SPY": "SPY"}
UA = {"User-Agent": "Mozilla/5.0 (GEX PRO verify)"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read()


def occ_url(sym):
    return f"https://marketdata.theocc.com/series-search?symbolType=U&symbol={sym}"


def chart_url(sym, rng):
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval=1d"


def occ_rows(text):
    """(product, expiry date, strike, call OI, put OI): tab-separated, strike = integer part + thousandths."""
    out = []
    for line in text.decode("utf-8", "replace").split("\n"):
        f = [x.strip() for x in line.split("\t")]
        try:
            out.append((f[0], date(int(f[2]), int(f[3]), int(f[4])), int(f[5]) + int(f[6]) / 1000, float(f[8] or 0), float(f[9] or 0)))
        except (IndexError, ValueError):
            continue
    return out


def bars(raw):
    """{date in the exchange's zone: close} from a Yahoo daily chart, closes rounded to 2 decimals (as published)."""
    r = json.loads(raw)["chart"]["result"][0]
    z = ZoneInfo(r["meta"]["exchangeTimezoneName"])
    return {datetime.fromtimestamp(t, z).date(): round(c, 2) for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c}


def close_at(d):
    return datetime.combine(d, EARLY.get(d, time(16, 0)), NY)


def expiry(root, d):
    if root in ("SPX", "NDX"):                       # AM-settled monthlies: opening print
        return datetime.combine(d, time(9, 30), NY)
    return close_at(d)


def gamma(s, k, t, q, v):
    t = max(t, 1 / (365 * 24 * 60))
    d1 = (math.log(s / k) + (R - q + v * v / 2) * t) / (v * math.sqrt(t))
    return math.exp(-q * t) * math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi) / (s * v * math.sqrt(t))


def vols(raw, idx, sessions, now):
    """The curve [(days, vol)] and the NDX scale, from the closes of the last session finished 30 min before now (or,
    per series, the session before it)."""
    done = [d for d in sessions if close_at(d) + timedelta(minutes=30) <= now]
    vd = done[-1]
    prev = done[-2]
    pick, when, hist = {}, {}, {}
    for n in list(CURVE) + (["VXN"] if idx == "NDX" else []):
        b = hist[n] = bars(raw[n])
        for d in (vd, prev):
            if d in b:
                pick[n], when[n] = b[d] / 100, d
                break
    pts = sorted((CURVE[n], v) for n, v in pick.items() if n in CURVE)

    def iv(days):
        if days <= pts[0][0]:
            return pts[0][1]
        for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
            if days <= d1:
                return math.sqrt((v0 * v0 * d0 + (v1 * v1 * d1 - v0 * v0 * d0) * (days - d0) / (d1 - d0)) / days)
        return pts[-1][1]
    scale = 1.0
    if idx == "NDX":                                 # NDX vol / S&P vol, both from one session
        both = [d for d in (vd, prev) if d in hist["VXN"] and d in hist["VIX"]]
        if both:
            scale = hist["VXN"][both[0]] / hist["VIX"][both[0]]
        elif "VIX" not in pick and len(set(when.values())) == 1:
            scale = pick["VXN"] / iv(30)
        else:
            raise SystemExit("no VXN and VIX close from one session")
    return (lambda days: scale * iv(days)), vd


def snap_to(k, strikes, tol):
    import bisect
    i = bisect.bisect_left(strikes, k)
    near = min((strikes[j] for j in (i - 1, i) if 0 <= j < len(strikes)), key=lambda s: abs(s - k))
    return near if abs(near - k) <= tol else round(k, 2)


def legs_of(text, key, now, ivf):
    today = now.astimezone(NY).date()
    out, strikes = [], set()
    for root, d, k, coi, poi in occ_rows(text):
        if root not in STANDARD[key] or not 0 <= (d - today).days <= MAX_DTE:
            continue
        e = expiry(root, d)
        if e <= now:
            continue
        strikes.add(k)
        v = ivf((e - now).total_seconds() / 86400)
        t = (e - now).total_seconds() / YEAR
        for cp, oi in (("C", coi), ("P", poi)):
            if oi > 0:
                out.append({"cp": cp, "k": k, "t": t, "oi": oi, "iv": v})
    return out, sorted(strikes)


def independent(raw, idx, etf, now):
    sessions = sorted(bars(raw["^GSPC_1mo"]))
    ivf, vd = vols(raw, idx, sessions, now)
    S = json.loads(raw[YSYM[idx]])["chart"]["result"][0]["meta"]["regularMarketPrice"]
    Se = json.loads(raw[YSYM[etf]])["chart"]["result"][0]["meta"]["regularMarketPrice"]
    ri, istrikes = legs_of(raw["occ_" + idx], idx, now, ivf)
    re_, _ = legs_of(raw["occ_" + etf], etf, now, ivf)
    gaps = sorted(b - a for a, b in zip(istrikes, istrikes[1:]))
    tol = 0.75 * gaps[len(gaps) // 2]
    ratio = S / Se
    legs = [(r["k"], r["cp"], r["oi"], S, r["k"], Q[idx], r["t"], r["iv"]) for r in ri]
    legs += [(snap_to(r["k"] * ratio, istrikes, tol), r["cp"], r["oi"], Se, r["k"], Q[etf], r["t"], r["iv"]) for r in re_]
    lo, hi = {"SPX": (9.5, 10.5), "NDX": (38.0, 45.0)}[idx]
    if not lo <= ratio <= hi:                       # one of the two prices is wrong: the ETF is left out
        legs = legs[:len(ri)]

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
    gross = sum(b["abs"] for b in by.values())
    cw = max((k for k in by if k >= S and by[k]["call"]), key=lambda k: abs(by[k]["call"]))
    pw = max((k for k in by if k <= S and by[k]["put"]), key=lambda k: abs(by[k]["put"]))
    ag = max(by, key=lambda k: by[k]["abs"])
    # zero gamma: same grid (+-5%, 201 points), every leg re-priced with its own underlying moved by the same %
    grid = [(1 - 0.05) + 0.10 * i / 200 for i in range(201)]
    prof = [(S * m, sum(dollar(leg, m) for leg in legs)) for m in grid]
    xs = [p0 + (p1 - p0) * (-v0) / (v1 - v0) for (p0, v0), (p1, v1) in zip(prof, prof[1:]) if v0 * v1 < 0]
    zg = min(xs, key=lambda x: abs(x - S)) if xs else None
    return {"spot": S, "ratio": ratio, "legs": len(legs), "net": net, "gross": gross, "cw": cw, "pw": pw, "ag": ag, "zg": zg,
            "vd": vd}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def fetch_all():
    raw = {f"occ_{s}": get(occ_url(s)) for s in ("NDX", "QQQ", "SPX", "SPY")}
    raw.update({n: get(chart_url("^" + n, "1mo")) for n in list(CURVE) + ["VXN"]})
    raw["^GSPC_1mo"] = get(chart_url("^GSPC", "1mo"))
    raw.update({y: get(chart_url(y, "1d")) for y in YSYM.values()})
    return raw


def opener_for(raw):
    """The engine's opener: the same bytes the independent side read, nothing else."""
    def op(req, timeout=None):
        q = urllib.parse.urlparse(req.full_url)
        args = urllib.parse.parse_qs(q.query)
        if q.netloc == "marketdata.theocc.com":
            return _Resp(raw["occ_" + args["symbol"][0]])
        sym = urllib.parse.unquote(q.path.rsplit("/", 1)[-1])
        return _Resp(raw[sym.lstrip("^")] if args.get("range") == ["1mo"] else raw[sym])
    return op


def main():
    from gexsys import config as cfgmod
    from gexsys.pipeline import run_once
    from gexsys.providers.occ import OccProvider
    raw = fetch_all()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    bad = 0
    for cfg, idx, etf in (("configs/free_es.json", "SPX", "SPY"), ("configs/free_nq.json", "NDX", "QQQ")):
        prov = OccProvider(cache_dir=None, opener=opener_for(raw), clock=lambda: now.timestamp())
        res = run_once(cfgmod.load(cfg), prov)
        s = res["summary"]
        ind = independent(raw, idx, etf, now)
        p = lambda x: (x or {}).get("price") if isinstance(x, dict) else x
        checks = [
            ("vol date", str(prov.vol_date), str(ind["vd"]), 0),
            ("reference price", s["ref_price"], ind["spot"], 1e-9),
            # net is a sum of large opposite-signed terms: judge its error against total gamma, not against net
            # itself (a balanced market with net near zero made tiny model differences look like big misses)
            ("net GEX $/1%", s["net"], ind["net"], 2e-3 * ind["gross"] / max(abs(ind["net"]), 1)),
            ("call wall", p(s["call_wall"]), ind["cw"], 0),
            ("put wall", p(s["put_wall"]), ind["pw"], 0),
            ("abs gamma strike", p(s["abs_gamma"]), ind["ag"], 0),
            ("zero gamma", p(s["zero_gamma"]), ind["zg"], 1e-3),
        ]
        print(f"\n{idx}+{etf}  ratio {ind['ratio']:.4f}  legs {ind['legs']}  vols of {ind['vd']}  asof {now:%H:%M:%S}Z")
        for name, a, b, tol in checks:
            if a is None or b is None or isinstance(a, str):
                ok = a == b
            else:
                ok = abs(a - b) <= tol * max(abs(b), 1) if tol else a == b
            bad += not ok
            print(f"  {'OK  ' if ok else 'DIFF'} {name:18s} engine {a!s:>22}   independent {b!s:>22}")
        # futures mapping: payload factor x index level = mapped level (tick-rounded)
        m = res["mapped"]
        fac = m["mapping"].get("factor") if m else None
        if m and fac and p(s["zero_gamma"]) is not None:          # no crossing (both sides agree on None): nothing to map
            zg_f = p(m["zero_gamma"])
            ok = abs(zg_f - p(s["zero_gamma"]) * fac) <= 0.25
            bad += not ok
            print(f"  {'OK  ' if ok else 'DIFF'} futures mapping    ZG {p(s['zero_gamma']):.2f} x {fac:.6f} = {zg_f}")
    print("\nALL MATCH" if not bad else f"\n{bad} DIFFERENCES")
    return bad


if __name__ == "__main__":
    sys.exit(main())
