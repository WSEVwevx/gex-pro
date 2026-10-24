"""Stress-test every pricing formula against finite differences and identities over a wide grid.

Run from the project folder: python tools/pricing_stress.py (or all checks: python tools/check.py)
"""
import itertools
import math
import sys

sys.path.insert(0, ".")
from gexsys import pricing as P

worst = {"black76 vs bsm(q=r)": (0.0, "all")}


def rec(name, err, ctx):
    if err > worst.get(name, (0,))[0]:
        worst[name] = (err, ctx)


S = 100.0
for m, t, v, r, q in itertools.product((0.7, 0.85, 0.95, 1.0, 1.05, 1.15, 1.3), (1 / 8760, 1 / 365, 7 / 365, 30 / 365, 0.5, 2.0),
                                       (0.05, 0.15, 0.3, 0.8, 1.5), (0.0, 0.04), (0.0, 0.013)):
    K = S * m
    ctx = dict(K=K, t=round(t, 5), vol=v, r=r, q=q)
    c, p = P.bsm_price(S, K, t, r, q, v, True), P.bsm_price(S, K, t, r, q, v, False)
    # put-call parity
    rec("put-call parity", abs((c - p) - (S * math.exp(-q * t) - K * math.exp(-r * t))) / S, ctx)
    h = 1e-3 * S * v * math.sqrt(t)          # step scaled to the option's own price range
    # delta, gamma vs central differences of the price
    for call in (True, False):
        fd_d = (P.bsm_price(S + h, K, t, r, q, v, call) - P.bsm_price(S - h, K, t, r, q, v, call)) / (2 * h)
        rec("delta", abs(fd_d - P.bsm_delta(S, K, t, r, q, v, call)), ctx)
    fd_g = (P.bsm_delta(S + h, K, t, r, q, v, True) - P.bsm_delta(S - h, K, t, r, q, v, True)) / (2 * h)
    g = P.bsm_gamma(S, K, t, r, q, v)
    rec("gamma (rel to ATM gamma)", abs(fd_g - g) / P.bsm_gamma(S, S, t, r, q, v), ctx)
    # vanna = d delta / d vol
    dv = 1e-5
    fd_va = (P.bsm_delta(S, K, t, r, q, v + dv, True) - P.bsm_delta(S, K, t, r, q, v - dv, True)) / (2 * dv)
    rec("vanna", abs(fd_va - P.bsm_vanna(S, K, t, r, q, v)) / max(1.0, abs(fd_va)), ctx)
    # charm = d delta / d calendar time = -d delta / d tau
    if t > 2 / 8760:
        dt = min(t * 1e-4, 1e-6)
        for call in (True, False):
            fd_ch = -(P.bsm_delta(S, K, t + dt, r, q, v, call) - P.bsm_delta(S, K, t - dt, r, q, v, call)) / (2 * dt)
            rec("charm", abs(fd_ch - P.bsm_charm(S, K, t, r, q, v, call)) / max(1.0, abs(fd_ch)), ctx)
    # Black-76 == BSM with q = r
    rec("black76 vs bsm(q=r)", abs(P.black76_gamma(S, K, t, r, v) - P.bsm_gamma(S, K, t, r, r, v)) / max(g, 1e-12), ctx)
    # scale invariance used by the SPY/QQQ conversion: gamma(rS, rK) = gamma(S, K) / r
    rec("gamma scaling", abs(P.bsm_gamma(10 * S, 10 * K, t, r, q, v) * 10 - g) / max(g, 1e-300), ctx)
    # IV round trip (skip prices too close to intrinsic to carry IV information)
    for call, px in ((True, c), (False, p)):
        intrinsic = max(0.0, (S * math.exp(-q * t) - K * math.exp(-r * t)) if call else (K * math.exp(-r * t) - S * math.exp(-q * t)))
        vega = S * math.exp(-q * t) * P.norm_pdf(P._d1_d2(S, K, t, r, q, v)[0]) * math.sqrt(t)
        if px - intrinsic > 1e-4 and vega > 1e-4 and v <= 1.5:
            iv = P.implied_vol(px, S, K, t, r, q, call)
            rec("IV round trip (vol pts)", 100 * abs((iv or -1) - v), ctx)

ok_limits = {"put-call parity": 1e-12, "delta": 1e-6, "gamma (rel to ATM gamma)": 1e-4, "vanna": 1e-4, "charm": 1e-3,
             "black76 vs bsm(q=r)": 1e-12, "gamma scaling": 1e-9, "IV round trip (vol pts)": 0.05}
bad = 0
for k, (err, ctx) in worst.items():
    ok = err <= ok_limits[k]
    bad += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {k:26s} worst {err:.3e} (limit {ok_limits[k]:.0e})  at {ctx}")
# American vs European: CRR American put >= European put, call ~= European call (no dividend)
eu = P.bsm_price(100, 105, 0.5, 0.04, 0.0, 0.25, False)
am = P.crr_american(100, 105, 0.5, 0.04, 0.0, 0.25, False)
euc = P.bsm_price(100, 105, 0.5, 0.04, 0.0, 0.25, True)
amc = P.crr_american(100, 105, 0.5, 0.04, 0.0, 0.25, True)
print(f"{'OK  ' if am >= eu - 1e-9 and abs(amc - euc) < 0.02 else 'FAIL'} CRR American: put {am:.4f} >= european {eu:.4f}; call {amc:.4f} ~ {euc:.4f}")
bad += not (am >= eu - 1e-9 and abs(amc - euc) < 0.02)
print("ALL PRICING CHECKS PASS" if not bad else f"{bad} FAILED")
sys.exit(1 if bad else 0)
