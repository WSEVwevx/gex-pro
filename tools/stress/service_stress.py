"""Stress test F1: the local service under 48 hours of compressed time, faults injected.

  python tools/stress/service_stress.py [--hours 48] [--step-min 5]

The real MarketWorker (NQ and ES) steps through simulated time, one refresh per step, on chains recorded live once
and replayed (so the right levels are known: the clean run's). Faults:
  network     5-minute outages at random (every request fails: Cboe, Yahoo)
  sleep       the PC sleeps 8 hours and wakes (the clock jumps)
  bad feed    a refresh returns an unusable chain (UNAVAILABLE)
  full disk   every file write fails for an hour
  corruption  the saved last-good / published files are overwritten with garbage (truncated, null, wrong shape,
              binary), then the service restarts
After every step the levels served must be the clean run's (or nothing yet). Never different.
Also: two real `python -m gexpro serve` launches on a spare port; the second must refuse and exit, the first keep
serving. Memory (the process's working set) and CPU time are reported over the run, with the growth.
Run 2026-11-10 (48 h, 15-minute steps, 192 x 2 refreshes): memory flat (+5.7 MB); second launch refused; 3 crashes
on restart with a null / wrong-shape saved file (fixed, tests/test_feed_guards.py); steps slowed as history grew
(latest() re-read every file: fixed). 59 ES steps served zero gamma one tick from the start-of-run answer: the real
clock moved 45 minutes on the same chain and time decay moved zero gamma 0.11 points (checked directly), so the
fixed reference, not the service, was wrong there. A truer harness would recompute the reference at each step.
Tolerance (fixed before running): no wrong level served, no crash, the second launch refused, memory growth from
the first 10% of the run to the last under 10 MB.
"""
from __future__ import annotations

import argparse
import builtins
import copy
import os
import random
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import verify_math as vm  # noqa: E402
from gexsys import basis, config as cfgmod, service  # noqa: E402
from gexsys.providers.cboe import CboeProvider  # noqa: E402

TS_FMT = "%Y-%m-%d %H:%M:%S"


def rss_mb() -> float:
    """This process's working set (Windows), in MB."""
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize / 1e6


class Faults:
    def __init__(self):
        self.offline = False
        self.disk_full = False
        self.bad_feed = False


def make_worker(cfg, raw, faults, store_root):
    cfg = copy.deepcopy(cfg)
    cfg.storage["root"] = str(store_root)

    def http(url, headers, limiter=None):
        if faults.offline:
            raise urllib.error.URLError("simulated outage")
        sym = url.rsplit("/", 1)[1][:-5]
        r = copy.deepcopy(raw[sym])
        r["timestamp"] = (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime(TS_FMT)   # fresh every refresh
        if faults.bad_feed:
            for o in r["data"]["options"]:
                o["open_interest"] = 0
        return r
    w = service.MarketWorker(cfg)
    w.provider = CboeProvider(http=http, include_etf=True)
    w.notify_desktop = lambda *a, **k: None
    w.send_webhook = lambda *a, **k: None
    w.candles_fn = lambda market: (_ for _ in ()).throw(OSError("offline")) if faults.offline else []
    return w


def served(w):
    r = w.result
    if not r:
        return None
    s = r.get("mapped") or r["summary"]
    p = lambda k: (s.get(k) or {}).get("price")
    return (p("zero_gamma"), p("call_wall"), p("put_wall"), r["summary"].get("status"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=48)
    ap.add_argument("--step-min", type=float, default=5)
    a = ap.parse_args()
    rng = random.Random(11)
    raw = {k: vm.fetch(k) for k in ("_NDX", "QQQ", "_SPX", "SPY")}
    yb = {s: basis._yahoo_1m(s, datetime.now(timezone.utc)) for s in ("NQ=F", "^NDX", "ES=F", "^GSPC")}
    faults = Faults()

    def yahoo(sym, asof):
        if faults.offline:
            raise OSError("simulated outage")
        return yb[sym]
    basis._yahoo_1m = yahoo

    real_open, real_replace = builtins.open, os.replace

    def guarded_open(f, mode="r", *aa, **kk):
        if faults.disk_full and any(c in mode for c in "wax"):
            raise OSError(28, "No space left on device (simulated)")
        return real_open(f, mode, *aa, **kk)

    def guarded_replace(src, dst, *aa, **kk):
        if faults.disk_full:
            raise OSError(28, "No space left on device (simulated)")
        return real_replace(src, dst, *aa, **kk)
    builtins.open, os.replace = guarded_open, guarded_replace

    store = Path(tempfile.mkdtemp(prefix="gexpro-stress-"))
    cfgs = [cfgmod.load("configs/free_nq_cboe.json"), cfgmod.load("configs/free_es_cboe.json")]
    workers = [make_worker(c, raw, faults, store) for c in cfgs]
    for w in workers:
        w.step(datetime.now(timezone.utc))
    clean = {w.key: served(w) for w in workers}
    print("clean levels:", clean)

    steps = int(a.hours * 60 / a.step_min)
    sim = datetime.now(timezone.utc)
    outages = set(rng.sample(range(steps), max(1, steps // 40)))          # ~2.5% of steps: 5-minute outages
    sleep_at, bad_at = steps // 3, set(rng.sample(range(steps), 3))
    disk_from, disk_to = steps // 2, steps // 2 + int(60 / a.step_min)
    corrupt_at = 2 * steps // 3
    wrong, crashes, log_rows = [], [], []
    t_cpu, t_wall = time.process_time(), time.time()
    for i in range(steps):
        sim += timedelta(minutes=a.step_min)
        if i == sleep_at:
            sim += timedelta(hours=8)                                     # the PC slept
        faults.offline = i in outages
        faults.bad_feed = i in bad_at
        faults.disk_full = disk_from <= i < disk_to
        if i == corrupt_at:
            faults.disk_full = False
            for n, junk in enumerate((b'{"summary": {"zero', b"null", b'{"unexpected": 1}', b"\x00\xff\xfe garbage")):
                for w in workers:
                    for p in (w._good_path, w._pub_path):
                        p.write_bytes(junk)
                try:
                    workers = [make_worker(c, raw, faults, store) for c in cfgs]   # restart on the damaged files
                    for w in workers:
                        got = served(w)
                        if got is not None and got[:3] != clean[w.key][:3]:
                            wrong.append(f"restart on corrupt file #{n}: {w.key} served {got}")
                except Exception as e:
                    crashes.append(f"restart on corrupt file #{n} ({junk[:20]!r}): {type(e).__name__}: {e}")
                    workers = []
            if not workers:                                                 # a clean restart so the run can go on
                for name in os.listdir(store):
                    if name.startswith(("last_good_", "published_")):
                        os.remove(store / name)
                workers = [make_worker(c, raw, faults, store) for c in cfgs]
        for w in workers:
            try:
                w.step(sim)
            except Exception as e:
                crashes.append(f"step {i} {w.key}: {type(e).__name__}: {e}")
                continue
            got = served(w)
            if got is not None and got[:3] != clean[w.key][:3]:
                wrong.append(f"step {i} ({'outage' if faults.offline else 'bad feed' if faults.bad_feed else 'disk full' if faults.disk_full else 'normal'}): "
                             f"{w.key} served {got}, clean {clean[w.key]}")
        if i % max(1, steps // 20) == 0 or i == steps - 1:
            log_rows.append((i, sim, rss_mb(), time.time() - t_wall, time.process_time() - t_cpu))
    builtins.open, os.replace = real_open, real_replace
    print(f"\n{steps} steps x {len(workers)} markets, {a.step_min:g}-minute steps, {a.hours:g} simulated hours; "
          f"{len(outages)} outages, 1 sleep of 8 h, {len(bad_at)} unusable feeds, {disk_to - disk_from} steps of full disk, "
          f"4 corrupt-file restarts")
    print(f"{'step':>5} {'memory MB':>10} {'wall s':>8} {'CPU s':>7}")
    for i, _, cur, wall, cpu in log_rows:
        print(f"{i:5d} {cur:10.1f} {wall:8.1f} {cpu:7.1f}")
    first = [r[2] for r in log_rows if r[0] <= steps // 10]
    last = log_rows[-1][2]
    growth = last - (sum(first) / len(first))
    print(f"memory growth, first 10% to the end: {growth:+.1f} MB")

    # two launches of the real service on a spare port
    env = dict(os.environ, GEXPRO_STRESS="1")
    port = "8799"
    p1 = subprocess.Popen([sys.executable, "-m", "gexpro", "--log-level", "ERROR", "serve", "--auto", "--port", port],
                          cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    second_ok = first_ok = False
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).read()
                first_ok = True
                break
            except Exception:
                time.sleep(1)
        p2 = subprocess.run([sys.executable, "-m", "gexpro", "--log-level", "ERROR", "serve", "--auto", "--port", port],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        second_ok = p2.returncode == 3 and "ALREADY RUNNING" in p2.stdout
        still = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5).status == 200
        print(f"\ntwo launches: first serving {first_ok}; second exited {p2.returncode} "
              f"({'refused: already running' if second_ok else p2.stdout[-120:]}); first still serving {still}")
        second_ok = second_ok and still
    finally:
        p1.terminate()
        try:
            p1.wait(10)
        except subprocess.TimeoutExpired:
            p1.kill()

    bad = wrong[:10] + crashes[:10]
    if growth > 10:
        bad.append(f"memory grew {growth:.1f} MB")
    if not (first_ok and second_ok):
        bad.append("double launch not handled")
    print("\nRESULT:", "PASS" if not bad else f"FAIL - {len(wrong)} wrong, {len(crashes)} crashes:\n  " + "\n  ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
