"""Every GEX PRO check in one run: python tools/check.py  (from the project folder; about 2 minutes)

  tests      the unit and integration tests
  lint       pyflakes (unused names, undefined names) and vulture (dead code)
  pricing    every pricing formula against finite differences and identities
  math       live levels re-derived from the raw Cboe data with independent code
  audit      live data, levels and the TradingView paste end to end, NQ and ES
  track      every track-record plan and grade re-derived by hand; the backtest recounted from raw files
  site       the hosted website's data files: present, filled in, and recent

--quick skips the live checks (math, audit, track, site). Exits 1 if anything failed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ["gexsys", "feeds", "briefings", "trackrecord", "gexpro"]
SITE = "https://wsevwevx.github.io/gex-pro/data/"


def run(args: list[str], ok_text: str | None = None) -> tuple[bool, str]:
    p = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout + p.stderr).strip()
    ok = p.returncode == 0 and (ok_text is None or ok_text in out)
    return ok, out


def site() -> tuple[bool, str]:
    lines, ok = [], True

    def get(name):
        with urllib.request.urlopen(urllib.request.Request(f"{SITE}{name}?t={int(time.time())}", headers={"User-Agent": "Mozilla/5.0 (GEX PRO check)"}), timeout=30) as r:
            return json.loads(r.read())

    try:
        all_ = get("all.json")
        # the build chain runs every 3-6 min while futures trade (Sun 18:00 - Fri 17:00 ET), hourly otherwise
        from zoneinfo import ZoneInfo
        et = datetime.now(ZoneInfo("America/New_York"))
        open_ = (et.weekday() == 6 and et.hour >= 18) or et.weekday() <= 3 or (et.weekday() == 4 and et.hour < 17)
        built_min = (datetime.now(timezone.utc) - datetime.fromisoformat(all_["now"])).total_seconds() / 60
        good = built_min < (30 if open_ else 120)
        ok &= good
        lines.append(f"{'OK  ' if good else 'FAIL'} site rebuilt {built_min:.0f} min ago (futures {'open' if open_ else 'closed'})")
        # Pine strings hold at most 4,096 characters, and the NQ + ES paste is one string
        with urllib.request.urlopen(urllib.request.Request(f"{SITE}pine-published.txt?t={int(time.time())}", headers={"User-Agent": "Mozilla/5.0 (GEX PRO check)"}), timeout=30) as r:
            paste = r.read().decode("utf-8")
        good = 0 < len(paste) <= 3800
        ok &= good
        lines.append(f"{'OK  ' if good else 'FAIL'} TradingView paste {len(paste)} of 4,096 characters")
        for w in all_["workers"]:
            asof = datetime.fromisoformat(w["result"]["summary"]["asof"])
            age_h = (datetime.now(timezone.utc) - asof).total_seconds() / 3600
            good = age_h < 3
            ok &= good
            lines.append(f"{'OK  ' if good else 'FAIL'} levels {w['market']}: {age_h:.1f} h old")
        checks = {"quotes.json": lambda d: len(d["quotes"]), "screener.json": lambda d: len(d["stocks"]),
                  "news.json": lambda d: len(d.get("events") or d.get("items") or d) if d else 0,
                  "trackrecord.json": lambda d: 1 if d else 0}
        for m in ("NQ", "ES"):
            checks[f"heatmap-{m}-5m.json"] = lambda d: len(d["candles"]) and len(d["columns"])
        for name, count in checks.items():
            n = count(get(name))
            ok &= n > 0
            lines.append(f"{'OK  ' if n > 0 else 'FAIL'} {name}: {n}")
    except Exception as e:
        return False, f"FAIL could not read the hosted site: {e}"
    return ok, "\n".join(lines)


def main() -> int:
    quick = "--quick" in sys.argv
    steps = [("tests", lambda: run(["-m", "unittest", "discover", "-s", "tests", "-q"])),
             ("pyflakes", lambda: run(["-m", "pyflakes", *PACKAGES, "tests", "tools"])),
             ("vulture", lambda: run(["-m", "vulture", *PACKAGES, "--min-confidence", "80"])),
             ("pricing", lambda: run(["tools/pricing_stress.py"], "ALL PRICING CHECKS PASS"))]
    if not quick:
        steps += [("math", lambda: run(["tools/verify_math.py"], "ALL MATCH")),
                  ("audit", lambda: run(["-m", "gexsys", "audit"], "0 failed")),
                  ("track", lambda: run(["tools/verify_track.py"], "ALL MATCH")),
                  ("site", site)]
    failed = []
    for name, fn in steps:
        t = time.time()
        ok, out = fn()
        tail = "\n".join(out.splitlines()[-4 if ok else -40:])
        print(f"\n=== {name}: {'PASS' if ok else 'FAIL'} ({time.time() - t:.0f}s)\n{tail}")
        if not ok:
            failed.append(name)
        if name == "audit" and ok and "[FAIL]" in out:
            failed.append(name)
    print("\n" + ("ALL CHECKS PASS" if not failed else "FAILED: " + ", ".join(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
