"""Stress test B1: the GEX engine against an independent re-implementation, on live Cboe chains replayed at
10 different moments (20 snapshots: SPX+SPY for ES, NDX+QQQ for NQ).

  python tools/stress/gex_recompute.py

The independent side is tools/verify_math.py (its own OCC parsing, expiry times, Black-Scholes gamma, IV
solver, ETF handling, strike buckets, walls and zero-gamma search) plus, here, its own ranked levels, first-
expiry levels and max pain. Shared: only the raw Cboe JSON and the inputs (rate, dividend yields), and the
definitions (written in each function's comment). Raw chains were never saved, so history cannot be replayed:
instead the SAME live chain is re-timed (its timestamp moved) to a weekend, a holiday, an early close, an
AM-settled expiry and more, which exercises every date path on both sides.
Tolerances (fixed before running): dollar figures (net, gross, every strike's net) 0.01% relative (strikes
under 1e-6 of gross: absolute); walls, abs gamma, max pain, ranked strikes exact; zero gamma 0.5 index points;
ranked shares 1e-4.
"""
from __future__ import annotations

import copy
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import verify_math as vm  # noqa: E402

_SOLVE = vm.solve_iv            # the independent bisection, before the refusal rule is layered on

TOL_REL, TOL_ZG, TOL_SHARE = 1e-4, 0.5, 1e-4
SCENARIOS = [                      # ET wall-clock moments the chain is re-timed to (all in Nov-Dec 2026)
    ("as fetched", None),
    ("Tuesday open", "2026-11-10 09:45"),
    ("Saturday", "2026-11-14 12:00"),
    ("Sunday Globex open", "2026-11-15 19:00"),
    ("monthly expiry, before the AM settlement", "2026-11-20 09:00"),
    ("monthly expiry, after the AM settlement", "2026-11-20 10:00"),
    ("Thanksgiving (holiday)", "2026-11-26 10:00"),
    ("day after Thanksgiving, before the 13:00 close", "2026-11-27 12:30"),
    ("day after Thanksgiving, after the close", "2026-11-27 13:30"),
    ("Christmas Eve, last minutes", "2026-12-24 12:58"),
]


def _iv_refusing(target, s, k, t, q, call):
    """Independent IV with the same RULE as the engine: refuse a vol that half a cent cannot pin to 2 points."""
    v = _SOLVE(target, s, k, t, q, call)
    if v is None:
        return None
    tt = max(t, 1 / (365 * 24 * 60))
    d1 = (math.log(s / k) + (vm.R - q + v * v / 2) * tt) / (v * math.sqrt(tt))
    vega = s * math.exp(-q * tt) * math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi) * math.sqrt(tt)
    return None if vega <= 0 or 0.005 / vega > 0.02 else v


def retime(raw: dict, et: str | None) -> dict:
    if not et:
        return raw
    out = copy.deepcopy(raw)
    t = datetime.strptime(et, "%Y-%m-%d %H:%M").replace(tzinfo=vm.NY).astimezone(timezone.utc)
    out["timestamp"] = t.strftime("%Y-%m-%d %H:%M:%S")
    return out


def independent_extra(raw_i, raw_e, idx, etf, asof, band):
    """By-strike net and abs, first-expiry zero gamma and walls, ranked levels and max pain, independently."""
    S, Se = float(raw_i["data"]["current_price"]), float(raw_e["data"]["current_price"])
    ri, istrikes, ismile = vm.rows_of(raw_i, idx, asof, vm.Q[idx])
    re_, _, esmile = vm.rows_of(raw_e, etf, asof, vm.Q[etf])
    gaps = sorted(b - a for a, b in zip(istrikes, istrikes[1:]))
    tol, ratio = 0.75 * gaps[len(gaps) // 2], S / Se
    smile: dict = {}
    for e, k, v in ismile:
        smile.setdefault(e, []).append((k, v))
    for e, k, v in esmile:
        smile.setdefault(e, []).append((k * ratio, v))           # the exact converted strike: borrowing picks the truly nearest

    def fill(r, k_idx):
        if r["iv"] is None and smile.get(r["e"]):
            r["iv"] = min(smile[r["e"]], key=lambda kv: abs(kv[0] - k_idx))[1]
        return r["iv"]
    legs = []      # (index strike bucket, cp, oi, own S, own K, q, t, iv, expiry, exact index-terms strike, oi in index contracts)
    for r in ri:
        if fill(r, r["k"]):
            legs.append((r["k"], r["cp"], r["oi"], S, r["k"], vm.Q[idx], r["t"], r["iv"], r["e"], r["k"], r["oi"]))
    for r in re_:
        k_idx = vm.snap_to(r["k"] * ratio, istrikes, tol)
        if fill(r, r["k"] * ratio):
            legs.append((k_idx, r["cp"], r["oi"], Se, r["k"], vm.Q[etf], r["t"], r["iv"], r["e"], r["k"] * ratio, r["oi"] / ratio))

    def dollar(leg, move=1.0):
        _, cp, oi, s, k, q, t, iv = leg[:8]
        s = s * move
        return (1 if cp == "C" else -1) * oi * vm.gamma(s, k, t, q, iv) * 100 * s * s * 0.01

    def buckets(ls):
        by = {}
        for leg in ls:
            v = dollar(leg)
            b = by.setdefault(leg[0], {"net": 0.0, "abs": 0.0, "call": 0.0, "put": 0.0})
            b["net"] += v
            b["abs"] += abs(v)
            b["call" if leg[1] == "C" else "put"] += v
        return by

    def zero_gamma(ls):
        grid = [(1 - 0.05) + 0.10 * i / 200 for i in range(201)]
        prof = [(S * m, sum(dollar(leg, m) for leg in ls)) for m in grid]
        xs = [p0 + (p1 - p0) * (-v0) / (v1 - v0) for (p0, v0), (p1, v1) in zip(prof, prof[1:]) if v0 * v1 < 0]
        return min(xs, key=lambda x: abs(x - S)) if xs else None

    def walls(by):
        cw = max((k for k in by if k >= S and by[k]["call"]), key=lambda k: abs(by[k]["call"]), default=None)
        pw = max((k for k in by if k <= S and by[k]["put"]), key=lambda k: abs(by[k]["put"]), default=None)
        return cw, pw

    def ranked(by, window, n):
        """Definition: within window x spot; call = most positive net, put = most negative net, abs = most total;
        strongest first, and a strike within one band of a level already taken adds to it instead."""
        near = {k: v for k, v in by.items() if abs(k - S) <= window * S}
        tot_net, tot_abs = sum(abs(v["net"]) for v in by.values()), sum(v["abs"] for v in by.values())
        def pick(vals):
            kept = []
            for k, v in sorted(vals, key=lambda kv: -kv[1]):
                home = next((x for x in kept if abs(x[0] - k) < band), None)
                if home:
                    home[1] += v
                else:
                    kept.append([k, v])
            return sorted(kept, key=lambda x: -x[1])
        pos = pick([(k, v["net"]) for k, v in near.items() if v["net"] > 0])[:n[0]]
        neg = pick([(k, -v["net"]) for k, v in near.items() if v["net"] < 0])[:n[1]]
        ab = pick([(k, v["abs"]) for k, v in near.items() if v["abs"] > 0])[:n[2]]
        return {"call": [(k, v / tot_net) for k, v in pos], "put": [(k, v / tot_net) for k, v in neg],
                "abs": [(k, v / tot_abs) for k, v in ab]}

    def max_pain(ls_raw):
        """Definition: the candidate strike (index strikes, ETF strikes at their index bucket) minimising the
        intrinsic payout to holders, each contract at its exact strike, OI in index contracts; ties -> lower."""
        cands = sorted({leg[0] for leg in ls_raw if leg[10]})
        best, best_pay = None, math.inf
        for s in cands:
            pay = sum(leg[10] * (max(0.0, s - leg[9]) if leg[1] == "C" else max(0.0, leg[9] - s)) for leg in ls_raw if leg[10])
            if pay < best_pay - 1e-9:
                best, best_pay = s, pay
        return best

    by = buckets(legs)
    # an expiry is a DATE: SPX / NDX list an AM-settled monthly and PM weeklies on the same day, and both expire then
    exps = sorted({leg[8].date() for leg in legs})
    first = [leg for leg in legs if exps and leg[8].date() == exps[0]]
    by0 = buckets(first)
    # max pain uses every contract with OI in the expiry (IV not needed): rebuild without the IV filter
    all_rows = [(r["k"], r["cp"], r["oi"], S, r["k"], 0, r["t"], 0, r["e"], r["k"], r["oi"]) for r in ri] + \
               [(vm.snap_to(r["k"] * ratio, istrikes, tol), r["cp"], r["oi"], Se, r["k"], 0, r["t"], 0, r["e"], r["k"] * ratio, r["oi"] / ratio) for r in re_]
    mp = {d.isoformat(): max_pain([x for x in all_rows if x[8].date() == d]) for d in sorted({x[8].date() for x in all_rows})}
    return {"by": by, "zg0": zero_gamma(first), "walls0": walls(by0), "ranked": ranked(by, 0.06, (5, 5, 3)),
            "ranked0": ranked(by0, 0.03, (7, 7, 3)), "max_pain": mp, "exp0": exps[0].isoformat() if exps else None}


def run_engine(cfg_path, raw, asof=None):
    """The live pipeline's steps (normalize, session-aware spot age, compute, summarize, extras) at an explicit
    moment: the engine dates a chain by its fetch time, so a re-timed chain needs the time passed in."""
    import dataclasses
    from gexsys import config as cfgmod, engine as eng
    from gexsys.extras import compute_extras
    from gexsys.levels import summarize
    from gexsys.marketcal import session_state
    from gexsys.normalize import normalize
    from gexsys.providers.cboe import CboeProvider
    cfg = cfgmod.load(cfg_path)
    prov = CboeProvider(http=lambda url, headers, limiter=None: raw[url.rsplit("/", 1)[1][:-5]], include_etf=True)
    # the provider dates its window from the chain's own timestamp, which retime() moves: production settings.
    # Its clock is the scenario's (a re-timed chain is not "from the future" there).
    from datetime import datetime as _dt
    from gexsys.providers import cboe as _cboe
    stamp = max(_dt.strptime(r["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) for r in raw.values())

    class _Clock(_dt):
        @classmethod
        def now(cls, tz=None):
            return stamp.astimezone(tz) if tz else stamp.replace(tzinfo=None)
    real, _cboe.datetime = _cboe.datetime, _Clock
    try:
        snap = normalize(prov.fetch_snapshot(cfg.source, cfg.engine.max_dte, cfg.engine.include_0dte), check_occ=True)
    finally:
        _cboe.datetime = real
    asof = asof or snap.fetched_at
    ecfg = cfg.engine if session_state(asof) == "RTH" else dataclasses.replace(cfg.engine, max_spot_age_s=400 * 86400)
    res = eng.compute(snap, ecfg, asof=asof)
    summary = summarize(res, cfg.levels)
    if res.status != "UNAVAILABLE":
        summary["extras"] = compute_extras(snap, ecfg, res)
    return {"summary": summary, "by_strike": [{"strike": k, "net": v["net"]} for k, v in res.by_strike.items()]}


def main() -> int:
    orig_rows_of = vm.rows_of

    def rows_of(raw, key, asof, q_solve=None):          # same rows, but the IV rule refuses undetermined vols
        saved = vm.solve_iv
        vm.solve_iv = _iv_refusing
        try:
            return orig_rows_of(raw, key, asof, q_solve)
        finally:
            vm.solve_iv = saved
    raws = {sym: vm.fetch(sym) for sym in ("_SPX", "SPY", "_NDX", "QQQ")}
    fails, rows = 0, []
    p = lambda x: (x or {}).get("price") if isinstance(x, dict) else x
    for label, et in SCENARIOS:
        for cfg, idx, etf, si, se, band in (("configs/free_es_cboe.json", "SPX", "SPY", "_SPX", "SPY", 10.0),
                                            ("configs/free_nq_cboe.json", "NDX", "QQQ", "_NDX", "QQQ", 40.0)):
            raw = {si: retime(raws[si], et), se: retime(raws[se], et)}
            when = datetime.strptime(et, "%Y-%m-%d %H:%M").replace(tzinfo=vm.NY) if et else None
            res = run_engine(cfg, raw, when)
            s = res["summary"]
            if s.get("status") == "UNAVAILABLE":
                rows.append((label, idx, "engine UNAVAILABLE", True))
                continue
            asof = datetime.fromisoformat(s["asof"])
            vm.rows_of = rows_of
            try:
                ind = vm.independent(raw[si], raw[se], idx, etf, asof)
                ext = independent_extra(raw[si], raw[se], idx, etf, asof, band)
            finally:
                vm.rows_of = orig_rows_of
            bad = []
            rel = lambda a, b: abs(a - b) / max(abs(b), 1e-300)
            if rel(s["net"], ind["net"]) > TOL_REL:
                bad.append(f"net {s['net']:.6g} vs {ind['net']:.6g}")
            gross = ind["gross"]
            if rel(s["gross"], gross) > TOL_REL:
                bad.append(f"gross {s['gross']:.6g} vs {gross:.6g}")
            eb = {round(x["strike"], 2): x["net"] for x in res["by_strike"]}
            worst_k = max(((k, abs(eb.get(round(k, 2), 0.0) - v["net"]) / max(abs(v["net"]), 1e-6 * gross)) for k, v in ext["by"].items()),
                          key=lambda kv: kv[1], default=(None, 0.0))
            missing = sorted(set(eb) ^ {round(k, 2) for k in ext["by"]})
            if worst_k[1] > TOL_REL:
                bad.append(f"strike {worst_k[0]} net off by {worst_k[1]:.2e}")
            if missing:
                bad.append(f"strikes on one side only: {missing[:5]}")
            for name, a, b in (("call wall", p(s["call_wall"]), ind["cw"]), ("put wall", p(s["put_wall"]), ind["pw"]),
                               ("abs gamma", p(s["abs_gamma"]), ind["ag"])):
                if a != b:
                    bad.append(f"{name} {a} vs {b}")
            zg_e, zg_i = p(s["zero_gamma"]), ind["zg"]
            if (zg_e is None) != (zg_i is None) or (zg_e is not None and abs(zg_e - zg_i) > TOL_ZG):
                bad.append(f"zero gamma {zg_e} vs {zg_i}")
            for side in ("call", "put", "abs"):
                a = [(x["price"], x["share"]) for x in s["ranked"][side]]
                b = ext["ranked"][side]
                if [k for k, _ in a] != [k for k, _ in b] or any(abs(x[1] - y[1]) > TOL_SHARE for x, y in zip(a, b)):
                    bad.append(f"ranked {side} {[k for k, _ in a]} vs {[k for k, _ in b]}")
            near = (s.get("extras") or {}).get("nearest") or {}
            if near.get("expiration") != ext["exp0"]:
                bad.append(f"first expiry {near.get('expiration')} vs {ext['exp0']}")
            else:
                z0 = p(near.get("zero_gamma"))
                if (z0 is None) != (ext["zg0"] is None) or (z0 is not None and abs(z0 - ext["zg0"]) > TOL_ZG):
                    bad.append(f"first-expiry zero gamma {z0} vs {ext['zg0']}")
                if (p(near.get("call_wall")), p(near.get("put_wall"))) != ext["walls0"]:
                    bad.append(f"first-expiry walls {(p(near.get('call_wall')), p(near.get('put_wall')))} vs {ext['walls0']}")
                r0 = near.get("ranked") or {}
                for side in ("call", "put", "abs"):
                    if [x["price"] for x in r0.get(side, [])] != [k for k, _ in ext["ranked0"][side]]:
                        bad.append(f"first-expiry ranked {side} differ")
            mp_e = {m["expiration"]: m["price"] for m in (s.get("extras") or {}).get("max_pain", [])}
            mp_diff = {e: (mp_e.get(e), v) for e, v in ext["max_pain"].items() if e in mp_e and mp_e[e] != v}
            if mp_diff:
                bad.append(f"max pain differs: {dict(list(mp_diff.items())[:3])}")
            fails += bool(bad)
            rows.append((label, idx, "; ".join(bad) if bad else f"OK (net {s['net']:.4g}, {len(eb)} strikes, ZG {zg_e})", not bad))
    print(f"{'scenario':48s} {'mkt':4s} result")
    for label, idx, msg, ok in rows:
        print(f"{label[:48]:48s} {idx:4s} {'PASS' if ok else 'FAIL'}  {msg[:160]}")
    print(f"\n{len(rows)} snapshots, {fails} failing")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
