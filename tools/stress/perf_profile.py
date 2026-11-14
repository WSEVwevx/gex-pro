"""Performance profile of one refresh and of the hosted build, on frozen inputs, with the outputs fingerprinted.

  python tools/stress/perf_profile.py record                 save live Cboe chains, Yahoo bars and candles
  python tools/stress/perf_profile.py fill                   build a 12-day store (RTH, one file a minute)
  python tools/stress/perf_profile.py run [--label NAME]     per-stage timings (cold x5, warm x5, hourly stats x5),
                                                             cProfile top 25, peak memory, output fingerprint
  python tools/stress/perf_profile.py net                    live: requests, bytes and time in one refresh
  python tools/stress/perf_profile.py build [--label NAME]   the hosted build: per-component time (gex inputs replayed)
  python tools/stress/perf_profile.py compare A B            outputs of two labelled runs: byte-identical paste,
                                                             every number within 1e-12

Replay: the clock is frozen at FROZEN (Friday 15:45 ET, RTH: the 0DTE path is live) and every chain is stamped
fresh at that moment; network calls return the recordings. The store holds 12 trading days of RTH history at one
file a minute plus today's session so far (~5,000 files per market), so costs that grow with history show up.
Nothing in the product is changed to measure it: timing and freezing hook in through module attributes.
"""
from __future__ import annotations

import cProfile
import copy
import json
import os
import pstats
import shutil
import statistics
import subprocess
import sys
import time
import tracemalloc
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
BASE = Path(os.path.expandvars(r"%TEMP%/claude/bc7626df52a346c5/61f0ae57-b303-48cd-8d08-5b790089e8ed/scratchpad/perf"))
REC, STORE, OUT = BASE / "rec", BASE / "store", BASE / "out"
FROZEN = datetime(2026, 11, 13, 20, 45, tzinfo=timezone.utc)          # Fri 15:45 ET
TS = FROZEN.strftime("%Y-%m-%d %H:%M:%S")
CONFIGS = ("configs/free_nq_cboe.json", "configs/free_es_cboe.json")
_real_dt = datetime


class FrozenDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN.astimezone(tz) if tz else FROZEN.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN.replace(tzinfo=None)


def freeze():
    import importlib
    for m in ("gexsys.service", "gexsys.pipeline", "gexsys.providers.cboe", "gexsys.normalize", "gexsys.basis",
              "gexsys.extras", "gexsys.engine", "gexsys.session", "gexsys.storage", "gexsys.component", "gexsys.heatmap",
              "gexsys.ladder", "gexsys.bias", "gexsys.alerts", "gexsys.publish", "gexsys.export", "gexsys.mapping",
              "gexpro.site", "gexpro.components", "gexpro.context"):
        importlib.import_module(m)                 # everything first: a module imported later would see the real clock
    for name, mod in list(sys.modules.items()):
        if name.split(".")[0] in ("gexsys", "gexpro", "trackrecord", "feeds", "briefings") and getattr(mod, "datetime", None) is _real_dt:
            mod.datetime = FrozenDT


# ------------------------------------------------------------------ replay
def replay():
    """Network -> recordings. Returns the raw chain texts (JSON is parsed on every call, as the real feed is)."""
    from gexsys import basis, heatmap, service
    from gexsys.providers.cboe import CboeProvider
    texts = {}
    for k in ("_NDX", "QQQ", "_SPX", "SPY"):
        d = json.loads((REC / f"cboe{k}.json").read_text())
        d["timestamp"] = TS
        texts[k] = json.dumps(d)

    def http(url, headers, limiter=None):
        return json.loads(texts[url.rsplit("/", 1)[1][:-5]])
    service.make_provider = lambda cfg: CboeProvider(http=http, include_etf=cfg.provider.get("include_etf", False))
    y = json.loads((REC / "yahoo1m.json").read_text())
    y = {s: {int(k): v for k, v in d.items()} for s, d in y.items()}
    basis._yahoo_1m = lambda sym, asof: y[sym]
    c = json.loads((REC / "candles.json").read_text())
    heatmap.fetch_candles = lambda market, tf: copy.deepcopy(c[f"{market}|{tf}"])


# ------------------------------------------------------------------ stage timers
T: dict = defaultdict(float)
N: dict = defaultdict(int)


def timed(owner, attr, label):
    fn = getattr(owner, attr)

    def wrap(*a, **k):
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            T[label] += time.perf_counter() - t
            N[label] += 1
    setattr(owner, attr, wrap)


def instrument():
    from gexsys import alerts, engine, pipeline, service, session, storage
    from gexsys.providers import cboe
    timed(cboe.CboeProvider, "fetch_snapshot", "fetch+parse (all)")
    timed(cboe.CboeProvider, "_chain", "  parse chain -> contracts")
    timed(cboe, "merge_etf", "  ETF merge")
    timed(pipeline, "normalize", "normalize")
    timed(engine, "compute", "GEX compute (all calls)")
    timed(engine, "_solve_iv", "  IV solve")
    timed(engine, "gamma_profile", "  profile + zero gamma")
    timed(pipeline, "summarize", "levels (summarize)")
    timed(pipeline, "compute_extras", "extras")
    timed(pipeline, "heat_profile", "heat profile")
    timed(pipeline, "build_ladder", "ladder")
    timed(pipeline, "compute_bias", "bias")
    timed(pipeline, "_futures_ref", "basis / futures ref")
    timed(pipeline, "map_summary", "mapping")
    timed(pipeline, "pine_payload", "paste")
    timed(storage.SnapshotStore, "save", "store save")
    timed(storage.SnapshotStore, "latest", "store read latest")
    timed(storage.SnapshotStore, "prune", "store prune")
    timed(alerts.AlertEngine, "evaluate", "alerts")
    timed(pipeline, "run_once", "run_once (total)")
    timed(service.MarketWorker, "_add_session", "session block (total)")
    timed(session, "summaries_since", "  session: read today's summaries")
    timed(session, "prior_levels", "  session: prior sessions' levels")
    timed(session, "changes", "  session: changes")
    timed(service.MarketWorker, "_stats", "  session: reaction stats")
    timed(session, "reaction_stats", "    reaction stats compute")
    timed(service.MarketWorker, "_save_last_good", "save last good")
    timed(service.MarketWorker, "_maybe_publish", "publish")


# ------------------------------------------------------------------ store
def fill():
    """12 trading days of RTH history, one file a minute, plus today's session to 15:44 ET."""
    from gexsys import config as cfgmod, marketcal, service
    freeze()
    replay()
    if STORE.exists():
        shutil.rmtree(STORE)
    for cfgp in CONFIGS:
        cfg = cfgmod.load(cfgp)
        cfg.storage["root"] = str(STORE)
        w = service.MarketWorker(cfg)
        w.candles_fn = None
        w.notify_desktop = w.send_webhook = lambda *a, **k: None
        w.step(FROZEN)
        tpl = w.result["summary"]
        tpl.pop("ladder", None)
        root = STORE / w.key
        for f in root.glob("*/*.json"):
            f.unlink()
        days, d = [], FROZEN.astimezone(marketcal.NY).date()
        while len(days) < 13:
            if marketcal.is_trading_day(d):
                days.append(d)
            d -= timedelta(days=1)
        n = 0
        for day in days:
            t = datetime.combine(day, datetime.min.time().replace(hour=9, minute=30), marketcal.NY)
            end = min(datetime.combine(day, marketcal.rth_close(day), marketcal.NY), FROZEN - timedelta(minutes=1))
            while t <= end:
                s = dict(tpl, asof=t.astimezone(timezone.utc).isoformat())
                p = root / t.astimezone(timezone.utc).strftime("%Y%m%d") / (t.astimezone(timezone.utc).strftime("%H%M%S_%f") + ".json")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(s, separators=(",", ":")), encoding="utf-8")
                n += 1
                t += timedelta(minutes=1)
        for f in STORE.glob("stats-*.json"):
            f.unlink()
        print(f"{w.key}: {n} files, {sum(f.stat().st_size for f in root.rglob('*.json')) / 1e6:.0f} MB")


# ------------------------------------------------------------------ one refresh
def make_workers(store: Path):
    from gexsys import config as cfgmod, service
    ws = []
    for cfgp in CONFIGS:
        cfg = cfgmod.load(cfgp)
        cfg.storage["root"] = str(store)
        w = service.MarketWorker(cfg)
        w.notify_desktop = w.send_webhook = lambda *a, **k: None
        ws.append(w)
    return ws


def work_copy() -> Path:
    """A fresh copy of the filled store, so every run starts from the same history (files only grow by one)."""
    dst = BASE / "work"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(STORE, dst)
    return dst


def one_cold(kind: str) -> dict:
    """In this (fresh) process: build workers and time their first refresh; 'warm' times a second one after it,
    'stats' a refresh whose hourly reaction-stats cache has expired."""
    freeze()
    replay()
    instrument()
    store = work_copy()
    ws = make_workers(store)
    out = {}
    for w in ws:
        if kind in ("warm", "stats"):
            w.step(FROZEN)
            if kind == "stats":
                for f in store.glob("stats-*.json"):
                    f.unlink()
        else:
            for f in store.glob(f"stats-{w.key}.json"):
                pass                                      # cold start with the hourly cache present (the usual case)
        T.clear()
        N.clear()
        t = time.perf_counter()
        w.step(FROZEN)
        out[w.key] = {"total": time.perf_counter() - t, "stages": dict(T), "calls": dict(N)}
    return out


def fingerprint(label: str) -> None:
    """The outputs of a warm refresh, saved for compare()."""
    freeze()
    replay()
    store = work_copy()
    ws = make_workers(store)
    res = {}
    for w in ws:
        w.step(FROZEN)
        w.step(FROZEN)
        r = w.result
        res[w.key] = {"summary": r["summary"], "mapped": r["mapped"], "pine": r["pine"], "session": r.get("session"),
                      "ladder": r.get("ladder"), "bias": r.get("bias")}
    OUT.mkdir(parents=True, exist_ok=True)
    from gexsys.models import to_jsonable
    (OUT / f"{label}.json").write_text(json.dumps(to_jsonable(res), sort_keys=True, default=str), encoding="utf-8")


def run(label: str) -> None:
    results = {"cold": [], "warm": [], "stats": []}
    for kind in results:
        for i in range(5):
            p = subprocess.run([sys.executable, __file__, "_child", kind], capture_output=True, text=True, cwd=ROOT)
            line = [x for x in p.stdout.splitlines() if x.startswith("{")]
            if not line:
                print(p.stdout[-2000:], p.stderr[-3000:])
                raise SystemExit(f"child {kind} failed")
            results[kind].append(json.loads(line[-1]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"timing-{label}.json").write_text(json.dumps(results), encoding="utf-8")
    for key in ("NQ-CBOE", "ES-CBOE"):
        print(f"\n{key}  (median of 5, seconds)")
        stages = sorted({s for k in results for r in results[k] for s in r[key]["stages"]},
                        key=lambda s: -statistics.median(r[key]["stages"].get(s, 0) for r in results["warm"]))
        print(f"  {'stage':40s} {'cold':>7} {'warm':>7} {'stats':>7} {'calls':>6}")
        med = lambda kind, s: statistics.median(r[key]["stages"].get(s, 0.0) for r in results[kind])
        print(f"  {'REFRESH TOTAL':40s} {statistics.median(r[key]['total'] for r in results['cold']):7.3f} "
              f"{statistics.median(r[key]['total'] for r in results['warm']):7.3f} {statistics.median(r[key]['total'] for r in results['stats']):7.3f}")
        for s in stages:
            print(f"  {s:40s} {med('cold', s):7.3f} {med('warm', s):7.3f} {med('stats', s):7.3f} {results['warm'][0][key]['calls'].get(s, 0):6d}")
    # cProfile and peak memory of one warm refresh per market
    p = subprocess.run([sys.executable, __file__, "_prof"], capture_output=True, text=True, cwd=ROOT)
    print(p.stdout[-9000:])
    fingerprint(label)
    print(f"\noutputs saved as {label}")


def prof() -> None:
    freeze()
    replay()
    store = work_copy()
    ws = make_workers(store)
    for w in ws:
        w.step(FROZEN)
    pr = cProfile.Profile()
    tracemalloc.start()
    pr.enable()
    for w in ws:
        w.step(FROZEN)
    pr.disable()
    cur, peak = tracemalloc.get_traced_memory()
    st = pstats.Stats(pr)
    print(f"\npeak Python memory during a warm refresh of both markets: {peak / 1e6:.0f} MB (traced)")
    print("\ncProfile, warm refresh of both markets, top 25 by own time:")
    st.sort_stats("tottime").print_stats(25)


def compare(a: str, b: str) -> int:
    A = json.loads((OUT / f"{a}.json").read_text(encoding="utf-8"))
    B = json.loads((OUT / f"{b}.json").read_text(encoding="utf-8"))
    diffs = []

    def walk(x, y, path):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in set(x) | set(y):
                if k not in x or k not in y:
                    diffs.append(f"{path}.{k}: only in {'A' if k in x else 'B'}")
                else:
                    walk(x[k], y[k], f"{path}.{k}")
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                diffs.append(f"{path}: {len(x)} vs {len(y)} items")
            for i, (p, q) in enumerate(zip(x, y)):
                walk(p, q, f"{path}[{i}]")
        elif isinstance(x, float) and isinstance(y, (int, float)) or isinstance(y, float) and isinstance(x, (int, float)):
            if abs(x - y) > 1e-12 * max(1.0, abs(x)):
                diffs.append(f"{path}: {x} vs {y}")
        elif x != y:
            diffs.append(f"{path}: {str(x)[:80]!r} vs {str(y)[:80]!r}")
    walk(A, B, "")
    pastes = all(A[k]["pine"] == B[k]["pine"] for k in A)
    print(f"pastes byte-identical: {pastes}; differences: {len(diffs)}")
    for d in diffs[:20]:
        print("  ", d)
    return 0 if pastes and not diffs else 1


def net() -> None:
    """Live: every request one refresh of both markets makes."""
    import urllib.request
    from gexsys import config as cfgmod, service
    seen = []
    real = urllib.request.OpenerDirector.open

    def op(self, req, *a, **k):
        url = req.full_url if hasattr(req, "full_url") else req
        t = time.perf_counter()
        r = real(self, req, *a, **k)
        body = r.read()
        seen.append((url.split("?")[0], len(body), time.perf_counter() - t))
        import io
        r.read = io.BytesIO(body).read
        return r
    urllib.request.OpenerDirector.open = op
    tmp = BASE / "netstore"
    shutil.rmtree(tmp, ignore_errors=True)
    for cfgp in CONFIGS:
        cfg = cfgmod.load(cfgp)
        cfg.storage["root"] = str(tmp)
        w = service.MarketWorker(cfg)
        w.notify_desktop = w.send_webhook = lambda *a, **k: None
        seen.clear()
        t = time.perf_counter()
        w.step()
        tot = time.perf_counter() - t
        print(f"\n{w.key}: refresh {tot:.2f} s wall; {len(seen)} requests, {sum(b for _, b, _ in seen) / 1e6:.1f} MB, "
              f"{sum(s for *_, s in seen):.2f} s in requests")
        dup = defaultdict(int)
        for u, b, s in seen:
            dup[u] += 1
            print(f"   {s:6.2f} s {b / 1e6:7.2f} MB  {u}")
        rep = {u: c for u, c in dup.items() if c > 1}
        print("   repeated in this refresh:", rep or "none")


def build(label: str) -> None:
    """The hosted build with the gex inputs replayed (feeds live: their time is network)."""
    freeze()
    replay()
    from gexpro import components, site
    from gexsys import config as cfgmod
    state = BASE / "state"
    shutil.rmtree(state, ignore_errors=True)
    shutil.copytree(STORE, state / "snapshots")
    comps = components.default_components([cfgmod.load(p) for p in CONFIGS])
    times = {}
    for c in comps:
        f = c.build_static

        def wrap(data, st, f=f, name=c.name):
            t = time.perf_counter()
            try:
                return f(data, st)
            finally:
                times[name] = time.perf_counter() - t
        c.build_static = wrap
    out = BASE / "site-build"
    shutil.rmtree(out, ignore_errors=True)
    t = time.perf_counter()
    site.build(comps, out, state)
    total = time.perf_counter() - t
    print(f"hosted build {total:.1f} s:", {k: round(v, 2) for k, v in times.items()})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"build-{label}.json").write_text(json.dumps({"total": total, "components": times}), encoding="utf-8")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "record":
        raise SystemExit("recorded already by hand; see REC")
    if cmd == "fill":
        fill()
    elif cmd == "_child":
        print(json.dumps(one_cold(sys.argv[2])))
    elif cmd == "_prof":
        prof()
    elif cmd == "run":
        run(sys.argv[3] if len(sys.argv) > 3 else "base")
    elif cmd == "net":
        net()
    elif cmd == "build":
        build(sys.argv[3] if len(sys.argv) > 3 else "base")
    elif cmd == "compare":
        raise SystemExit(compare(sys.argv[2], sys.argv[3]))
