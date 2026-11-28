"""Study occ_lse_accuracy v2, part A (studies/occ_lse_accuracy/v2.json): the smile's IV vs the VIX-family curve's,
both against Cboe's own closing ATM IV of 9-19 Nov 2026.

  python tools/stress/occ_lse_accuracy.py pairs            the pairs and their truth (no request)
  python tools/stress/occ_lse_accuracy.py fetch --budget N  LSE flow for pairs not yet on disk (at most N calls)
  python tools/stress/occ_lse_accuracy.py run              the comparison, from disk + Yahoo closes

Local only: LSE prints and per-pair results stay in %LOCALAPPDATA%/gexsys/studies/occ_lse_accuracy/ (LSE licence).
The definition's hash is printed with every result."""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gexsys import marketcal, smile as SM  # noqa: E402
from gexsys.providers.common import dividend_yield, risk_free_rate  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEF = ROOT / "studies/occ_lse_accuracy/v2.json"
UTC = timezone.utc
MARKETS = {"NQ": ("NDX", "NDXP", "^NDX"), "ES": ("SPX", "SPXW", "^GSPC")}     # source, LSE root, Yahoo index
BAND = 0.04


def store() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "gexsys" / "studies" / "occ_lse_accuracy"


def def_hash() -> str:
    return hashlib.sha256(DEF.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# ---------------------------------------------------------------- truth
def session_after_close(t: datetime) -> date | None:
    """Session d when t is after rth_close(d) + 15 min and before the next session's open; else None."""
    c = marketcal.last_close(t)
    d = c.astimezone(marketcal.NY).date()
    nxt = d + timedelta(days=1)
    while not marketcal.is_trading_day(nxt):
        nxt += timedelta(days=1)
    return d if c + timedelta(minutes=15) <= t < marketcal.rth_open_dt(nxt) else None


def next_session(d: date) -> date:
    n = d + timedelta(days=1)
    while not marketcal.is_trading_day(n):
        n += timedelta(days=1)
    return n


def pairs(snap_root: Path) -> tuple[list[dict], list[str]]:
    """The first after-close snapshot per (market, session): the truth (v2 A_iv_level.truth). Also what was dropped."""
    out, dropped = {}, []
    for m in MARKETS:
        for f in sorted((snap_root / f"{m}-CBOE").glob("*/*.json")):
            try:
                s = json.loads(f.read_text(encoding="utf-8"))
                t = datetime.fromisoformat(s["asof"])
            except (OSError, ValueError, KeyError):
                continue
            d = session_after_close(t)
            if d is None or (m, d) in out and out[(m, d)]["_t"] <= t:
                continue
            em = (s.get("extras") or {}).get("expected_move") or {}
            out[(m, d)] = {"_t": t, "market": m, "session": d.isoformat(), "file": f"{f.parent.name}/{f.name}",
                           "expiry": em.get("daily_iv_expiry"), "iv": em.get("daily_iv"), "S": em.get("anchor"),
                           "t0": em.get("variance_from")}
    good = []
    for (m, d), p in sorted(out.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        p.pop("_t")
        if not (p["iv"] and p["S"] and p["t0"]) or p["expiry"] != next_session(d).isoformat():
            dropped.append(f"{m} {d}: truth incomplete or not for the next session ({p['expiry']})")
            continue
        good.append(p)
    return good, dropped


# ---------------------------------------------------------------- LSE flow -> one row per contract
def flow_params(p: dict) -> dict:
    d = date.fromisoformat(p["session"])
    c = marketcal.rth_close_dt(d).astimezone(UTC)
    s = float(p["S"])
    return {"underlying": MARKETS[p["market"]][1], "expiry": p["expiry"], "strike_min": math.floor(s * (1 - BAND)),
            "strike_max": math.ceil(s * (1 + BAND)), "from": (c - SM.LAST_WINDOW).strftime("%Y-%m-%d %H:%M:%S"),
            "to": c.strftime("%Y-%m-%d %H:%M:%S"), "order": "desc", "limit": 5000}


def collapse(prints: list[dict], price_at=None) -> tuple[list[dict], int]:
    """Flow prints -> chain-shaped rows (v2 smile_same.rows): the contract's last print, its IV and underlying price
    (else price_at(ts), the index's 1-minute close), volume = the window's summed sizes. Also prints dropped."""
    by, vol, dropped = {}, {}, 0
    for pr in prints:
        ts = SM.stamp(pr.get("ts"))
        if ts is None or SM.kind(pr) is None:
            dropped += 1
            continue
        key = (float(pr.get("strike") or 0), SM.kind(pr))
        vol[key] = vol.get(key, 0) + float(pr.get("size") or 0)
        if key not in by or SM.stamp(by[key]["ts"]) < ts:
            by[key] = pr
    rows = []
    for key, pr in by.items():
        s = pr.get("underlying_price")
        if s is None and price_at:
            s = price_at(SM.stamp(pr["ts"]))
        if s is None:
            dropped += 1
            continue
        rows.append({"strike": key[0], "contract_type": pr.get("contract_type"), "expiry": pr.get("expiry"),
                     "iv": pr.get("iv"), "greeks_underlying_price": s, "volume_today": vol[key],
                     "last_trade_at": pr.get("ts")})
    return rows, dropped


def fetch(budget: int) -> None:
    from gexsys.providers import lse
    got, _ = pairs(Path(os.environ["LOCALAPPDATA"]) / "gexsys" / "snapshots")
    c = lse.LseClient(budget=budget)
    (store() / "flow").mkdir(parents=True, exist_ok=True)
    for p in got:
        f = store() / "flow" / f"{p['market']}_{p['session']}.json"
        if f.exists():
            continue
        try:
            d = c.get("/v3/options/flow", **flow_params(p))
        except Exception as e:                      # the client's errors carry the status and code only, never the key
            print(f"{p['market']} {p['session']}: {e}")
            if "budget" in str(e):
                break
            continue
        f.write_text(json.dumps(d), encoding="utf-8")
        print(f"{p['market']} {p['session']}: {len(d.get('rows') or [])} prints")
    print(f"LSE calls this run: {c.limiter.used}")


# ---------------------------------------------------------------- the comparison
def yahoo_minutes(sym: str, d: date) -> dict:
    """{minute (UTC, aware): close} of the index on session d (Yahoo chart, interval 1m), for the price fallback."""
    from gexsys.providers.occ import OccProvider
    o, c = marketcal.rth_open_dt(d), marketcal.rth_close_dt(d)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval=1m"
           f"&period1={int(o.timestamp())}&period2={int(c.timestamp()) + 60}")
    j = json.loads(OccProvider(cache_dir=None)._get(url, f"y1m_{sym}_{d}"))["chart"]["result"][0]
    q = j["indicators"]["quote"][0]["close"]
    return {datetime.fromtimestamp(t, UTC): v for t, v in zip(j["timestamp"], q) if v}


def bootstrap(ds: list[float], seed: int, n: int = 10000) -> tuple[float, float]:
    import numpy as np
    rng = np.random.default_rng(seed)
    a = np.array(ds)
    med = np.median(a[rng.integers(0, len(a), size=(n, len(a)))], axis=1)
    return float(np.percentile(med, 2.5)), float(np.percentile(med, 97.5))


def verdict(ds: list[float], ci: tuple[float, float]) -> str:
    """The v1 pass bar (approved 2026-11-28), on the pairs with both arms. ds in vol points."""
    if len(ds) < 8:
        return "can't tell (n too small)"
    med = sorted(ds)[len(ds) // 2] if len(ds) % 2 else (sorted(ds)[len(ds) // 2 - 1] + sorted(ds)[len(ds) // 2]) / 2
    closer = sum(1 for x in ds if x < 0) / len(ds)
    if med <= -0.5 and ci[1] < 0 and closer >= 0.70:
        return "better"
    return "no worse (not better)" if med <= 0.25 else "no better"


def run() -> dict:
    from gexsys.providers.occ import CURVE, VOL_SYM, VOL_URL, OccProvider, daily_closes
    spec = json.loads(DEF.read_text(encoding="utf-8"))
    got, dropped = pairs(Path(os.environ["LOCALAPPDATA"]) / "gexsys" / "snapshots")
    prov = OccProvider(cache_dir=None)
    hist = {n: daily_closes(prov._get(VOL_URL.format(sym=urllib.parse.quote(VOL_SYM[n])), f"yvol_{n}"))
            for n in [c for c, _ in CURVE] + ["VXN"]}
    rows_out = []
    for p in got:
        m, d = p["market"], date.fromisoformat(p["session"])
        src, root, ysym = MARKETS[m]
        t0, s0 = datetime.fromisoformat(p["t0"]), float(p["S"])
        exp = marketcal.option_expiry_time(date.fromisoformat(p["expiry"]), root)
        T = (exp - t0).total_seconds() / SM.YEAR_S
        curve = prov._curve_on(src, hist, d)
        rec = {k: p[k] for k in ("market", "session", "expiry", "file")}
        rec.update(cboe=p["iv"], T_days=T * 365, vix=curve(T) if curve else None)
        f = store() / "flow" / f"{m}_{p['session']}.json"
        if not f.exists():
            rec["smile_why"] = "no LSE flow on disk"
        else:
            fl = json.loads(f.read_text(encoding="utf-8"))
            prints = fl.get("rows") or []
            rec["prints"], rec["truncated"] = len(prints), len(prints) >= 5000
            mins = {}

            def price_at(ts, mins=mins):
                if not mins:
                    mins.update(yahoo_minutes(ysym, d) or {0: None})
                return mins.get(ts.replace(second=0, microsecond=0))
            rows, rec["prints_dropped"] = collapse(prints, price_at)
            r, q = risk_free_rate(), dividend_yield(src)
            pts = SM.points(rows, exp, marketcal.rth_open_dt(d), marketcal.rth_close_dt(d), r, q)
            sig = curve(T) if curve else None
            fit, why = SM.fit(exp, pts, sig) if sig else (None, "no VIX-family curve")
            rec["contracts"], rec["points"] = len(rows), len(pts)
            if fit:
                rec["smile"] = SM.Surface({exp: fit}, r, q).iv(exp, s0, s0, t0)
                rec["fit"] = fit.info()
            else:
                rec["smile_why"] = why
        for a in ("vix", "smile"):
            if rec.get(a) is not None:
                rec[f"err_{a}"] = (rec[a] - rec["cboe"]) * 100
        rows_out.append(rec)
    both = [x for x in rows_out if "err_vix" in x and "err_smile" in x]
    ds = [abs(x["err_smile"]) - abs(x["err_vix"]) for x in both]
    ci = bootstrap(ds, spec["seed"]) if len(ds) >= 2 else (float("nan"), float("nan"))
    res = {"definition": str(DEF.relative_to(ROOT)), "sha256": def_hash(), "computed": datetime.now(UTC).isoformat(),
           "pairs": rows_out, "dropped": dropped, "n_both": len(both), "D": ds, "D_ci95": ci,
           "verdict": verdict(ds, ci) if ds else "can't tell (n too small)"}
    store().mkdir(parents=True, exist_ok=True)
    (store() / "result_v2.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return res


def summary(res: dict) -> str:
    med = lambda v: sorted(v)[len(v) // 2] if len(v) % 2 else (sorted(v)[len(v) // 2 - 1] + sorted(v)[len(v) // 2]) / 2
    out = [f"occ_lse_accuracy v2 part A  sha256 {res['sha256']}  computed {res['computed'][:16]} UTC", ""]
    out.append("market session    expiry      Cboe   VIX    smile  errVIX errSmile  D     note")
    for x in res["pairs"]:
        out.append(f"{x['market']:6s} {x['session']} {x['expiry']} {x['cboe']*100:6.2f} "
                   + (f"{x['vix']*100:6.2f} " if x.get("vix") else "   -   ")
                   + (f"{x['smile']*100:6.2f} " if x.get("smile") else "   -   ")
                   + (f"{x['err_vix']:+6.2f} " if "err_vix" in x else "   -   ")
                   + (f"{x['err_smile']:+6.2f}  " if "err_smile" in x else "   -    ")
                   + (f"{abs(x['err_smile']) - abs(x['err_vix']):+5.2f} " if "err_smile" in x and "err_vix" in x else "  -   ")
                   + (x.get("smile_why") or ("truncated" if x.get("truncated") else "")))
    ds = res["D"]
    out.append("")
    for a in ("vix", "smile"):
        e = [abs(x[f"err_{a}"]) for x in res["pairs"] if f"err_{a}" in x]
        b = [x[f"err_{a}"] for x in res["pairs"] if f"err_{a}" in x]
        if e:
            out.append(f"{a:5s}: n {len(e)}, median |error| {med(e):.2f} vol pts, mean error {sum(b)/len(b):+.2f}, worst {max(e):.2f}")
    if ds:
        out.append(f"D (|smile err| - |VIX err|): n {len(ds)}, median {med(ds):+.2f} vol pts, 95% CI "
                   f"[{res['D_ci95'][0]:+.2f}, {res['D_ci95'][1]:+.2f}], smile closer in {sum(1 for x in ds if x < 0)} of {len(ds)}")
    out.append(f"dropped: {len(res['dropped'])}" + (f" ({'; '.join(res['dropped'])})" if res["dropped"] else ""))
    out.append(f"VERDICT: {res['verdict']}")
    return "\n".join(out)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "pairs":
        got, dropped = pairs(Path(os.environ["LOCALAPPDATA"]) / "gexsys" / "snapshots")
        for p in got:
            print(p["market"], p["session"], p["expiry"], p["iv"], p["S"], p["t0"], p["file"], flow_params(p))
        print("dropped:", dropped)
    elif cmd == "fetch":
        fetch(int(sys.argv[sys.argv.index("--budget") + 1]))
    else:
        print(summary(run()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
