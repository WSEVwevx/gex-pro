"""Does gexpro/uncertainty.py's 95% interval cover the truth 93-97% of the time? (Phase 4 method check)

  python tools/stress/uncertainty_coverage.py [--datasets 1000] [--reps 10000] [--sessions 40] [--seed 20261118]

1,000 synthetic datasets with a known effect and day-level clustering, seeded: each session has its own day effect
u ~ N(0, 0.6) on the log-odds scale, shared by the real level and the baseline that day (as one day's tape is);
real touches per session 0-3 (mean 1.5), baseline touches 15-25; reject log-odds -0.8 + u for the baseline and
-0.8 + 0.5 + u for the real level. The true difference is the population ratio of rejects to touches, real minus
baseline, from 400,000 simulated sessions. Pass: coverage within 93-97% (fixed before running).
Recorded: the plain percentile interval gave 0.947 at 40 sessions but 0.924 (FAIL) at 20; hence the expanded percentile.
Expanded percentile, 1,000 datasets x 10,000 resamples: 0.935 at 10 sessions, 0.951 at 20 (0.941 with --seed 7),
0.955 at 40. No dataset triggered BCa, so the BCa branch is not covered by this check.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gexpro import uncertainty as U  # noqa: E402

BASE, EFFECT, DAY_SD = -0.8, 0.5, 0.6
LO, HI = 0.93, 0.97


def session(rng: random.Random) -> U.Session:
    u = rng.gauss(0, DAY_SD)
    pr, pb = 1 / (1 + math.exp(-(BASE + EFFECT + u))), 1 / (1 + math.exp(-(BASE + u)))
    rn, bn = rng.randint(0, 3), rng.randint(15, 25)
    return (sum(rng.random() < pr for _ in range(rn)), rn, sum(rng.random() < pb for _ in range(bn)), bn)


def truth(seed: int = 1, n: int = 400_000) -> float:
    rng = random.Random(seed)
    return U.diff([session(rng) for _ in range(n)])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", type=int, default=1000)
    ap.add_argument("--reps", type=int, default=U.REPS)
    ap.add_argument("--sessions", type=int, default=40)
    ap.add_argument("--seed", type=int, default=20261118)
    a = ap.parse_args(argv)
    true = truth()
    rng = random.Random(a.seed)
    hit = used = bca = 0
    for k in range(a.datasets):
        ss = [session(rng) for _ in range(a.sessions)]
        r = U.summarize(ss, a.reps, seed=k)
        if "interval" not in r:
            continue
        used += 1
        bca += r["interval_method"] == "BCa"
        hit += r["interval"][0] <= true <= r["interval"][1]
    cov = hit / used
    print(f"true difference {true:.4f}; {used} datasets of {a.sessions} sessions, {a.reps} resamples each "
          f"({bca} used BCa); coverage {cov:.3f} (pass {LO:.2f}-{HI:.2f})")
    print("PASS" if LO <= cov <= HI else "FAIL")
    return 0 if LO <= cov <= HI else 1


if __name__ == "__main__":
    sys.exit(main())
