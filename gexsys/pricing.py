"""Option pricing and Greeks.

Models
------
* Black-Scholes-Merton (continuous dividend yield q) for European index options
  (SPX, NDX).  Used as an *approximation* for American ETF options (SPY, QQQ):
  for gamma of near-dated, near-the-money options the early-exercise premium is
  small, but it is not zero.  `crr_american` is provided to quantify the error.
* Black-76 for options on futures (ES, NQ options).  Equivalent to BSM with
  S = F and q = r.

Units: gamma is d(delta)/dS per 1.0 unit of the underlying, per one unit of
the option (i.e. before the contract multiplier).
"""
from __future__ import annotations

import math
from typing import Callable, Optional

SQRT_2PI = math.sqrt(2.0 * math.pi)
MIN_T = 1.0 / (365.0 * 24.0 * 60.0)   # one minute, in years - floor for 0DTE
MIN_VOL = 1e-4


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1_d2(s: float, k: float, t: float, r: float, q: float, vol: float) -> tuple[float, float]:
    t = max(t, MIN_T)
    vol = max(vol, MIN_VOL)
    vs = vol * math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * vol * vol) * t) / vs
    return d1, d1 - vs


def bsm_price(s, k, t, r, q, vol, is_call: bool) -> float:
    if t <= 0:
        return max(0.0, (s - k) if is_call else (k - s))
    d1, d2 = _d1_d2(s, k, t, r, q, vol)
    if is_call:
        return s * math.exp(-q * t) * norm_cdf(d1) - k * math.exp(-r * t) * norm_cdf(d2)
    return k * math.exp(-r * t) * norm_cdf(-d2) - s * math.exp(-q * t) * norm_cdf(-d1)


def bsm_delta(s, k, t, r, q, vol, is_call: bool) -> float:
    d1, _ = _d1_d2(s, k, t, r, q, vol)
    df = math.exp(-q * max(t, MIN_T))
    return df * norm_cdf(d1) if is_call else df * (norm_cdf(d1) - 1.0)


def bsm_gamma(s, k, t, r, q, vol) -> float:
    """Gamma is identical for calls and puts under BSM."""
    t = max(t, MIN_T)
    d1, _ = _d1_d2(s, k, t, r, q, vol)
    return math.exp(-q * t) * norm_pdf(d1) / (s * max(vol, MIN_VOL) * math.sqrt(t))


def bsm_vanna(s, k, t, r, q, vol) -> float:
    """d(delta)/d(vol), per 1.00 (=100 vol points) of volatility; identical for calls and puts."""
    t = max(t, MIN_T)
    d1, d2 = _d1_d2(s, k, t, r, q, vol)
    return -math.exp(-q * t) * norm_pdf(d1) * d2 / max(vol, MIN_VOL)


def bsm_charm(s, k, t, r, q, vol, is_call: bool) -> float:
    """d(delta)/d(calendar time) per YEAR as time passes (tau shrinking), i.e. -d(delta)/d(tau)."""
    t = max(t, MIN_T)
    d1, d2 = _d1_d2(s, k, t, r, q, vol)
    vs = max(vol, MIN_VOL) * math.sqrt(t)
    common = math.exp(-q * t) * norm_pdf(d1) * (2 * (r - q) * t - d2 * vs) / (2 * t * vs)
    if is_call:
        return q * math.exp(-q * t) * norm_cdf(d1) - common
    return -q * math.exp(-q * t) * norm_cdf(-d1) - common


def black76_price(f, k, t, r, vol, is_call: bool) -> float:
    return bsm_price(f, k, t, r, r, vol, is_call)


def black76_gamma(f, k, t, r, vol) -> float:
    return bsm_gamma(f, k, t, r, r, vol)


def model_gamma(s, k, t, r, q, vol, futures: bool) -> float:
    return black76_gamma(s, k, t, r, vol) if futures else bsm_gamma(s, k, t, r, q, vol)


def finite_diff_gamma(price_fn: Callable[[float], float], s: float, rel_h: float = 1e-3) -> float:
    """Central second difference of a price function, for independent validation."""
    h = s * rel_h
    return (price_fn(s + h) - 2.0 * price_fn(s) + price_fn(s - h)) / (h * h)


def crr_american(s, k, t, r, q, vol, is_call: bool, steps: int = 400) -> float:
    """Cox-Ross-Rubinstein binomial price for an American option (validation use)."""
    t = max(t, MIN_T)
    dt = t / steps
    u = math.exp(vol * math.sqrt(dt))
    d = 1.0 / u
    disc = math.exp(-r * dt)
    p = (math.exp((r - q) * dt) - d) / (u - d)
    if not 0.0 < p < 1.0:
        raise ValueError("CRR risk-neutral probability out of range; increase steps")
    values = [max(0.0, (s * u ** j * d ** (steps - j) - k) if is_call else (k - s * u ** j * d ** (steps - j)))
              for j in range(steps + 1)]
    for i in range(steps - 1, -1, -1):
        for j in range(i + 1):
            cont = disc * (p * values[j + 1] + (1.0 - p) * values[j])
            st = s * u ** j * d ** (i - j)
            ex = (st - k) if is_call else (k - st)
            values[j] = max(cont, ex)
    return values[0]


def implied_vol(price: float, s, k, t, r, q, is_call: bool,
                lo: float = 1e-4, hi: float = 5.0, tol: float = 1e-7, max_iter: int = 200) -> Optional[float]:
    """Bisection IV solver for a European (BSM) price. Returns None if no solution.

    Bisection is slower than Newton but cannot diverge for deep ITM/OTM or
    tiny-vega 0DTE options, which matters more here than speed.
    """
    if price is None or price <= 0 or s <= 0 or k <= 0:
        return None
    t = max(t, MIN_T)
    intrinsic = max(0.0, (s * math.exp(-q * t) - k * math.exp(-r * t)) if is_call
                    else (k * math.exp(-r * t) - s * math.exp(-q * t)))
    if price < intrinsic - 1e-9:
        return None
    f_lo = bsm_price(s, k, t, r, q, lo, is_call) - price
    f_hi = bsm_price(s, k, t, r, q, hi, is_call) - price
    if f_lo * f_hi > 0:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = bsm_price(s, k, t, r, q, mid, is_call) - price
        if abs(f_mid) < tol or (hi - lo) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)
