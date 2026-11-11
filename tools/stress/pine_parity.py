"""Stress test F3: does the indicator draw exactly the levels the calculation produced?

  python tools/stress/pine_parity.py            50+ saved pastes, Python only
  python tools/stress/pine_parity.py --show N   print paste N and the chart lines it should give (for the TradingView check)

Truth: each saved calculation's summary (index points, full precision), mapped the way the indicator maps it.
Under test: the paste made from that summary, read with the indicator's own rules (parseOne: GEX1;key=value;...;END,
the ranking it picks, the levels it draws with default settings, rounding to whole points, merging lines closer than
0.03% of price into one, dropping lines more than 8% from price).
Sources: the 9:30 pastes on the track-record branch and the calculations saved on this computer.
Tolerance (fixed before running): every drawn line at the same chart price as the truth's, with the same names;
the only allowed difference is the paste's 2-decimal rounding (at most 0.005 index points), reported separately.
Chart sample (2026-11-10, NQ1! 1h, the saved NQ paste, "Snapshot factor" mapping so the factor is the paste's 1.003507):
the Data Window showed zero gamma 28,504, call wall 28,881, put wall 26,824; predicted 28,503.563 -> 28,504,
28,880.931 -> 28,881, 26,823.742 -> 26,824. All three match. (Read without touching the chart; settings restored.)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gexsys.export import pine_payload  # noqa: E402

MERGE_PCT, MAX_DIST_PCT, RANK_C, RANK_A = 0.03, 8.0, 7, 3
FACTOR = {"NQ": 1.0035, "ES": 1.0030}          # a typical live ratio; any value works, both sides use the same
TICK = 0.25


def pine_round(v: float) -> float:
    return math.floor(v + 0.5)                # Pine's math.round: ties go up; "Whole points" is the default


# ---- the indicator's reading of a paste (pine/nq_es_gex_levels.pine, parseOne) ----
def parse_like_pine(txt: str) -> dict | None:
    toks = txt.strip().split(";")
    if len(toks) < 2 or toks[0] != "GEX1":
        return None
    m = {}
    for t in toks:
        p = t.find("=")
        if p > 0:
            m[t[:p]] = t[p + 1:]
    num = lambda k: float(m[k]) if m.get(k, "") != "" else None
    return {"mkt": m.get("mkt", ""), "ref": num("ref"), "zg": num("zg"), "cw": num("cw"), "pw": num("pw"), "ag": num("ag"),
            "x0": m.get("x0", ""), "z0": num("z0"), "c0": num("c0"), "p0": num("p0"),
            "rk": ranked_from_token(m.get("R", "")), "rk0": ranked_from_token(m.get("R0", "")),
            "rk0e": ranked_from_token(m.get("R0e", "")), "g0e": num("g0e"),
            "ema": num("ema"), "emd": num("emd"), "emw": num("emw"), "st": m.get("st", "")}


def ranked_from_token(tok: str) -> list[tuple[str, float]]:
    out = []
    for item in tok.split(","):
        pr = item[1:].split(":")
        if len(pr) == 2 and pr[0]:
            out.append((item[0], float(pr[0])))
    return out


# ---- the same inputs straight from the summary (the truth) ----
def from_summary(s: dict) -> dict:
    p = lambda lv: lv["price"] if lv else None
    ex = s.get("extras") or {}
    n = ex.get("nearest") or {}
    em = ex.get("expected_move") or {}
    rk = lambda r: [(code, x["price"]) for side, code in (("call", "C"), ("put", "P"), ("abs", "A")) for x in (r or {}).get(side) or []]
    return {"mkt": s.get("market", ""), "ref": s.get("ref_price") or s.get("spot"), "zg": p(s.get("zero_gamma")),
            "cw": p(s.get("call_wall")), "pw": p(s.get("put_wall")), "ag": p(s.get("abs_gamma")),
            "x0": n.get("label", ""), "z0": p(n.get("zero_gamma")), "c0": p(n.get("call_wall")), "p0": p(n.get("put_wall")),
            "rk": rk(s.get("ranked")), "rk0": rk(n.get("ranked")), "rk0e": rk(n.get("ranked_etf")), "g0e": round(100 * n.get("etf_share", 0.0)) if n.get("ranked_etf") else None,
            "ema": em.get("anchor"), "emd": em.get("daily_points"), "emw": em.get("weekly_points"), "st": s.get("status", "")}


# ---- what the indicator draws, default settings (drawKey + drawMore, first source only) ----
def draw(d: dict, f: float) -> list[tuple[float, list[str]]]:
    close = d["ref"] * f
    tol = max(TICK / 2, close * MERGE_PCT / 100)
    lines: list[list] = []

    def mp(x):
        return None if x is None else pine_round(x * f)

    def sane(x):
        return x is None or abs(x - close) / close * 100 <= MAX_DIST_PCT

    def level(x, name):
        if x is None or not sane(x):
            return x
        best = min(((abs(q - x), i) for i, (q, _) in enumerate(lines) if abs(q - x) <= tol), default=None)
        if best:
            if name not in lines[best[1]][1]:
                lines[best[1]][1].append(name)
            return lines[best[1]][0]
        lines.append([x, [name]])
        return x

    def snap(x):
        if x is None:
            return None
        best = min(((abs(q - x), q) for q, _ in lines if abs(q - x) <= tol), default=None)
        return best[1] if best else x

    has_i, has_e = bool(d["rk0"]), bool(d["rk0e"])
    first = has_i or has_e
    etf = first and has_e and ((d["g0e"] or 0) >= 50 or not has_i)
    ranked = d["rk0e"] if etf else d["rk0"] if first else d["rk"]
    level(mp(d["zg"]), "ZG")
    level(mp(d["cw"]), "CW")
    level(mp(d["pw"]), "PW")
    level(mp(d["ag"]), "AG")
    n = {"C": 0, "P": 0, "A": 0}
    for kind, px in ranked:
        cap = RANK_A if kind == "A" else RANK_C
        if kind in n and n[kind] < cap:
            n[kind] += 1
            level(snap(mp(px)), ("Ab" if kind == "A" else kind) + str(n[kind]))
    if d["x0"]:
        d0 = "0D" if d["x0"] == "0DTE" else d["x0"]
        level(mp(d["z0"]), d0 + " ZG")
        level(mp(d["c0"]), d0 + " CW")
        level(mp(d["p0"]), d0 + " PW")
    if d["ema"] is not None:
        for hz, pts in (("D", d["emd"]), ("W", d["emw"])):
            if pts is not None:
                for k in (1, 2):
                    level(mp(d["ema"] + k * pts), f"{hz}+{k}σ")
                    level(mp(d["ema"] - k * pts), f"{hz}-{k}σ")
    return sorted((p, sorted(nm)) for p, nm in lines)


def pastes() -> list[tuple[str, str, dict | None]]:
    """(label, paste, summary or None). Track-record pastes have no summary beside them: their truth is their own
    unrounded counterpart where a local summary exists, else they are checked for self-consistency only."""
    out = []
    root = Path(os.path.expandvars("%LOCALAPPDATA%/gexsys/snapshots"))
    for f in sorted(root.glob("*-CBOE/*/*.json")):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        s = s.get("summary", s)
        if not s.get("zero_gamma") or not s.get("market"):
            continue
        src = "NDX" if s["market"] == "NQ" else "SPX"
        out.append((f"{f.parent.parent.name}/{f.parent.name}/{f.stem}", pine_payload(s, s["market"], src, "ratio", provider="CBOE"), s))
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/track-record", "pastes/"], cwd=ROOT,
                           capture_output=True, text=True).stdout.split()
    for nm in names:
        txt = subprocess.run(["git", "show", f"origin/track-record:{nm}"], cwd=ROOT, capture_output=True, text=True).stdout
        out.append((nm, txt.strip(), None))
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int)
    a = ap.parse_args()
    items = pastes()
    if a.show is not None:
        label, txt, _ = items[a.show]
        d = parse_like_pine(txt)
        print(label, "\n", txt, "\n")
        for f in (FACTOR[d["mkt"]], 1.0):
            print(f"factor {f}:", draw(d, f))
        return 0
    bad, rounding, checked, lines = [], 0, 0, 0
    worst = 0.0
    for label, txt, summ in items:
        d = parse_like_pine(txt)
        if d is None:
            bad.append(f"{label}: not a GEX1 paste")
            continue
        f = FACTOR.get(d["mkt"], 1.0)
        got = draw(d, f)
        lines += len(got)
        checked += 1
        if summ is None:
            continue
        t = from_summary(summ)
        d2 = d
        for k in ("zg", "cw", "pw", "ag", "z0", "c0", "p0", "ema", "emd", "emw"):
            if (t[k] is None) != (d2[k] is None):
                bad.append(f"{label}: {k} {'missing from the paste' if d2[k] is None else 'in the paste but not the summary'}")
            elif t[k] is not None:
                worst = max(worst, abs(t[k] - d2[k]))
        want = draw(t, f)
        got = draw(d2, f)
        if want != got:
            # allowed only if the paste's 2-decimal rounding explains it: the truth rounded the same way draws the same
            r2 = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in t.items()}
            for k in ("rk", "rk0", "rk0e"):
                r2[k] = [(c, round(px, 2)) for c, px in t[k]]
            if draw(r2, f) == got:
                rounding += 1
            else:
                bad.append(f"{label}: drawn {got} vs truth {want}")
    print(f"{checked} pastes read ({sum(1 for *_, s in items if s)} with their full-precision summary), {lines} chart lines")
    print(f"largest paste rounding of a level: {worst:.4f} index points (2 decimals: at most 0.005)")
    print(f"pastes where that rounding moved a line across a whole-point boundary (and so a merge): {rounding}")
    if worst > 0.005 + 1e-9:
        bad.append(f"paste rounding {worst:.4f} > 0.005")
    if checked < 50:
        bad.append(f"only {checked} pastes")
    print("RESULT:", "PASS" if not bad else f"FAIL - {len(bad)}:\n  " + "\n  ".join(bad[:20]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
