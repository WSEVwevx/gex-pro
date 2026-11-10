"""Stress test D4: look-ahead and survivorship audit of the public track record (git branch track-record).

  python tools/stress/lookahead_audit.py

Every graded number must come from data timestamped before the 09:30 ET open it is graded against, no session
may disappear after the fact, and nothing may be rewritten once graded. Checks, per session file:
  L1  plan.asof (the data time of the snapshot) is before that session's 09:30 ET open
  L2  plan.frozen_at is at or after plan.asof (rebuilt plans: frozen later, but from pre-open data only)
  L3  graded_at is after that session's close (the grade could not have been known earlier)
  L4  the outcome's open, high, low, close are a coherent bar (low <= open, close <= high)
  L5  the 9:30 paste's data time (ts) is before the open and its bt mark names the same session
  L6  the 1-minute record starts at 09:30, matches the graded index open and ends at or before the close
Survivorship:
  S1  every trading day from the first recorded session to the last has a file for NQ and ES
      (graded, missed or no_prices: never silently absent)
  S2  git history: once a session file says "graded", no later commit changes its plan or outcome
  S3  history.csv has exactly the sessions the files have, with the same status
Tolerance: zero violations.
"""
from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gexsys import marketcal  # noqa: E402

NY = marketcal.NY
BR = __import__("os").environ.get("GEXPRO_AUDIT_BRANCH", "origin/track-record")


def git(*a) -> str:
    return subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8").stdout


def show(path: str, rev: str = BR) -> str:
    return git("show", f"{rev}:{path}")


def main() -> int:
    git("fetch", "-q", "origin", "track-record")
    files = git("ls-tree", "-r", "--name-only", BR).split()
    sessions = {f: json.loads(show(f)) for f in files if f.startswith("sessions/")}
    pastes = {f: show(f).strip() for f in files if f.startswith("pastes/")}
    minutes = {f: json.loads(show(f)) for f in files if f.startswith("minutes/")}
    bad: list[str] = []
    for f, s in sorted(sessions.items()):
        d = date.fromisoformat(s["session"])
        o = datetime.combine(d, time(9, 30), NY)
        c = datetime.combine(d, marketcal.rth_close(d), NY)
        p, out = s.get("plan") or {}, s.get("outcome") or {}
        if p:
            asof = datetime.fromisoformat(p["asof"])
            if asof >= o:
                bad.append(f"L1 {f}: data {asof.isoformat()} is not before the open {o.isoformat()}")
            if datetime.fromisoformat(p["frozen_at"]) < asof:
                bad.append(f"L2 {f}: frozen before its own data time")
        if s.get("status") == "graded":
            if datetime.fromisoformat(s["graded_at"]) <= c:
                bad.append(f"L3 {f}: graded at {s['graded_at']}, before the close {c.isoformat()}")
            if not (out["low"] <= min(out["open"], out["close"]) and max(out["open"], out["close"]) <= out["high"]):
                bad.append(f"L4 {f}: incoherent bar {out}")
    for f, text in pastes.items():
        day = f.split("/")[1][:10]
        tok = dict(t.split("=", 1) for t in text.split(";") if "=" in t)
        o = datetime.combine(date.fromisoformat(day), time(9, 30), NY)
        ts = datetime.fromtimestamp(int(tok.get("ts", "0")) / 1000, NY)
        if ts >= o:
            bad.append(f"L5 {f}: paste data {ts.isoformat()} is not before the open")
        if tok.get("bt") != day.replace("-", ""):
            bad.append(f"L5 {f}: bt={tok.get('bt')} does not name {day}")
    for f, r in minutes.items():
        sf = f"sessions/{r['session']}_{r['market']}.json"
        s = sessions.get(sf) or {}
        d = date.fromisoformat(r["session"])
        close_min = (marketcal.rth_close(d).hour * 60 + marketcal.rth_close(d).minute) - 570
        if not r["bars"] or r["bars"][0][0] != 0:
            bad.append(f"L6 {f}: does not start at 09:30")
        if r["bars"] and r["bars"][-1][0] >= close_min:
            bad.append(f"L6 {f}: runs past the close")
        if (s.get("outcome") or {}).get("open") != r.get("index_open"):
            bad.append(f"L6 {f}: index open {r.get('index_open')} differs from the graded open {(s.get('outcome') or {}).get('open')}")
    # S1: no trading day silently absent
    days = sorted({s["session"] for s in sessions.values()})
    d, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    while d <= last:
        if marketcal.is_trading_day(d):
            for m in ("NQ", "ES"):
                if f"sessions/{d.isoformat()}_{m}.json" not in sessions:
                    bad.append(f"S1 {d} {m}: no session file (neither graded nor marked missed)")
        d += timedelta(days=1)
    # S2: nothing rewritten after grading
    for f in sorted(sessions):
        revs = git("log", "--format=%H", "--reverse", BR, "--", f).split()
        graded = None
        for rev in revs:
            try:
                s = json.loads(show(f, rev))
            except ValueError:
                continue
            if graded is None and s.get("status") == "graded":
                graded = (s.get("plan"), s.get("outcome"))
            elif graded is not None and (s.get("plan"), s.get("outcome")) != graded:
                bad.append(f"S2 {f}: plan or outcome changed after grading (commit {rev[:8]})")
    # S3: the permanent table agrees with the files
    rows = {(r["session"], r["market"]): r["status"] for r in csv.DictReader(io.StringIO(show("history.csv")))}
    files_ = {(s["session"], s["market"]): s["status"] for s in sessions.values()}
    if rows != files_:
        diff = sorted(set(rows.items()) ^ set(files_.items()))
        bad.append(f"S3 history.csv and the session files differ: {diff[:6]}")
    print(f"sessions {len(sessions)}, pastes {len(pastes)}, minute records {len(minutes)}, days {days[0]} to {days[-1]}")
    print(f"violations: {len(bad)} (tolerance 0)")
    for b in bad:
        print("  " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
