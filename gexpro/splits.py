"""When does the level-reaction edge differ? Study splits v1 (studies/splits/v1.json: every split and test is there first).

  python -m gexpro.splits [--out results.json]

Each split puts sessions in groups by a fact known before 09:30 ET (regime, distance from zero gamma, VIX/VXN tercile
with trailing cutoffs, event day, weekday, opex week, 0DTE share of gamma). The value compared is the level-reaction
study's pooled real-minus-baseline reject rate (studies/level_reaction/v2.json). A split is tested only when every
group has at least 20 sessions: a permutation test over whole sessions, then Benjamini-Hochberg at q = 0.10 across the
tests run. Survivors get each group's Phase 4 interval; the rest read "no difference found".
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from gexsys import marketcal

from . import reaction_lab as L
from . import uncertainty

ROOT = Path(__file__).resolve().parent.parent
DEFINITION = ROOT / "studies" / "splits" / "v1.json"
ARCHIVE = "origin/archive"
SEED, PERMS, MIN_GROUP, Q = 20261118, 10_000, 20, 0.10          # as written in the definition (tests check the text)
NEAR = 0.5                                                      # zero-gamma distance, in expected moves
VOL_WINDOW, DTE_WINDOW, DTE_MIN = 252, 252, 60
VOL = {"NQ": "NDX", "ES": "SPX"}                                # trackrecord.prices.vol_index: VXN, VIX
SPLITS = {"regime": ["POSITIVE", "NEGATIVE"], "zg_distance": ["near", "far"], "vol_tercile": ["low", "mid", "high"],
          "event_day": ["event", "no_event"], "weekday": ["Mon", "Tue", "Wed", "Thu", "Fri"],
          "opex_week": ["opex_week", "other"], "zero_dte_tercile": ["low", "mid", "high"]}
NAMED = {"CPI": ("CPI",), "FOMC": ("FOMC", "Federal Funds Rate"), "NFP": ("Non-Farm Employment Change",), "PCE": ("PCE",)}
MARKETS = ("NQ", "ES")

Counts = tuple[int, int, int, int]       # (real rejects, real touches, baseline rejects, baseline touches)


def definition() -> tuple[dict, str]:
    raw = DEFINITION.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------- the split inputs (each known before 09:30 ET)
def tercile(v: float, history: list[float], need: int) -> Optional[str]:
    if len(history) < need:
        return None
    xs = sorted(history)
    q1, q2 = uncertainty._quantile(xs, 1 / 3), uncertainty._quantile(xs, 2 / 3)
    return "low" if v <= q1 else "mid" if v <= q2 else "high"


def vol_label(d: date, closes: dict[str, float]) -> tuple[Optional[str], str]:
    prev = marketcal.previous_trading_day(d).isoformat()
    if prev not in closes:
        return None, "no vol-index close for the previous trading day"
    hist = [closes[k] for k in sorted(k for k in closes if k <= prev)][-VOL_WINDOW:]
    g = tercile(closes[prev], hist, VOL_WINDOW)
    return g, "" if g else f"fewer than {VOL_WINDOW} earlier closes"


def zg_label(plan: dict) -> tuple[Optional[str], str]:
    if plan.get("zg") is None or not plan.get("em") or plan.get("ref") is None:
        return None, "the plan has no zero gamma"
    return ("near" if abs(plan["ref"] - plan["zg"]) / plan["em"] < NEAR else "far"), ""


def _et_day(iso: str) -> date:
    return datetime.fromisoformat(iso).astimezone(marketcal.NY).date()


def event_label(d: date, cal: Optional[dict]) -> tuple[Optional[str], str, list[str]]:
    """(event | no_event | None, why unavailable, named releases) from the calendar copy fetched before 09:30."""
    if not cal:
        return None, "no calendar copy saved before that day's 09:30", []
    sunday = d - timedelta(days=(d.weekday() + 1) % 7)
    days = {_et_day(e["time"]) for e in cal.get("events", []) if e.get("time")}
    if not any(sunday <= x <= sunday + timedelta(days=6) for x in days):
        return None, "the saved calendar is for another week", []
    hits = [e for e in cal["events"] if e.get("country") == "USD" and e.get("impact") == "High" and _et_day(e["time"]) == d]
    named = sorted({n for n, keys in NAMED.items() for e in hits if any(k in e.get("title", "") for k in keys)})
    return ("event" if hits else "no_event"), "", named


def opex_label(d: date) -> str:
    x = marketcal.quarterly_expiry(d.year, d.month)          # any month: the third Friday, holiday-adjusted
    return "opex_week" if d - timedelta(days=d.weekday()) == x - timedelta(days=x.weekday()) else "other"


def zero_dte_share(snap: dict) -> Optional[float]:
    b = snap.get("by_dte_bucket") or {}
    total = sum((v or {}).get("abs") or 0 for v in b.values())
    return ((b.get("0DTE") or {}).get("abs") or 0) / total if total else None


def dte_labels(shares: dict[str, float]) -> dict[str, tuple[Optional[str], str]]:
    """{date: label} with cutoffs from up to 252 earlier sessions' shares (at least 60)."""
    out, ds = {}, sorted(shares)
    for i, d in enumerate(ds):
        g = tercile(shares[d], [shares[x] for x in ds[max(0, i - DTE_WINDOW):i]], DTE_MIN)
        out[d] = (g, "" if g else f"fewer than {DTE_MIN} earlier archived sessions")
    return out


def labels(s: dict, closes: dict[str, float], cal: Optional[dict], dte: dict[str, tuple]) -> dict[str, tuple]:
    """{split: (group or None, why unavailable, extra)} for one session."""
    d = date.fromisoformat(s["session"])
    ev = event_label(d, cal)
    return {"regime": ((s["regime"], "", None) if s["regime"] in SPLITS["regime"] else (None, f"regime {s['regime']}", None)),
            "zg_distance": (*zg_label(s.get("plan") or {}), None),
            "vol_tercile": (*vol_label(d, closes), None),
            "event_day": (ev[0], ev[1], ev[2]),
            "weekday": (SPLITS["weekday"][d.weekday()], "", None),
            "opex_week": (opex_label(d), "", None),
            "zero_dte_tercile": (*dte.get(s["session"], (None, "no archived 09:30 snapshot for that day")), None)}


# ---------------------------------------------------------------- the test
def counts(real: list[dict], rand: list[dict]) -> dict[tuple[str, str], Counts]:
    """Per (session, market), pooled over level types: the level-reaction study's counted touches."""
    out: dict = {}
    for rows, k in ((real, 0), (rand, 2)):
        for r in L.counted(rows):
            c = out.setdefault((r["session"], r["market"]), [0, 0, 0, 0])
            c[k] += r["outcome"] == "reject"
            c[k + 1] += 1
    return {k: tuple(v) for k, v in out.items()}


def statistic(groups: list[list[Counts]]) -> Optional[float]:
    """sum n_g (d_g - d_bar)^2 with n_g sessions; None when a group has no real or no baseline touch."""
    ds, ns = [], []
    for g in groups:
        d = uncertainty.diff(g)
        if d is None:
            return None
        ds.append(d)
        ns.append(len(g))
    bar = sum(n * d for n, d in zip(ns, ds)) / sum(ns)
    return sum(n * (d - bar) ** 2 for n, d in zip(ns, ds))


def permutation_p(groups: list[list[Counts]], perms: int, seed: int) -> Optional[float]:
    obs = statistic(groups)
    if obs is None:
        return None
    pool = [s for g in groups for s in g]
    sizes = [len(g) for g in groups]
    rng, hits, used = random.Random(seed), 0, 0
    for _ in range(perms):
        rng.shuffle(pool)
        parts, i = [], 0
        for n in sizes:
            parts.append(pool[i:i + n])
            i += n
        st = statistic(parts)
        if st is None:
            continue
        used += 1
        hits += st >= obs - 1e-12
    return (1 + hits) / (used + 1) if used >= 0.9 * perms else None


def bh(pvals: dict[str, float], q: float = Q) -> set[str]:
    """Benjamini-Hochberg: the tests with p at or below the largest p_(k) <= k q / m."""
    ranked = sorted(pvals.items(), key=lambda kv: kv[1])
    m, cut = len(ranked), 0
    for k, (_, p) in enumerate(ranked, 1):
        if p <= k * q / m:
            cut = k
    return {name for name, _ in ranked[:cut]}


# ---------------------------------------------------------------- the study
def run(sessions: list[dict], c: dict[tuple[str, str], Counts], closes: dict[str, dict[str, float]],
        calendars: dict[str, dict], dte: dict[str, dict[str, tuple]], perms: int = PERMS) -> dict:
    d, sha = definition()
    tests, pvals = [], {}
    lab = {(s["session"], s["market"]): labels(s, closes.get(s["market"], {}), calendars.get(s["session"]), dte.get(s["market"], {}))
           for s in sessions}
    for i, (split, m) in enumerate((sp, mk) for sp in SPLITS for mk in MARKETS):      # the definition's order
        groups = SPLITS[split]
        ss = [s for s in sessions if s["market"] == m]
        by: dict[str, list] = {g: [] for g in groups}
        why, named, roll = Counter(), Counter(), 0
        for s in ss:
            g, reason, extra = lab[(s["session"], m)][split]
            if g is None:
                why[reason] += 1
                continue
            by[g].append(c.get((s["session"], m), (0, 0, 0, 0)))
            roll += s["roll_week"]
            named.update(extra or [])
        t = {"id": f"{split}:{m}", "split": split, "market": m, "seed": SEED + i,
             "groups": {g: {"sessions": len(v), "difference": None if uncertainty.diff(v) is None else round(uncertainty.diff(v), 4)}
                        for g, v in by.items()},
             "unavailable": dict(why), "roll_week_sessions": roll}
        if named:
            t["named_events"] = dict(named)
        if min(len(v) for v in by.values()) < MIN_GROUP:
            t["status"] = "not enough data"                   # n only: a difference over a few sessions is noise
            for v in t["groups"].values():
                del v["difference"]
        else:
            p = permutation_p(list(by.values()), perms, SEED + i)
            t["status"], t["p_value"] = ("tested", round(p, 4)) if p is not None else ("unavailable", None)
            if p is not None:
                pvals[t["id"]] = p
            t["_by"] = by
        tests.append(t)
    keep = bh(pvals)
    for t in tests:
        by = t.pop("_by", None)
        if t["status"] == "tested":
            t["survives"] = t["id"] in keep
            t["verdict"] = "difference found" if t["survives"] else "no difference found"
            if t["survives"]:
                for g, v in by.items():
                    t["groups"][g].update(uncertainty.summarize(v))
    return {"study": d["study"], "version": d["version"], "definition_sha256": sha, "seed": SEED, "permutations": perms,
            "q": Q, "registered": len(tests), "tested": len(pvals), "survivors": sorted(keep),
            "sessions": {m: sum(s["market"] == m for s in sessions) for m in MARKETS},
            "data_from": min(s["session"] for s in sessions), "data_through": max(s["session"] for s in sessions),
            "tests": tests}


def read_archive(files: Optional[dict] = None) -> tuple[dict[str, dict], dict[str, dict[str, float]]]:
    """({date: calendar copy}, {market: {date: 0DTE share}}) from the archive branch."""
    files = L.read_branch(ARCHIVE, lambda f: f.endswith(("/calendar.json", "/NQ-open.json", "/ES-open.json"))) \
        if files is None else files
    cals, shares = {}, {m: {} for m in MARKETS}
    for f, b in files.items():
        _, d, name = f.split("/")
        if name == "calendar.json":
            cals[d] = json.loads(b)
        else:
            sh = zero_dte_share(json.loads(b))
            if sh is not None:
                shares[name.split("-")[0]][d] = sh
    return cals, shares


def main(argv=None) -> int:
    import argparse
    from trackrecord import prices
    ap = argparse.ArgumentParser(prog="gexpro.splits")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    sessions = L.load()
    rules = L.definition()[0]["rules"]
    real = [r for s in sessions for r in L.session_levels(s, rules)]
    rand = L.baseline(sessions, real, rules, L.DRAWS, L.SEED)
    cals, shares = read_archive()
    closes = {m: prices.vol_index(u) for m, u in VOL.items()}
    res = run(sessions, counts(real, rand), closes, cals, {m: dte_labels(v) for m, v in shares.items()})
    print(f"splits v{res['version']}  definition sha256 {res['definition_sha256']}  seed {res['seed']}")
    print(f"sessions NQ {res['sessions']['NQ']}, ES {res['sessions']['ES']} ({res['data_from']} to {res['data_through']}); "
          f"registered {res['registered']}, tested {res['tested']}, survivors {len(res['survivors'])} (BH q={res['q']})")
    for t in res["tests"]:
        gs = "  ".join(f"{g} {v['sessions']}" + ("" if v.get("difference") is None else f" ({v['difference']:+.3f})")
                       for g, v in t["groups"].items())
        extra = f"  p={t['p_value']}" if t.get("p_value") is not None else ""
        un = f"  unavailable {sum(t['unavailable'].values())}: {next(iter(t['unavailable']))}" if t["unavailable"] else ""
        print(f"{t['id']:22} {t.get('verdict', t['status']):20}{extra}  {gs}{un}")
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
