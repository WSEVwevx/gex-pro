"""Stress test D2: is the daily bias better than a coin, honestly?

  python tools/stress/bias_eval.py

Data: every graded session on the track-record branch (levels frozen before 09:30, graded at the close).
  hit rate      directional calls (Bullish / Bearish) right, against the base rate of the side called
                (a Bullish call on a day that closed up is right; the base rate is how often days closed up)
  permutation   10,000 shuffles of the outcomes across the called sessions: how often does a random pairing
                of calls and outcomes do at least as well? (A constant call has no pairing to test.)
  Brier         needs a probability per call; the bias publishes a label and a confidence word, not a number
  regime        the page's other claim: negative-gamma sessions trade wider ranges than positive / pivot ones
                (|close move| in expected moves, permutation test of the difference in means, 10,000 shuffles)
  power         directional calls needed to show a 55% hit rate beats 50% at 80% power (one-sided 5%)
Tolerance (fixed before running): "better than a coin" needs the permutation p < 0.05 AND a hit rate above the
base rate; anything less is reported as not shown.
"""
from __future__ import annotations

import csv
import io
import math
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHUFFLES = 10_000


def binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k)"""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def calls_needed(p1: float = 0.55, p0: float = 0.5, alpha: float = 0.05, power: float = 0.8) -> int:
    """Smallest n where the exact one-sided binomial test at alpha has the power wanted against p1."""
    for n in range(10, 5000):
        k = next(k for k in range(n + 1) if binom_sf(k, n, p0) <= alpha)       # critical number of hits
        if binom_sf(k, n, p1) >= power:
            return n
    return -1


def main() -> int:
    txt = subprocess.run(["git", "show", "origin/track-record:history.csv"], cwd=ROOT, capture_output=True, text=True).stdout
    rows = [r for r in csv.DictReader(io.StringIO(txt)) if r["status"] == "graded" and r["move_em"]]
    up = [float(r["move_em"]) > 0 for r in rows]
    calls = [(r, u) for r, u in zip(rows, up) if r["bias"] in ("Bullish", "Bearish")]
    print(f"{len(rows)} graded session-markets ({rows[0]['session']} to {rows[-1]['session']}); "
          f"{len(calls)} directional calls, {len(rows) - len(calls)} Neutral")
    print("  calls by label:", {lab: sum(1 for r, _ in calls if r["bias"] == lab) for lab in ("Bullish", "Bearish")})
    hits = [(r["bias"] == "Bullish") == u for r, u in calls]
    base_up = sum(up) / len(up)
    called_up = sum(u for _, u in calls) / len(calls) if calls else float("nan")
    print(f"  hit rate {sum(hits)}/{len(hits)} = {100 * sum(hits) / max(1, len(hits)):.1f}%; base rate: {100 * base_up:.1f}% of all "
          f"graded days closed up ({100 * called_up:.1f}% of the called ones)")
    rng = random.Random(7)
    outcomes = [u for _, u in calls]
    labels = [r["bias"] == "Bullish" for r, _ in calls]
    real = sum(hits)
    ge = 0
    for _ in range(SHUFFLES):
        rng.shuffle(outcomes)
        ge += sum(a == b for a, b in zip(labels, outcomes)) >= real
    p_perm = (ge + 1) / (SHUFFLES + 1)
    constant = len(set(labels)) == 1
    print(f"  permutation p {p_perm:.3f}" + ("  (every call was the same label: a constant call carries no information "
                                              "beyond the base rate, so p is 1 by construction)" if constant else ""))
    print("  Brier score: not computable - the bias publishes Bullish / Bearish / Neutral and a confidence word, no probability")
    # the regime claim
    neg = [abs(float(r["move_em"])) for r in rows if r["regime"] == "NEGATIVE"]
    oth = [abs(float(r["move_em"])) for r in rows if r["regime"] != "NEGATIVE"]
    what = "|close - previous close| in expected moves"
    diff = sum(neg) / len(neg) - sum(oth) / len(oth)
    pool, ge = neg + oth, 0
    for _ in range(SHUFFLES):
        rng.shuffle(pool)
        a, b = pool[:len(neg)], pool[len(neg):]
        ge += sum(a) / len(a) - sum(b) / len(b) >= diff
    p_reg = (ge + 1) / (SHUFFLES + 1)
    print(f"  regime: {what}: negative gamma {sum(neg) / len(neg):.2f} (n {len(neg)}) vs others {sum(oth) / len(oth):.2f} "
          f"(n {len(oth)}); one-sided permutation p {p_reg:.3f}")
    n55 = calls_needed()
    print(f"  power: {n55} directional calls to show 55% beats 50% at 80% power (exact binomial, one-sided 5%)")
    shown = (not constant) and p_perm < 0.05 and sum(hits) / max(1, len(hits)) > max(called_up, 1 - called_up)
    print("\nRESULT:", "better than a coin: shown" if shown else
          f"better than a coin: NOT shown ({sum(hits)}/{len(hits)} right, all from the model before the 2026-11-06 fix; "
          f"the current model has made no graded directional call yet)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
