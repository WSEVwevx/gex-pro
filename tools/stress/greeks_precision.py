"""Stress test A1: every price and Greek in gexsys/pricing against a 50-digit reference (mpmath).

  python tools/stress/greeks_precision.py          (needs `pip install mpmath`, a test-only dependency)

Grid: moneyness K/S 0.5-1.5 (14 values), time 1 minute to 2 years (9), IV 5%-200% (7), rates -1% to 8% (5),
dividends 0-5% (4), calls and puts: 35,280 contracts. Two references, both independent of the code:
  closed form   the Black-Scholes-Merton formulas evaluated in 50-digit arithmetic
  derivatives   numerical differentiation of the 50-digit price (mpmath.diff), which checks the closed forms
Tolerance (fixed before running): |code - ref| / max(|ref|, floor) <= 1e-6, floor 1e-10 (x spot for the
price, / spot for gamma): values smaller than the floor carry no weight in any exposure.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import mpmath as mp

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gexsys import pricing as P  # noqa: E402

mp.mp.dps = 50
S = 20000.0
MONEY = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0, 1.01, 1.05, 1.1, 1.2, 1.3, 1.5)
TIMES = (1 / 525600, 15 / 525600, 1 / 8760, 1 / 365, 7 / 365, 30 / 365, 0.25, 1.0, 2.0)
VOLS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.2, 2.0)
RATES = (-0.01, 0.0, 0.02, 0.05, 0.08)
DIVS = (0.0, 0.01, 0.03, 0.05)
TOL = 1e-6


def ref(s, k, t, r, q, v, call):
    s, k, t, r, q, v = (mp.mpf(x) for x in (s, k, t, r, q, v))
    vs = v * mp.sqrt(t)
    d1 = (mp.log(s / k) + (r - q + v * v / 2) * t) / vs
    d2 = d1 - vs
    N, n = mp.ncdf, mp.npdf
    eq, er = mp.e ** (-q * t), mp.e ** (-r * t)
    price = s * eq * N(d1) - k * er * N(d2) if call else k * er * N(-d2) - s * eq * N(-d1)
    delta = eq * N(d1) if call else eq * (N(d1) - 1)
    gamma = eq * n(d1) / (s * vs)
    vanna = -eq * n(d1) * d2 / v
    common = eq * n(d1) * (2 * (r - q) * t - d2 * vs) / (2 * t * vs)
    charm = q * eq * N(d1) - common if call else -q * eq * N(-d1) - common
    return {"price": price, "delta": delta, "gamma": gamma, "vanna": vanna, "charm": charm}


def ref_diff(s, k, t, r, q, v, call):
    """Greeks as derivatives of the 50-digit price: checks the closed forms above."""
    def price(S_, T_, V_):
        return ref(S_, k, T_, r, q, V_, call)["price"]
    return {"delta": mp.diff(lambda x: price(x, t, v), s),
            "gamma": mp.diff(lambda x: price(x, t, v), s, 2),
            "vanna": mp.diff(lambda x, y: price(x, t, y), (s, v), (1, 1)),
            "charm": -mp.diff(lambda x, y: price(x, y, v), (s, t), (1, 1))}


def code(s, k, t, r, q, v, call):
    return {"price": P.bsm_price(s, k, t, r, q, v, call), "delta": P.bsm_delta(s, k, t, r, q, v, call),
            "gamma": P.bsm_gamma(s, k, t, r, q, v), "vanna": P.bsm_vanna(s, k, t, r, q, v),
            "charm": P.bsm_charm(s, k, t, r, q, v, call)}


FLOOR = {"price": 1e-10 * S, "delta": 1e-10, "gamma": 1e-10 / S, "vanna": 1e-10, "charm": 1e-10}


def main(sample_diff: int = 400) -> int:
    worst = {g: (0.0, None, None, None) for g in FLOOR}
    worst_abs = {g: 0.0 for g in FLOOR}
    n = 0
    for m, t, v, r, q, call in itertools.product(MONEY, TIMES, VOLS, RATES, DIVS, (True, False)):
        k = S * m
        a, b = code(S, k, t, r, q, v, call), ref(S, k, t, r, q, v, call)
        for g in FLOOR:
            err = abs(a[g] - float(b[g]))
            rel = err / max(abs(float(b[g])), FLOOR[g])
            worst_abs[g] = max(worst_abs[g], err)
            if rel > worst[g][0]:
                worst[g] = (rel, dict(K=m, t=t, vol=v, r=r, q=q, call=call), a[g], float(b[g]))
        n += 1
    # the closed forms themselves, against derivatives of the price (a spread of the grid)
    form_worst = {g: 0.0 for g in ("delta", "gamma", "vanna", "charm")}
    grid = list(itertools.product(MONEY, TIMES[2:], VOLS, (0.0, 0.05), (0.0, 0.03), (True, False)))
    for m, t, v, r, q, call in grid[:: max(1, len(grid) // sample_diff)]:
        b, d = ref(S, S * m, t, r, q, v, call), ref_diff(S, S * m, t, r, q, v, call)
        for g in form_worst:
            form_worst[g] = max(form_worst[g], float(abs(b[g] - d[g]) / max(abs(b[g]), mp.mpf(FLOOR[g]))))
    print(f"contracts checked: {n} (calls and puts); tolerance {TOL:g} relative")
    fails = 0
    for g, (rel, ctx, got, want) in worst.items():
        ok = rel <= TOL
        fails += not ok
        print(f"  {g:6s} max rel {rel:.2e}  max abs {worst_abs[g]:.2e}  {'PASS' if ok else 'FAIL'}"
              + ("" if ok else f"  at {ctx}: code {got!r} vs ref {want!r}"))
    print("closed forms vs 50-digit derivatives of the price:")
    for g, e in form_worst.items():
        ok = e <= TOL
        fails += not ok
        print(f"  {g:6s} max rel {e:.2e}  {'PASS' if ok else 'FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
