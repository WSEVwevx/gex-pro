"""Level-reaction lab, study level_reaction v2 (studies/level_reaction/v2.json: every rule is defined there first;
v2 = v1's rules with Phase 4's statistics, gexpro/uncertainty.py).

  python -m gexpro.reaction_lab [--out results.json]

When price first reaches a 09:30 level during the cash session, is it rejected more often than at a random level the
same distance from the open? Inputs come only from the public track record (git branch track-record): the frozen
plan (sessions/), the 09:30 paste (pastes/) and the 1-minute futures record (minutes/), all checked for look-ahead by
tools/stress/lookahead_audit.py. Levels are mapped to futures with that morning's 09:30 ratio, one per session.
The result carries the definition file's SHA-256, the seed and the data-through date.
"""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from gexsys import marketcal

from . import uncertainty

ROOT = Path(__file__).resolve().parent.parent
DEFINITION = ROOT / "studies" / "level_reaction" / "v2.json"
BRANCH = "origin/track-record"
TYPES = ["ZG", "CW", "PW", "Ab1", "C1", "C2", "C3", "P1", "P2", "P3"]      # also the cluster order
PLAN_KEY = {"ZG": "zg", "CW": "cw", "PW": "pw", "Ab1": "ag"}
HORIZONS = (15, 30, 60)
SEED, DRAWS, REPS = 20261118, 1000, uncertainty.REPS      # as written in the definition (test_reaction_lab checks)
BUCKETS = (("09:30-10:30", time(10, 30)), ("10:30-15:00", time(15, 0)), ("15:00-close", time(23, 59)))


def definition() -> tuple[dict, str]:
    raw = DEFINITION.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------- inputs
def paste_levels(text: str) -> dict[str, float]:
    """C1-C3 and P1-P3: the first three C and P entries of the paste's R token, in the order written."""
    tok = dict(t.split("=", 1) for t in text.strip().split(";") if "=" in t)
    out, n = {}, {"C": 0, "P": 0}
    for e in (tok.get("R") or "").split(","):
        kind, rest = e[:1], e[1:]
        if kind in n and n[kind] < 3 and rest:
            n[kind] += 1
            out[f"{kind}{n[kind]}"] = float(rest.split(":")[0])
    return out


def session_input(sess: dict, minutes: dict, paste: Optional[str], prev_close: Optional[float]) -> dict:
    """Everything one session's replay uses, in futures points (one 09:30 ratio)."""
    plan, r = sess["plan"], minutes["ratio"]
    levels = {t: plan[k] for t, k in PLAN_KEY.items() if plan.get(k) is not None}
    if paste:
        levels.update(paste_levels(paste))
    d = date.fromisoformat(sess["session"])
    return {"session": sess["session"], "market": sess["market"], "regime": plan.get("regime"), "ratio": r,
            "open": minutes["index_open"] * r, "em": plan["em"] * r,
            "prev_close": None if prev_close is None else prev_close * r,
            "levels": {t: v * r for t, v in levels.items()}, "has_paste": bool(paste),
            "bars": minutes["bars"], "close_min": minutes.get("close_min", 390),
            "roll_week": _roll_week(d)}


def _roll_week(d: date) -> bool:
    m = ((d.month - 1) // 3 + 1) * 3
    return marketcal.roll_date(d.year, m) <= d <= marketcal.quarterly_expiry(d.year, m)


def read_branch(branch: str = BRANCH) -> dict[str, bytes]:
    """{path: bytes} of the track record's sessions, minutes and pastes, read with one git process."""
    git = lambda *a, **k: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, **k).stdout
    git("fetch", "-q", "origin", "track-record")
    paths = [f for f in git("ls-tree", "-r", "--name-only", branch).decode().split()
             if f.startswith(("sessions/", "minutes/", "pastes/"))]
    out, buf = {}, git("cat-file", "--batch", input="".join(f"{branch}:{f}\n" for f in paths).encode())
    for f in paths:                                     # each answer: "<sha> blob <size>\n<bytes>\n"
        head, buf = buf.split(b"\n", 1)
        size = int(head.split()[2])
        out[f], buf = buf[:size], buf[size + 1:]
    return out


def load(branch: str = BRANCH, files: Optional[dict] = None, skipped: Optional[list] = None) -> list[dict]:
    """Every graded session with a 1-minute record and an expected move, oldest first. Sessions left out, and sessions
    whose previous trading day has no graded close (all their levels: no_prior_close), are named in `skipped`."""
    files = read_branch(branch) if files is None else files
    skipped = [] if skipped is None else skipped
    graded = {}
    for f in sorted(x for x in files if x.startswith("sessions/")):
        s = json.loads(files[f])
        if s.get("status") == "graded":
            graded[(s["session"], s["market"])] = s
    out = []
    for (d, m), s in sorted(graded.items()):
        name = f"{d}_{m}"
        if f"minutes/{name}.json" not in files:
            skipped.append(f"{name}: no 1-minute record")
            continue
        if not (s.get("plan") or {}).get("em"):
            skipped.append(f"{name}: the plan has no expected move")
            continue
        prev = graded.get((marketcal.previous_trading_day(date.fromisoformat(d)).isoformat(), m))
        if prev is None:
            skipped.append(f"{name}: the previous trading day has no graded close (levels counted as no_prior_close)")
        paste = files[f"pastes/{name}.txt"].decode() if f"pastes/{name}.txt" in files else None
        out.append(session_input(s, json.loads(files[f"minutes/{name}.json"]), paste,
                                 prev["outcome"]["close"] if prev else None))
    return out


# ---------------------------------------------------------------- one level
def tol_of(s: dict, rules: dict) -> float:
    return max(2 * rules["tick"][s["market"]], 0.05 * s["em"])


def bucket(minute: int) -> str:
    t = (datetime.combine(date(2000, 1, 1), marketcal.RTH_OPEN) + timedelta(minutes=minute)).time()
    return next(name for name, end in BUCKETS if t < end)


def classify(level: float, s: dict, rules: dict) -> dict:
    """One level's category and, for a touch, its outcome (the definition's rules, applied literally)."""
    tol, k, o, bars = tol_of(s, rules), rules["k"], s["open"], s["bars"]
    if abs(level - o) <= tol:
        return {"cat": "at_open"}
    if s["prev_close"] is None:
        return {"cat": "no_prior_close"}
    if min(s["prev_close"], o) < level < max(s["prev_close"], o):
        return {"cat": "gap_through"}
    up = level > o
    i = next((i for i, b in enumerate(bars) if (b[1] >= level - tol if up else b[2] <= level + tol)), None)
    if i is None:
        return {"cat": "untouched", "side": "above" if up else "below"}
    m0, last = bars[i][0], bars[-1][0]
    res, when = "stall", None
    for j in range(i, len(bars)):
        m, h, lo, c = bars[j]
        if m - m0 > 60:
            break
        if (c > level + tol) if up else (c < level - tol):
            res, when = "break", m - m0                     # same bar as a reject: a break (the worse case)
            break
        if j > i and ((lo <= level - k * tol) if up else (h >= level + k * tol)):
            res, when = "reject", m - m0
            break
    exc = {}
    for hz in HORIZONS:
        if m0 + hz > last:
            exc[hz] = None                                  # runs past the close: not reported
            continue
        w = [b for b in bars[i:] if b[0] <= m0 + hz]
        away = (level - min(b[2] for b in w)) if up else (max(b[1] for b in w) - level)
        thru = (max(b[1] for b in w) - level) if up else (level - min(b[2] for b in w))
        exc[hz] = {"away": round(away, 2), "through": round(thru, 2),
                   "away_em": round(away / s["em"], 4), "through_em": round(thru / s["em"], 4)}
    return {"cat": "touch", "side": "above" if up else "below", "minute": m0, "bucket": bucket(m0),
            "outcome": res, "minutes_to_resolution": when, "excursions": exc}


def session_levels(s: dict, rules: dict, shift: float = 0.0) -> list[dict]:
    """Every real level of one session, classified, with the cluster rule (later members within tol: dependent)."""
    tol, out, seen = tol_of(s, rules), [], []
    for t in TYPES:
        if t not in s["levels"]:
            continue
        lv = s["levels"][t] + shift
        r = dict(classify(lv, s, rules), type=t, level=round(lv, 2), session=s["session"], market=s["market"],
                 regime=s["regime"], roll_week=s["roll_week"])
        if any(abs(lv - x) <= tol for x in seen):
            r["dependent"] = True
        seen.append(lv)
        out.append(r)
    return out


# ---------------------------------------------------------------- baseline
def baseline(sessions: list[dict], real: list[dict], rules: dict, n: int, seed: int) -> list[dict]:
    """n random levels per market x type: a session where that type exists, a real distance (in expected moves, side
    included) of that type and market, the same rules; redrawn when within tol of a real level of that session."""
    rng = random.Random(seed)
    out = []
    by_key = {(s["session"], s["market"]): s for s in sessions}
    for m in sorted({s["market"] for s in sessions}):
        for t in TYPES:
            ss = [s for s in sessions if s["market"] == m and t in s["levels"]]
            dist = [(s["levels"][t] - s["open"]) / s["em"] for s in ss]
            if not ss:
                continue
            got = tries = 0
            while got < n and tries < 100 * n:                  # every draw on a real level (e.g. one session): stop, fewer drawn
                tries += 1
                s, d = rng.choice(ss), rng.choice(dist)
                lv = s["open"] + d * s["em"]
                if any(abs(lv - x) <= tol_of(s, rules) for x in by_key[(s["session"], m)]["levels"].values()):
                    continue
                out.append(dict(classify(lv, s, rules), type=t, level=round(lv, 4), session=s["session"], market=m,
                                regime=s["regime"], roll_week=s["roll_week"], random=True))
                got += 1
    return out


# ---------------------------------------------------------------- statistics
def counted(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["cat"] == "touch" and not r.get("dependent")]


def rate(rows: list[dict]) -> Optional[float]:
    t = counted(rows)
    return sum(r["outcome"] == "reject" for r in t) / len(t) if t else None


def per_session(real: list[dict], rand: list[dict]) -> list[tuple[int, int, int, int]]:
    """(real rejects, real touches, baseline rejects, baseline touches) per session that has real levels in the cell."""
    out = []
    for d in sorted({r["session"] for r in real}):
        rt = [r for r in counted(real) if r["session"] == d]
        bt = [r for r in counted(rand) if r["session"] == d]
        out.append((sum(r["outcome"] == "reject" for r in rt), len(rt), sum(r["outcome"] == "reject" for r in bt), len(bt)))
    return out


def cell(real: list[dict], rand: list[dict], st: dict, seed: int, reps: int) -> dict:
    t, sessions = counted(real), len({r["session"] for r in real})
    out = {"sessions": sessions, "levels": len(real), "touches": len(t),
           "categories": {c: sum(r["cat"] == c for r in real) for c in ("touch", "untouched", "gap_through", "at_open", "no_prior_close")},
           "dependent": sum(bool(r.get("dependent")) for r in real),
           "outcomes": {o: sum(r["outcome"] == o for r in t) for o in ("reject", "break", "stall")},
           "baseline_touches": len(counted(rand))}
    if len(t) < st["min_n"]:
        return dict(out, small=True)
    ss = per_session(real, rand)              # baseline restricted to the sessions that have this level (paired)
    bn = sum(s[3] for s in ss)
    out.update(reject=round(rate(real), 4), baseline=round(sum(s[2] for s in ss) / bn, 4) if bn else None)
    out.update(uncertainty.summarize(ss, reps, seed))     # difference = reject - baseline; interval, p-value, power
    return out


def run(sessions: list[dict], shift_pts: Optional[dict] = None, reps: Optional[int] = None,
        skipped: Optional[list] = None) -> dict:
    """The whole study (and, with shift_pts {market: points}, the shifted-levels robustness run)."""
    d, sha = definition()
    rules, st = d["rules"], d["statistics"]
    seed, n = SEED, DRAWS
    reps = reps or REPS
    shifted = [dict(s, levels={t: v + (shift_pts or {}).get(s["market"], 0.0) for t, v in s["levels"].items()}) for s in sessions]
    real = [r for s in shifted for r in session_levels(s, rules)]
    rand = baseline(shifted, real, rules, n, seed)
    table = []
    for m in sorted({s["market"] for s in sessions}):
        for t in TYPES:
            R = [r for r in real if r["market"] == m and r["type"] == t]
            if not R:
                continue
            B = [r for r in rand if r["market"] == m and r["type"] == t]
            row = {"market": m, "type": t, "all": cell(R, B, st, seed, reps),
                   "no_roll_weeks": cell([r for r in R if not r["roll_week"]], [r for r in B if not r["roll_week"]], st, seed, reps),
                   "by_regime": {g: cell([r for r in R if r["regime"] == g], [r for r in B if r["regime"] == g], st, seed, reps)
                                 for g in sorted({r["regime"] for r in R})},
                   "by_time": {b: cell([r for r in R if r.get("bucket") == b], [r for r in B if r.get("bucket") == b], st, seed, reps)
                               for b, _ in BUCKETS}}
            table.append(row)
    return {"study": d["study"], "version": d["version"], "definition_sha256": sha, "seed": seed, "baseline_per_type": n,
            "bootstrap_reps": reps, "shift_pts": shift_pts or {}, "sessions": len(sessions),
            "data_from": min(s["session"] for s in sessions), "data_through": max(s["session"] for s in sessions),
            "roll_week_sessions": sum(s["roll_week"] for s in sessions), "skipped": skipped or [], "table": table,
            "levels": real}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="gexpro.reaction_lab")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    skipped: list = []
    sessions = load(skipped=skipped)
    res = {"main": run(sessions, skipped=skipped), "shift_up": run(sessions, {"NQ": 5.0, "ES": 1.0}), "shift_down": run(sessions, {"NQ": -5.0, "ES": -1.0})}
    m = res["main"]
    print(f"level_reaction v{m['version']}  definition sha256 {m['definition_sha256']}  seed {m['seed']}")
    print(f"{m['sessions']} sessions ({m['data_from']} to {m['data_through']}), roll-week sessions {m['roll_week_sessions']}")
    for x in m["skipped"]:
        print("  note: " + x)
    print(f"{'mkt':4}{'type':5}{'sess':>5}{'lvls':>5}{'touch':>6}{'rej':>5}{'brk':>5}{'stl':>5}  {'real':>6} {'base':>6} {'diff':>7}  interval        +5/+1   -5/-1")
    alt = {k: {(r['market'], r['type']): r['all'] for r in res[k]['table']} for k in ("shift_up", "shift_down")}
    for r in m["table"]:
        c = r["all"]
        def show(x):
            return "n<20" if x.get("small") else "n/a" if "unavailable" in x else f"{x['difference']:+.3f}"
        if c.get("small"):
            mid = f"  {'n<20':>6} {'':>6} {'':>7}  {'':14}"
        elif "unavailable" in c:
            mid = f"  {c['reject']:6.3f} {'':>6} {'':>7}  {'unavailable':14}"
        else:
            mid = f"  {c['reject']:6.3f} {c['baseline']:6.3f} {c['difference']:+7.3f}  {str(c['interval']):14}"
        print(f"{r['market']:4}{r['type']:5}{c['sessions']:5}{c['levels']:5}{c['touches']:6}{c['outcomes']['reject']:5}"
              f"{c['outcomes']['break']:5}{c['outcomes']['stall']:5}{mid}  {show(alt['shift_up'][(r['market'], r['type'])]):>6}  "
              f"{show(alt['shift_down'][(r['market'], r['type'])]):>6}")
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
