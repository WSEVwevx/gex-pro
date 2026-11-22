"""Study weekend_move: with the market closed, calendar days on the backup's vol curve (A) or one VIX1D session (B)?

  python tools/stress/weekend_move.py

Definition: studies/weekend_move/v1.json (written and committed before any result; its SHA-256 is printed).
Inputs: studies/weekend_move/inputs.csv, frozen daily closes, checked against the hash in the definition.
Nothing here is used by the site.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gexsys import marketcal  # noqa: E402
from gexsys.providers.occ import curve_iv  # noqa: E402

DIR = ROOT / "studies" / "weekend_move"
INDEXES, TARGET, Z = ("SPX", "NDX"), 0.682689, 1.959964
LAUNCH = date(2023, 4, 24)                                  # VIX1D; earlier values are back-calculated
CURVE = (("VIX1D", 1.0), ("VIX9D", 9.0), ("VIX", 30.0), ("VIX3M", 93.0))
FIRST, LAST = date(2022, 5, 13), date(2026, 11, 20)


def definition() -> tuple[dict, str]:
    b = (DIR / "v1.json").read_bytes()
    return json.loads(b), hashlib.sha256(b).hexdigest()


def read_inputs(d: dict) -> dict[date, dict]:
    b = (DIR / d["inputs"]["file"]).read_bytes()
    if hashlib.sha256(b).hexdigest() != d["inputs"]["sha256"]:
        raise ValueError("inputs.csv is not the file named in the definition")
    return {date.fromisoformat(r["date"]): {k: float(v) for k, v in r.items() if k != "date" and v}
            for r in csv.DictReader(b.decode().splitlines())}


def next_trading_day(d: date) -> date:
    n = d + timedelta(days=1)
    while not marketcal.is_trading_day(n):
        n += timedelta(days=1)
    return n


def close_time(d: date) -> datetime:
    return datetime.combine(d, marketcal.rth_close(d), marketcal.NY)


def calendar_days(d: date, n: date) -> float:
    # to UTC first: two times in the same zone subtract by the wall clock and would miss the DST hour
    a, b = (close_time(x).timestamp() for x in (d, n))
    return (b - a) / 86400


def sigmas(row: dict, index: str, t_days: float) -> tuple[float, float]:
    """(A, B): sigma of the close-to-close log return, from one day's vol closes."""
    scale = row["VXN"] / row["VIX"] if index == "NDX" else 1.0
    pts = [(days, scale * row[n] / 100) for n, days in CURVE]
    return curve_iv(pts, t_days) * math.sqrt(t_days / 365), scale * row["VIX1D"] / 100 / math.sqrt(252)


def pairs(rows: dict[date, dict], index: str, first: date = FIRST, last: date = LAST) -> tuple[list[dict], int]:
    out, dropped, d = [], 0, first
    while d < last:
        n = next_trading_day(d)
        if marketcal.is_trading_day(d) and n <= last:
            a, b = rows.get(d, {}), rows.get(n, {})
            if index not in a or index not in b or any(x not in a for x in ("VIX1D", "VIX9D", "VIX", "VIX3M", "VXN")):
                dropped += 1
            else:
                t = calendar_days(d, n)
                sa, sb = sigmas(a, index, t)
                r = math.log(b[index] / a[index])
                la, lb = (r * r / (s * s) + math.log(s * s) for s in (sa, sb))
                out.append({"d": d, "n": n, "gap": (n - d).days, "t": t, "r": r, "a": sa, "b": sb, "diff": la - lb,
                            "early": any(x in marketcal.early_closes(x.year) for x in (d, n)), "roll": marketcal.roll_week(n)})
        d += timedelta(days=1)
    return out, dropped


def group(ps: list[dict], name: str) -> list[dict]:
    if name == "early":
        return [p for p in ps if p["early"]]
    ok = {"primary": lambda g: g >= 3, "ordinary": lambda g: g == 1, "two_day": lambda g: g == 2}[name]
    return [p for p in ps if not p["early"] and ok(p["gap"])]


def mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs)


def interval(ps: list[dict], seed: int, draws: int) -> tuple[float, float]:
    """95% percentile interval of the mean difference; whole ISO weeks of d are drawn with replacement."""
    wk: dict[tuple, list[float]] = {}
    for p in ps:
        wk.setdefault(tuple(p["d"].isocalendar()[:2]), []).append(p["diff"])
    tot = [(sum(wk[k]), len(wk[k])) for k in sorted(wk)]
    rng, m, out = random.Random(seed), len(tot), []
    for _ in range(draws):
        pick = [tot[rng.randrange(m)] for _ in range(m)]
        out.append(sum(s for s, _ in pick) / sum(c for _, c in pick))
    out.sort()
    return out[draws // 40 - 1], out[draws - draws // 40 - 1]


def wilson(k: int, n: int) -> tuple[float, float]:
    p, c = k / n, 1 + Z * Z / n
    mid, half = (p + Z * Z / (2 * n)) / c, Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / c
    return mid - half, mid + half


def stats(ps: list[dict], seed: int, draws: int) -> dict:
    n, out = len(ps), {"n": len(ps)}
    if not n:
        return out
    out["diff"] = mean(p["diff"] for p in ps)
    out["ci"] = interval(ps, seed, draws)
    for s in "ab":
        k = sum(abs(p["r"]) <= p[s] for p in ps)
        out[s] = {"inside": k, "share": k / n, "wilson": wilson(k, n), "ratio": mean(p["r"] ** 2 / p[s] ** 2 for p in ps)}
    return out


def conditions(ps: list[dict], seed: int, draws: int) -> dict[str, bool]:
    prim, ordi = group(ps, "primary"), group(ps, "ordinary")
    s, o = stats(prim, seed, draws), stats(ordi, seed, draws)
    late = sorted(prim, key=lambda p: p["d"])[len(prim) // 2:]          # the last ceil(n / 2)
    return {"1 primary interval above 0": s["ci"][0] > 0, "2 later half above 0": mean(p["diff"] for p in late) > 0,
            "3 coverage closer to 68.3%": abs(s["b"]["share"] - TARGET) < abs(s["a"]["share"] - TARGET),
            "4 ordinary interval not all below 0": not o["ci"][1] < 0}


def line(name: str, s: dict) -> str:
    if not s["n"]:
        return f"  {name:26s} n    0"

    def one(x):
        return f"{x['inside']}/{s['n']} {100 * x['share']:.1f}% ({100 * x['wilson'][0]:.1f}-{100 * x['wilson'][1]:.1f}) r2/s2 {x['ratio']:.4f}"
    return f"  {name:26s} n {s['n']:4d}  A-B {s['diff']:+.4f} [{s['ci'][0]:+.4f}, {s['ci'][1]:+.4f}]  A {one(s['a'])}  B {one(s['b'])}"


def main() -> int:
    d, sha = definition()
    seed, draws = d["test"]["seed"], d["test"]["draws"]
    rows, verdicts = read_inputs(d), {}
    print(f"weekend_move v{d['version']}  definition sha256 {sha}")
    print(f"inputs sha256 {d['inputs']['sha256']}  seed {seed}  draws {draws}")
    for ix in INDEXES:
        ps, dropped = pairs(rows, ix)
        prim, ordi = group(ps, "primary"), group(ps, "ordinary")
        half = len(prim) // 2
        print(f"{ix}: {len(ps)} pairs {ps[0]['d']} to {ps[-1]['n']}, {dropped} dropped")
        for name, g in (("primary (gap >= 3)", prim), ("ordinary (gap 1)", ordi), ("two-day", group(ps, "two_day")),
                        ("early close", group(ps, "early")), ("primary, earlier half", prim[:half]), ("primary, later half", prim[half:]),
                        ("primary, before launch", [p for p in prim if p["d"] < LAUNCH]), ("primary, since launch", [p for p in prim if p["d"] >= LAUNCH]),
                        ("primary, roll weeks", [p for p in prim if p["roll"]]), ("primary, other weeks", [p for p in prim if not p["roll"]]),
                        ("ordinary, before launch", [p for p in ordi if p["d"] < LAUNCH]), ("ordinary, since launch", [p for p in ordi if p["d"] >= LAUNCH]),
                        ("ordinary, roll weeks", [p for p in ordi if p["roll"]]), ("ordinary, other weeks", [p for p in ordi if not p["roll"]])):
            print(line(name, stats(g, seed, draws)))
        verdicts[ix] = conditions(ps, seed, draws)
        for k, v in verdicts[ix].items():
            print(f"  {'PASS' if v else 'FAIL'} {k}")
    better = all(v for c in verdicts.values() for v in c.values())
    print("VERDICT:", "B is better" if better else "no edge found; rule A stays")
    return 0


if __name__ == "__main__":
    sys.exit(main())
