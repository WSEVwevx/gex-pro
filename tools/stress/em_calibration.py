"""Stress test D1: is the daily ±1σ expected-move band calibrated?

  python tools/stress/em_calibration.py

A  The band GEX PRO actually published (track-record branch, frozen before 09:30): close inside anchor ± 1σ?
   Exact binomial test against 68.3%, Clopper-Pearson 95% interval, split by GEX regime and weekday.
B  The same construction over decades (trackrecord/backtest.py: previous close x vol index x sqrt(calendar days /
   365), VIX for SPX since 1990, VXN for NDX since 2009). A proxy: the 30-day vol index stands in for the band's own
   nearest-expiry ATM IV. Coverage, PIT histogram (Φ of the close in σ units, 10 bins, chi-square), splits by weekday
   and IV tercile. If miscalibrated: the scale k that makes the band hold 68.3% is fitted on the first half of the
   dates only and checked on the second half.
Tolerance (fixed before running): calibrated if the binomial p >= 0.05 against 68.3%; a correction is accepted only
if, on the held-out half, its coverage is within 1.5 points of 68.3% and closer than the uncorrected band's.
"""
from __future__ import annotations

import csv
import io
import math
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from trackrecord import backtest, prices  # noqa: E402

TARGET = math.erf(1 / math.sqrt(2))       # 0.6827


def binom_p(k: int, n: int, p: float) -> float:
    """Exact two-sided binomial p (sum of outcomes no more likely than k)."""
    lp = lambda i: math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p)
    ref = lp(k)
    return min(1.0, sum(math.exp(lp(i)) for i in range(n + 1) if lp(i) <= ref + 1e-9))


def binom_cdf(k: int, n: int, p: float) -> float:
    if p <= 0:
        return 1.0
    if p >= 1:
        return 0.0 if k < n else 1.0
    return sum(math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p))
               for i in range(k + 1))


def clopper_pearson(k: int, n: int) -> tuple[float, float]:
    return (0.0 if k == 0 else _cp_lo(k, n)), (1.0 if k == n else _cp_hi(k, n))


def _cp_lo(k, n):
    lo, hi = 0.0, 1.0
    for _ in range(60):                      # P(X >= k | p) = 0.025
        mid = (lo + hi) / 2
        if 1 - binom_cdf(k - 1, n, mid) < 0.025:
            lo = mid
        else:
            hi = mid
    return lo


def _cp_hi(k, n):
    lo, hi = 0.0, 1.0
    for _ in range(60):                      # P(X <= k | p) = 0.025
        mid = (lo + hi) / 2
        if binom_cdf(k, n, mid) > 0.025:
            lo = mid
        else:
            hi = mid
    return hi


def chi2_sf(x: float, k: int) -> float:
    """Upper tail of chi-square with k degrees of freedom (regularized gamma Q(k/2, x/2))."""
    a, z = k / 2, x / 2
    if z < a + 1:                            # series for P, then Q = 1 - P
        s, term, n = 1 / a, 1 / a, 0
        while abs(term) > 1e-15 * abs(s):
            n += 1
            term *= z / (a + n)
            s += term
        return 1 - s * math.exp(-z + a * math.log(z) - math.lgamma(a))
    b, c, d = z + 1 - a, 1e300, 1 / (z + 1 - a)
    h = d
    for i in range(1, 300):                  # Lentz continued fraction for Q
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        h *= d * c
        if abs(d * c - 1) < 1e-15:
            break
    return math.exp(-z + a * math.log(z) - math.lgamma(a)) * h


def coverage_line(name: str, inside: list[bool]) -> str:
    n, k = len(inside), sum(inside)
    if not n:
        return f"  {name:28s} n 0"
    lo, hi = clopper_pearson(k, n)
    return f"  {name:28s} n {n:5d}  inside {100 * k / n:5.1f}%  95% CI {100 * lo:5.1f}-{100 * hi:5.1f}  p vs 68.3% {binom_p(k, n, TARGET):.3g}"


def pit(rows: list[dict]) -> tuple[list[int], float]:
    u = [0.5 * (1 + math.erf(r["move_em"] / math.sqrt(2))) for r in rows]
    bins = [0] * 10
    for x in u:
        bins[min(9, int(x * 10))] += 1
    e = len(u) / 10
    return bins, chi2_sf(sum((b - e) ** 2 / e for b in bins), 9)


def live() -> list[bool]:
    txt = subprocess.run(["git", "show", "origin/track-record:history.csv"], cwd=ROOT, capture_output=True, text=True).stdout
    rows = [r for r in csv.DictReader(io.StringIO(txt)) if r["status"] == "graded" and r["move_em"]]
    print(f"A. The band GEX PRO published ({len(rows)} graded session-markets, {rows[0]['session']} to {rows[-1]['session']})")
    print(coverage_line("all", [abs(float(r["move_em"])) <= 1 for r in rows]))
    for key, vals in (("market", ("NQ", "ES")), ("regime", ("POSITIVE", "NEGATIVE", "INDETERMINATE"))):
        for v in vals:
            print(coverage_line(f"{key} {v}", [abs(float(r["move_em"])) <= 1 for r in rows if r[key] == v]))
    for wd, nm in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri")):
        print(coverage_line(f"weekday {nm}", [abs(float(r["move_em"])) <= 1 for r in rows if date.fromisoformat(r["session"]).weekday() == wd]))
    u = [{"move_em": float(r["move_em"])} for r in rows]
    bins, p = pit(u)
    print(f"  PIT deciles {bins}  chi-square p {p:.3g} (n {len(u)}: low power)")
    return [abs(float(r["move_em"])) <= 1 for r in rows]


def history(und: str) -> list[str]:
    verdicts = []
    rows = backtest.days(prices.daily(und), prices.vol_index(und))
    name = prices.VOL_INDEX[und]
    print(f"\nB. {und} with {name}, {rows[0]['date']} to {rows[-1]['date']} (proxy for the band's own IV)")
    inside = [r["close_in"] for r in rows]
    print(coverage_line("all", inside))
    for wd, nm in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri")):
        print(coverage_line(f"weekday {nm}", [r["close_in"] for r in rows if date.fromisoformat(r["date"]).weekday() == wd]))
    vs = sorted(r["vol"] for r in rows)
    t1, t2 = vs[len(vs) // 3], vs[2 * len(vs) // 3]
    for nm, lo, hi in (("IV low tercile", 0, t1), ("IV mid tercile", t1, t2), ("IV high tercile", t2, 1e9)):
        print(coverage_line(f"{nm} ({name} {lo:.0f}-{min(hi, 999):.0f})", [r["close_in"] for r in rows if lo <= r["vol"] < hi]))
    bins, p = pit(rows)
    print(f"  PIT deciles {bins}  chi-square p {p:.3g}")
    k_in = sum(inside)
    if binom_p(k_in, len(rows), TARGET) >= 0.05:
        verdicts.append(f"{und}: calibrated")
        return verdicts
    half = len(rows) // 2
    fit, test = rows[:half], rows[half:]
    k = sorted(abs(r["move_em"]) for r in fit)[int(TARGET * (len(fit) - 1))]
    raw_t = [abs(r["move_em"]) <= 1 for r in test]
    cor_t = [abs(r["move_em"]) <= k for r in test]
    print(f"  correction fitted on {fit[0]['date']}..{fit[-1]['date']}: band x {k:.3f}")
    print(coverage_line("held out, as published", raw_t))
    print(coverage_line(f"held out, x {k:.3f}", cor_t))
    c_raw, c_cor = sum(raw_t) / len(test), sum(cor_t) / len(test)
    ok = abs(c_cor - TARGET) <= 0.015 and abs(c_cor - TARGET) < abs(c_raw - TARGET)
    verdicts.append(f"{und}: miscalibrated ({100 * k_in / len(rows):.1f}% inside); x{k:.3f} {'validates' if ok else 'does NOT validate'} "
                    f"on the held-out half ({100 * c_cor:.1f}%)")
    return verdicts


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    live()
    out = history("SPX") + history("NDX")
    print("\nRESULT:\n  " + "\n  ".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
