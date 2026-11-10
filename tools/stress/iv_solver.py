"""Stress test A2: the implied-vol solver (gexsys/pricing.implied_vol) on 100,000 random prices plus edge cases.

  python tools/stress/iv_solver.py [--n 100000]

Each case starts from a true vol, prices the option exactly, and asks the solver for the vol back.
  determinable   the price's resolution (1e-10 x max(price, 1)) fixes the vol to within 1e-6, i.e. a 1e-6 change
                 of vol moves the price by at least that resolution: the price pins the vol down. The solver must return it within 1e-6 (PASS) - a refusal here counts against the
                 convergence rate.
  undetermined   the price barely depends on vol (deep in or out of the money, minutes left): the solver must
                 refuse; a returned vol more than 1e-4 from the truth is SILENTLY WRONG.
  impossible     price at / below intrinsic, at / above the no-arbitrage maximum, zero, negative: must refuse.
Tolerance (fixed before running): 0 silently wrong answers, 0 impossible prices accepted, round-trip error
<= 1e-6 on determinable cases, convergence >= 99.9% of determinable cases.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gexsys import pricing as P  # noqa: E402


def case(rng: random.Random):
    s = 20000.0
    m = math.exp(rng.uniform(math.log(0.5), math.log(1.5)))
    t = math.exp(rng.uniform(math.log(1 / 525600), math.log(2.0)))
    v = math.exp(rng.uniform(math.log(0.02), math.log(3.0)))
    return s, s * m, t, rng.uniform(-0.01, 0.08), rng.uniform(0.0, 0.05), v, rng.random() < 0.5


def solve(fn, px, s, k, t, r, q, call):
    out = fn(px, s, k, t, r, q, call)
    return out if not isinstance(out, tuple) else out[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100000)
    a = ap.parse_args()
    rng = random.Random(11)
    fn = getattr(P, "implied_vol_status", P.implied_vol)
    det = det_ok = det_refused = undet = undet_wrong = undet_refused = 0
    worst_rt, worst_wrong = 0.0, None
    for _ in range(a.n):
        s, k, t, r, q, v, call = case(rng)
        px = P.bsm_price(s, k, t, r, q, v, call)
        h = 1e-6
        dp = abs(P.bsm_price(s, k, t, r, q, v + h, call) - P.bsm_price(s, k, t, r, q, v - h, call))
        # the price pins the vol to 1e-6 when its resolution (1e-10 x max(price, 1)) is at most vega x 1e-6;
        # dp spans +/-1e-6, i.e. 2e-6 of vol (the first version compared dp itself: a factor-2 slip that called
        # vols known only to 2e-6 "determinable")
        determinable = dp / 2 >= 1e-10 * max(px, 1.0) and px > 0
        iv = solve(fn, px, s, k, t, r, q, call)
        if determinable:
            det += 1
            if iv is None:
                det_refused += 1
            else:
                err = abs(iv - v)
                worst_rt = max(worst_rt, err)
                det_ok += err <= 1e-6
                if err > 1e-4 and (worst_wrong is None or err > worst_wrong[0]):
                    worst_wrong = (err, dict(K=k / s, t=t, vol=v, call=call, got=iv))
        else:
            undet += 1
            if iv is None:
                undet_refused += 1
            elif abs(iv - v) > 1e-4:
                undet_wrong += 1
                if worst_wrong is None or abs(iv - v) > worst_wrong[0]:
                    worst_wrong = (abs(iv - v), dict(K=k / s, t=t, vol=v, call=call, got=iv, price=px))
    # impossible prices
    imp_cases = imp_accepted = 0
    for _ in range(2000):
        s, k, t, r, q, v, call = case(rng)
        intrinsic = max(0.0, (s * math.exp(-q * t) - k * math.exp(-r * t)) if call else (k * math.exp(-r * t) - s * math.exp(-q * t)))
        top = s * math.exp(-q * t) if call else k * math.exp(-r * t)
        for px in (intrinsic * (1 - 1e-6) - 1e-6, top, top * 1.01, 0.0, -1.0):
            imp_cases += 1
            imp_accepted += solve(fn, px, s, k, t, r, q, call) is not None
    conv = (det_ok / det) if det else 1.0
    print(f"cases {a.n}: determinable {det}, undetermined {undet}")
    print(f"  determinable: within 1e-6 {det_ok} ({conv:.4%}), refused {det_refused}, worst round-trip error {worst_rt:.2e}")
    print(f"  undetermined: refused {undet_refused}, returned a vol more than 1e-4 off (silently wrong) {undet_wrong}")
    print(f"  impossible prices: {imp_cases} tried, accepted {imp_accepted}")
    if worst_wrong:
        print(f"  worst wrong answer: off by {worst_wrong[0]:.3g} at {worst_wrong[1]}")
    fails = []
    if undet_wrong or (worst_wrong and worst_wrong[0] > 1e-4):
        fails.append("silently wrong answers")
    if imp_accepted:
        fails.append("impossible prices accepted")
    if conv < 0.999:
        fails.append(f"convergence {conv:.4%} < 99.9%")
    print("RESULT:", "PASS" if not fails else "FAIL - " + "; ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
