"""Stress test D3: is the level-reaction study (trackrecord/reactions.py) sound?

  python tools/stress/reaction_null.py [--runs 1000] [--sessions 30] [--edge 0.15]

NULL: each run builds `sessions` random-walk days (1-minute bars, 09:30-16:00, sigma = expected move / sqrt(390)
per minute) and puts "levels" at random strikes. Real levels and random strikes are then exchangeable, so
the true edge is exactly zero, and any "edge" verdict is a false positive.
  per-verdict rate     how often one verdict (one level type, one horizon) claims an edge   tolerance <= 5%
  page rate            how often ANY verdict on the page (every type x horizon) claims one  reported
PLANTED: the same, but at a real level's first touch price is turned back with probability `edge` (a
genuine extra bounce), then left to random-walk. Reports the realised extra bounce rate and how often
the study detects it, for several sample sizes.
Tolerances are fixed before running.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from trackrecord import reactions as R  # noqa: E402

OPEN, EM, GRID = 20000.0, 400.0, 10.0
TYPES = ["cw", "pw", "zg"]                      # three level types, two levels each per day


def day(rng: random.Random, levels: list[float], edge: float) -> list[list]:
    """390 one-minute bars [m, high, low, close]; at a level's first touch, with probability `edge`, price
    is turned back (a real bounce) by drifting away from it for 30 minutes."""
    sd = EM / math.sqrt(390)
    p, bars, pending = OPEN, [], {L: (1 if L > OPEN else -1) for L in levels}
    drift, drift_left = 0.0, 0
    for m in range(390):
        q = p + rng.gauss(0, sd) + (drift if drift_left > 0 else 0.0)
        drift_left -= 1
        hi, lo = max(p, q) + abs(rng.gauss(0, sd * 0.3)), min(p, q) - abs(rng.gauss(0, sd * 0.3))
        for L, side in list(pending.items()):
            if (hi >= L - R.TOUCH * EM) if side > 0 else (lo <= L + R.TOUCH * EM):
                del pending[L]
                if edge and rng.random() < edge:
                    q = L - side * sd                          # turned at the level
                    hi, lo = (max(p, L), min(p, q)) if side > 0 else (max(p, q), min(p, L))
                    drift, drift_left = -side * EM * 0.3 / 30, 30
        bars.append([m, round(hi, 2), round(lo, 2), round(q, 2)])
        p = q
    return bars


def one_run(args) -> dict:
    seed, sessions, edge = args
    rng = random.Random(seed)
    recs, levels = [], {}
    for i in range(sessions):
        s = f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}"
        lv = []
        for t in TYPES:
            for _ in range(2):
                d = rng.choice([-1, 1]) * rng.uniform(0.05, 0.8) * EM
                lv.append((t, round((OPEN + d) / GRID) * GRID))
        recs.append({"session": s, "market": "NQ", "underlying": "NDX", "index_open": OPEN, "ratio": 1.0, "em": EM,
                     "close_min": 390, "bars": day(rng, [p for _, p in lv], edge)})
        levels[(s, "NQ")] = lv
    obs = R.observations(recs, levels)
    res = R.summarize(obs, seed=seed)
    out = {"verdicts": [], "bounce_real": [], "bounce_rand": []}
    for t in res["types"]:
        if t["type"] not in TYPES:
            continue
        for hz, c in t["h"].items():
            out["verdicts"].append((t["type"], hz, c["verdict"], c["touches"]))
            if hz == "15" and c["bounce"]["rate"] is not None and c["bounce"]["random"] is not None:
                out["bounce_real"].append(c["bounce"]["rate"])
                out["bounce_rand"].append(c["bounce"]["random"])
    return out


def run(runs: int, sessions: int, edge: float, seed0: int) -> dict:
    with Pool() as pool:
        rs = pool.map(one_run, [(seed0 + k, sessions, edge) for k in range(runs)])
    judged = [v for r in rs for v in r["verdicts"] if v[2] != "few"]
    claims = [v for v in judged if v[2] in ("bounce", "break", "fewer_bounces")]
    page = sum(1 for r in rs if any(v[2] in ("bounce", "break", "fewer_bounces") for v in r["verdicts"]))
    bounce_hits = [v for v in judged if v[2] == "bounce"]
    gap = [a - b for r in rs for a, b in zip(r["bounce_real"], r["bounce_rand"])]
    return {"runs": runs, "sessions": sessions, "edge": edge, "verdicts_judged": len(judged),
            "per_verdict_claim_rate": len(claims) / max(1, len(judged)),
            "per_verdict_bounce_rate": len(bounce_hits) / max(1, len(judged)),
            "page_claim_rate": page / runs,
            "mean_bounce_gap_15m": sum(gap) / max(1, len(gap)),
            "few_share": 1 - len(judged) / max(1, sum(len(r["verdicts"]) for r in rs))}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1000)
    ap.add_argument("--sessions", type=int, default=30)
    ap.add_argument("--edge", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    r = run(a.runs, a.sessions, a.edge, a.seed)
    for k, v in r.items():
        print(f"{k:26s} {v:.4f}" if isinstance(v, float) else f"{k:26s} {v}")
