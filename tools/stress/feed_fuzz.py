"""Stress test E1: corrupt every data source and check that nothing silently wrong comes out.

  python tools/stress/feed_fuzz.py

Each source's real response is fetched once, then replayed with one corruption at a time:
  levels (Cboe chains -> the whole pipeline, run_once): truncated JSON, NaN / Infinity in numbers, negative OI,
      duplicate contracts, the timestamp 2 days old / 5 hours ahead / in ET instead of UTC, the other market's chain
      (wrong symbol), price 0, strikes x10, empty options. Verdict per case: REFUSED (error or UNAVAILABLE),
      WARNED (DEGRADED or a new warning, levels may differ), UNAFFECTED (zero gamma and walls within 0.1 daily
      expected move of the clean run, no warning needed), or SILENTLY WRONG (they moved, nothing said so).
  basis (Yahoo NQ=F / ^NDX 1-minute bars, futures prices on the website): truncated, NaN closes, wrong symbol,
      stale, timestamps shifted an hour. REFUSED = the carry model stands in (labelled).
  news feeds (ForexFactory, CFTC, the posts feed, quotes, market drivers): truncated, empty, null, an HTML error
      page, NaN numbers, a wrong top-level type. Each must keep its last good copy (or show nothing) without
      raising, and never show NaN.
Tolerance (fixed before running): zero SILENTLY WRONG cases, zero crashes, zero NaN shown.
"""
from __future__ import annotations

import copy
import io
import json
import re
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import verify_math as vm  # noqa: E402
from gexsys import basis, config as cfgmod  # noqa: E402
from gexsys.pipeline import run_once  # noqa: E402
from gexsys.providers.cboe import CboeProvider  # noqa: E402

TS_FMT = "%Y-%m-%d %H:%M:%S"


# ------------------------------------------------------------------ levels
def chain_cases(raw_i: dict, raw_e: dict, other: dict) -> list[tuple[str, object, object]]:
    def ts_shift(r, h):
        r = copy.deepcopy(r)
        r["timestamp"] = (datetime.strptime(r["timestamp"], TS_FMT) + timedelta(hours=h)).strftime(TS_FMT)
        return r

    def each(r, f, every=7):
        r = copy.deepcopy(r)
        for i, o in enumerate(r["data"]["options"]):
            if i % every == 0:
                f(o)
        return r

    text = json.dumps(raw_i)
    return [
        ("truncated JSON", text[: len(text) // 2], raw_e),
        ("NaN open interest (1 in 7)", each(raw_i, lambda o: o.__setitem__("open_interest", float("nan"))), raw_e),
        ("'NaN' strings in IV and gamma", each(raw_i, lambda o: (o.__setitem__("iv", "NaN"), o.__setitem__("gamma", "NaN"))), raw_e),
        ("Infinity IV (1 in 7)", each(raw_i, lambda o: o.__setitem__("iv", float("inf"))), raw_e),
        ("negative open interest (1 in 7)", each(raw_i, lambda o: o.__setitem__("open_interest", -abs(o.get("open_interest") or 1) * 50)), raw_e),
        ("every contract twice", {**raw_i, "data": {**raw_i["data"], "options": raw_i["data"]["options"] * 2}}, raw_e),
        ("timestamp 2 days old", ts_shift(raw_i, -48), ts_shift(raw_e, -48)),
        ("timestamp 5 hours ahead", ts_shift(raw_i, 5), ts_shift(raw_e, 5)),
        ("timestamp in ET, not UTC", ts_shift(raw_i, -5), ts_shift(raw_e, -5)),
        ("the other market's chain (wrong symbol)", other, raw_e),
        ("current price 0", {**raw_i, "data": {**raw_i["data"], "current_price": 0}}, raw_e),
        ("current price NaN", {**raw_i, "data": {**raw_i["data"], "current_price": "NaN"}}, raw_e),
        ("strikes x10 (current price unchanged)", {**raw_i, "data": {**raw_i["data"], "current_price": raw_i["data"]["current_price"] / 10}}, raw_e),
        ("empty options list", {**raw_i, "data": {**raw_i["data"], "options": []}}, raw_e),
        ("ETF chain truncated", raw_i, json.dumps(raw_e)[:500]),
        ("ETF price 0", raw_i, {**raw_e, "data": {**raw_e["data"], "current_price": 0}}),
    ]


def run_levels(cfg, si, se, ri, re_):
    def http(url, headers, limiter=None):
        body = ri if url.rsplit("/", 1)[1][:-5] == si else re_
        return json.loads(body) if isinstance(body, str) else body
    r = run_once(cfg, CboeProvider(http=http, include_etf=True))
    return r


def levels_of(r):
    s = r["summary"]
    p = lambda k: (s.get(k) or {}).get("price") if isinstance(s.get(k), dict) else s.get(k)
    em = ((s.get("extras") or {}).get("expected_move") or {}).get("daily_points")
    kinds = {re.sub(r"[\d.,]+", "#", w) for w in s.get("warnings") or []}      # a warning's kind, not its count
    return {k: p(k) for k in ("zero_gamma", "call_wall", "put_wall")}, em, s.get("status"), kinds


def fuzz_levels() -> list[tuple[str, str, str]]:
    out = []
    raw = {k: vm.fetch(k) for k in ("_NDX", "QQQ", "_SPX", "SPY")}
    for cfgp, si, se, oi in (("configs/free_nq_cboe.json", "_NDX", "QQQ", "_SPX"), ("configs/free_es_cboe.json", "_SPX", "SPY", "_NDX")):
        cfg = cfgmod.load(cfgp)
        clean = run_levels(cfg, si, se, raw[si], raw[se])
        lv0, em, st0, w0 = levels_of(clean)
        for name, ri, re_ in chain_cases(raw[si], raw[se], raw[oi]):
            try:
                r = run_levels(cfg, si, se, ri, re_)
            except Exception as e:
                out.append((f"{cfg.market} levels", name, f"REFUSED ({type(e).__name__}: {str(e)[:60]})"))
                continue
            lv, _, st, w = levels_of(r)
            if st == "UNAVAILABLE":
                out.append((f"{cfg.market} levels", name, "REFUSED (UNAVAILABLE: " + (r["summary"]["warnings"] or ["?"])[-1][:60] + ")"))
                continue
            moved = [k for k in lv if (lv[k] is None) != (lv0[k] is None) or (lv[k] is not None and abs(lv[k] - lv0[k]) > 0.1 * em)]
            new_w = w - w0
            if st == "DEGRADED" or new_w:
                out.append((f"{cfg.market} levels", name, f"WARNED ({st}; {'; '.join(sorted(new_w))[:90]})" + (f" moved {moved}" if moved else "")))
            elif moved:
                out.append((f"{cfg.market} levels", name, f"SILENTLY WRONG: {', '.join(f'{k} {lv0[k]} -> {lv[k]}' for k in moved)}"))
            else:
                out.append((f"{cfg.market} levels", name, "UNAFFECTED"))
    return out


# ------------------------------------------------------------------ basis
def fuzz_basis() -> list[tuple[str, str, str]]:
    out = []
    now = datetime.now(timezone.utc)
    good = {s: _yahoo_raw(s, now) for s in ("NQ=F", "^NDX", "ES=F")}
    real = basis._yahoo_1m

    def replay(corrupt):
        def fake(sym, asof):
            body = corrupt(sym, good[sym])
            res = json.loads(body)["chart"]["result"][0]
            q = res["indicators"]["quote"][0]["close"]
            return {t - t % 60: c for t, c in zip(res.get("timestamp") or [], q) if c}
        return fake

    def nan_closes(sym, b):
        d = json.loads(b)
        q = d["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        for i in range(0, len(q), 3):
            q[i] = float("nan")
        return json.dumps(d)

    def shift(sym, b):
        if sym != "NQ=F":
            return b
        d = json.loads(b)
        d["chart"]["result"][0]["timestamp"] = [t + 3600 for t in d["chart"]["result"][0]["timestamp"]]
        return json.dumps(d)

    clean = basis.observed_basis("NDX", now)
    cases = [("truncated JSON", lambda s, b: b[: len(b) // 2]),
             ("NaN closes (1 in 3)", nan_closes),
             ("wrong symbol (ES=F served for NQ=F)", lambda s, b: good["ES=F"] if s == "NQ=F" else b),
             ("stale (bars end 6 days ago)", None),
             ("futures timestamps shifted an hour", shift)]
    try:
        for name, corrupt in cases:
            if corrupt is None:
                basis._yahoo_1m = replay(lambda s, b: b)
                got = basis.observed_basis("NDX", now + timedelta(days=6))
            else:
                basis._yahoo_1m = replay(corrupt)
                try:
                    got = basis.observed_basis("NDX", now)
                except Exception as e:
                    out.append(("NQ basis", name, f"CRASH ({type(e).__name__})"))
                    continue
            if got is None:
                out.append(("NQ basis", name, "REFUSED (carry model stands in, labelled)"))
            elif clean and abs(got[0] - clean[0]) * 27000 <= 0.5:
                out.append(("NQ basis", name, f"UNAFFECTED (ratio {got[0]:.6f})"))
            else:
                out.append(("NQ basis", name, f"SILENTLY WRONG: ratio {got[0]:.6f} vs {clean[0]:.6f} "
                                              f"({(got[0] - clean[0]) * 27000:+.1f} NQ points)"))
    finally:
        basis._yahoo_1m = real
    return out


def _yahoo_raw(sym: str, asof: datetime) -> str:
    p2 = int(asof.timestamp())
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + sym.replace("^", "%5E").replace("=", "%3D")
           + f"?interval=1m&period1={p2 - 5 * 86400}&period2={p2}")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
        return r.read().decode("utf-8")


# ------------------------------------------------------------------ news feeds
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def recording_opener(store: dict):
    def opener(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if url not in store:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                store[url] = r.read()
        return _Resp(store[url])
    return opener


def corruptions():
    def nan_numbers(b):
        return re.sub(rb'(":\s*)-?\d+\.\d+', rb'\1NaN', b, count=40)

    def wrap(b):
        return b'{"unexpected": ' + b + b'}' if b.strip()[:1] in (b"[", b"{") else b
    return [("truncated", lambda b: b[: len(b) // 2]), ("empty body", lambda b: b""), ("null", lambda b: b"null"),
            ("HTML error page", lambda b: b"<html><body>429 Too Many Requests</body></html>"),
            ("NaN numbers", nan_numbers), ("wrong top-level type", wrap)]


def fuzz_feeds() -> list[tuple[str, str, str]]:
    from feeds import drivers, forexfactory, positioning, quotes, truthsocial
    out = []
    tmp = Path(tempfile.mkdtemp())
    makers = {
        "ForexFactory calendar": (lambda op, clk: forexfactory.Calendar(opener=op, clock=clk, cache_path=tmp / "ff.json"), "get"),
        "posts feed": (lambda op, clk: truthsocial.Posts(opener=op, clock=clk, cache_path=tmp / "posts.json"), "get"),
        "quotes": (lambda op, clk: quotes.Quotes(opener=op, clock=clk), "get"),
        "market drivers": (lambda op, clk: drivers.Drivers(opener=op, clock=clk, cache_path=tmp / "drv.json"), "get"),
    }
    for name, (make, meth) in makers.items():
        store: dict = {}
        t = [1e9]
        clk = lambda: t[0]
        try:
            comp = make(recording_opener(store), clk)
            good = getattr(comp, meth)()
        except Exception as e:
            out.append((name, "clean fetch", f"could not record a clean response ({type(e).__name__}: {e}); not tested"))
            continue
        good_s = json.dumps(good, sort_keys=True, default=str)
        for cname, f in corruptions():
            bad = {u: f(b) for u, b in store.items()}
            t[0] += 10 ** 6                                  # past every cache lifetime: forces a refresh
            comp.opener = lambda req, timeout=None, bad=bad: _Resp(bad.get(getattr(req, "full_url", req), b""))
            try:
                got = getattr(comp, meth)()
            except Exception as e:
                out.append((name, cname, f"CRASH ({type(e).__name__}: {str(e)[:60]})"))
                continue
            s = json.dumps(got, sort_keys=True, default=str)
            if "NaN" in s or "Infinity" in s:
                out.append((name, cname, "NaN SHOWN"))
            elif _same_data(got, good):
                out.append((name, cname, "kept the last good copy"))
            else:
                out.append((name, cname, "changed: " + _what_changed(good, got)))
            comp.opener = recording_opener(store)
            t[0] += 10 ** 6
            getattr(comp, meth)()                             # back to good data for the next case
        del good_s
    # CFTC uses its own fetch function
    store = {}

    def fetch_rec(url):
        if url not in store:
            store[url] = positioning.Positioning._get(url)
        return store[url]
    t = [1e9]
    comp = positioning.Positioning(clock=lambda: t[0], fetch=fetch_rec)
    good = comp.get()
    for cname, f in corruptions():
        comp._fetch = lambda url, f=f: f(store[url])
        t[0] += 10 ** 7
        try:
            got = comp.get()
        except Exception as e:
            out.append(("CFTC positioning", cname, f"CRASH ({type(e).__name__})"))
            continue
        s = json.dumps(got, default=str)
        out.append(("CFTC positioning", cname, "NaN SHOWN" if "NaN" in s else
                    "kept the last good copy" if got.get("markets") == good.get("markets") else "changed: " + _what_changed(good, got)))
    return out


def _same_data(got, good) -> bool:
    """Equal apart from fetch times and stale flags (a kept copy marked stale is the last good copy)."""
    def strip(d):
        if isinstance(d, dict):
            return {k: strip(v) for k, v in d.items() if k not in ("error", "fetched", "fetched_at", "ok_at", "source", "stale",
                                                                   "age_s", "weights_asof")}
        if isinstance(d, list):
            return [strip(x) for x in d]
        return d
    return strip(got) == strip(good)


def _what_changed(a, b) -> str:
    ka = set((a or {}).keys()) | set((b or {}).keys())
    diff = [k for k in sorted(ka) if (a or {}).get(k) != (b or {}).get(k) and k not in ("fetched_at",)]
    return ", ".join(diff)[:80] or "?"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    rows = fuzz_levels() + fuzz_basis() + fuzz_feeds()
    w = max(len(r[1]) for r in rows)
    for src, case, verdict in rows:
        print(f"{src:22s} {case:{w}s}  {verdict}")
    bad = [r for r in rows if r[2].startswith(("SILENTLY WRONG", "CRASH", "NaN SHOWN"))]
    print(f"\n{len(rows)} cases. RESULT:", "PASS" if not bad else f"FAIL - {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
