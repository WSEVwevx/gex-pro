"""Uncertainty for the Backtesting tab's rates and differences, stated correctly (standard library only).

Every rate or difference is compared with its baseline per session: the unit resampled is the whole session, never
the touch (one day's touches share that day's tape and are not independent).

  interval     95%, 10,000 session resamples, seeded. Expanded percentile interval (Hesterberg): the tails are cut at
               z = sqrt(S/(S-1)) x t_0.975(S-1) instead of 1.96, because the plain percentile interval is too narrow
               with few sessions (coverage 92.4% at 20 sessions in the check below). BCa (bias-corrected and
               accelerated, jackknife over sessions, same z) when the bootstrap's bias is large: |z0| > BIAS_LIMIT.
               The method is named.
  p-value      two-sided, against no difference from the baseline, from the same resamples: twice the smaller tail
               share beyond 0, with +1 smoothing so it is never exactly 0. A p-value, not "the chance the edge is zero".
  power        sessions needed to detect the observed difference at 80% power and alpha 0.05, scaling the bootstrap
               variance: S x (z_0.975 + z_0.8)^2 x var / diff^2. Labelled optimistic: an effect seen in a small sample is
               usually overstated, so the true number needed is usually larger.
  headline     an interval that includes 0 reads "no proven edge yet (n sessions)".

tools/stress/uncertainty_coverage.py checks the method on 1,000 synthetic datasets with a known effect and day-level
clustering: the intervals must cover the true value 93-97% of the time.
"""
from __future__ import annotations

import math
import random
from statistics import NormalDist
from typing import Optional

N = NormalDist()
Z975, Z80 = N.inv_cdf(0.975), N.inv_cdf(0.80)
BIAS_LIMIT = 0.25            # |z0| above this: BCa instead of the percentile interval (fixed before any result)
REPS, SEED = 10_000, 20261118

Session = tuple[int, int, int, int]       # (real rejects, real touches, baseline rejects, baseline touches)


def diff(ss: list[Session]) -> Optional[float]:
    rr, rn, br, bn = (sum(s[i] for s in ss) for i in range(4))
    return rr / rn - br / bn if rn and bn else None


def resample(ss: list[Session], reps: int = REPS, seed: int = SEED) -> list[float]:
    """The difference recomputed on `reps` resamples of whole sessions (resamples with no touch on a side are skipped)."""
    rng, n, out = random.Random(seed), len(ss), []
    for _ in range(reps):
        rr = rn = br = bn = 0
        for i in rng.choices(range(n), k=n):
            s = ss[i]
            rr += s[0]
            rn += s[1]
            br += s[2]
            bn += s[3]
        if rn and bn:
            out.append(rr / rn - br / bn)
    return out


def t975(df: int) -> float:
    """Student t 0.975 quantile (Cornish-Fisher series in z; within 0.002 of the tables for df >= 3)."""
    z, v = Z975, df
    return (z + (z ** 3 + z) / (4 * v) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * v ** 2)
            + (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / (384 * v ** 3)
            + (79 * z ** 9 + 776 * z ** 7 + 1482 * z ** 5 - 1920 * z ** 3 - 945 * z) / (92160 * v ** 4))


def z_expanded(sessions: int) -> float:
    """Hesterberg's expanded-percentile multiplier: sqrt(S/(S-1)) x t_0.975(S-1)."""
    return math.sqrt(sessions / (sessions - 1)) * t975(sessions - 1)


def _quantile(xs: list[float], q: float) -> float:
    """Sorted xs; the q quantile by linear interpolation."""
    pos = q * (len(xs) - 1)
    lo = math.floor(pos)
    return xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (pos - lo)


def interval(ss: list[Session], diffs: list[float], est: float) -> dict:
    xs, z = sorted(diffs), z_expanded(len(ss))
    below = sum(d < est for d in xs) + 0.5 * sum(d == est for d in xs)
    z0 = N.inv_cdf(min(max(below / len(xs), 1e-6), 1 - 1e-6))
    if abs(z0) <= BIAS_LIMIT:
        return {"method": "expanded percentile", "lo": _quantile(xs, N.cdf(-z)), "hi": _quantile(xs, N.cdf(z)), "z0": z0}
    jack = [d for d in (diff(ss[:i] + ss[i + 1:]) for i in range(len(ss))) if d is not None]
    m = sum(jack) / len(jack)
    num, den = sum((m - j) ** 3 for j in jack), 6 * sum((m - j) ** 2 for j in jack) ** 1.5
    a = num / den if den else 0.0
    q = lambda z: N.cdf(z0 + (z0 + z) / (1 - a * (z0 + z)))
    return {"method": "BCa", "lo": _quantile(xs, q(-z)), "hi": _quantile(xs, q(z)), "z0": z0, "a": a}


def p_value(diffs: list[float]) -> float:
    n = len(diffs)
    tail = min(sum(d <= 0 for d in diffs), sum(d >= 0 for d in diffs))
    return min(1.0, 2 * (tail + 1) / (n + 1))


def sessions_needed(diffs: list[float], est: float, sessions: int) -> Optional[int]:
    if not est:
        return None
    m = sum(diffs) / len(diffs)
    var = sum((d - m) ** 2 for d in diffs) / (len(diffs) - 1)
    return math.ceil(sessions * (Z975 + Z80) ** 2 * var / est ** 2)


def summarize(ss: list[Session], reps: int = REPS, seed: int = SEED) -> dict:
    """Everything the tab shows for one rate difference."""
    est = diff(ss)
    if est is None:
        return {"sessions": len(ss), "unavailable": "no touches on one side"}
    if len(ss) < 2:
        return {"sessions": len(ss), "difference": round(est, 4), "unavailable": "one session: nothing to resample"}
    ds = resample(ss, reps, seed)
    if len(ds) < 0.9 * reps:
        return {"sessions": len(ss), "difference": round(est, 4), "unavailable": "over 10% of session resamples had no touch on one side"}
    iv = interval(ss, ds, est)
    zero_in = iv["lo"] <= 0 <= iv["hi"]
    return {"sessions": len(ss), "difference": round(est, 4), "interval": [round(iv["lo"], 4), round(iv["hi"], 4)],
            "interval_method": iv["method"], "z0": round(iv["z0"], 3), "p_value": round(p_value(ds), 4),
            "sessions_needed_80pct": sessions_needed(ds, est, len(ss)), "power_label": "optimistic",
            "headline": f"no proven edge yet ({len(ss)} sessions)" if zero_in
            else f"{'more' if est > 0 else 'fewer'} rejections than the baseline ({len(ss)} sessions)",
            "reps": reps, "seed": seed}
