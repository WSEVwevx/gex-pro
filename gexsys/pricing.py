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
QUOTE_TOL = 0.005        # a quoted mid is known to half a cent
QUOTE_MAX_VOL_ERR = 0.02 # ...so an IV that half a cent cannot pin to 2 vol points is refused, not guessed


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def norm_cdf(x: float) -> float:
    # erfc keeps full relative precision in both tails; 0.5 * (1 + erf(x)) cancels for x << 0 (deep OTM prices
    # came out 200x too large at 1e-14: tools/stress/greeks_precision.py)
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _d1_d2(s: float, k: float, t: float, r: float, q: float, vol: float) -> tuple[float, float]:
    t = max(t, MIN_T)
    vol = max(vol, MIN_VOL)
    vs = vol * math.sqrt(t)
    lm = math.log(s / k)
    # d2 directly, not d1 - vs: that difference cancels to rounding noise near the money when r - q ~ vol^2 / 2
    return (lm + (r - q + 0.5 * vol * vol) * t) / vs, (lm + (r - q - 0.5 * vol * vol) * t) / vs


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


def implied_vol_status(price: float, s, k, t, r, q, is_call: bool, price_tol: Optional[float] = None,
                       max_vol_err: float = 1e-6, lo: float = 1e-4, hi: float = 5.0) -> tuple[Optional[float], str]:
    """(vol, "ok") or (None, why) for a European (BSM) price.

    Solved on the vol itself (bisection in log-vol to 1e-12 relative: it cannot diverge for deep in / out of the
    money or tiny-vega 0DTE options). A price that does not pin the vol down is REFUSED, never answered:
    the price's own precision (price_tol; default 1e-10 x max(price, 1), for exact prices) divided by vega
    must be at most max_vol_err. Quoted mids are cents: pass price_tol=0.005 and a max_vol_err such as 0.02.
    Before 2026-11-10 the solver stopped once the PRICE was within 1e-7 and answered anyway: a deep
    in-the-money call priced at 2% vol came back at 499% (tools/stress/iv_solver.py)."""
    if price is None or not math.isfinite(price) or price <= 0:
        return None, "no price"
    if s <= 0 or k <= 0:
        return None, "bad underlying or strike"
    t = max(t, MIN_T)
    disc_s, disc_k = s * math.exp(-q * t), k * math.exp(-r * t)
    intrinsic = max(0.0, (disc_s - disc_k) if is_call else (disc_k - disc_s))
    top = disc_s if is_call else disc_k
    if price >= top:
        return None, "at or above the no-arbitrage maximum"
    tiny = 1e-12 * max(top, 1.0)
    if price < intrinsic - tiny:
        return None, "below intrinsic value"
    if price - intrinsic <= tiny:
        return None, "no time value: the price does not set a vol"
    f = lambda v: bsm_price(s, k, t, r, q, v, is_call) - price
    if f(hi) < 0:
        return None, f"needs a vol above {hi:.0%}"
    if f(lo) > 0:
        return None, f"needs a vol below {lo:.2%}"
    a, b = math.log(lo), math.log(hi)
    for _ in range(200):
        m = 0.5 * (a + b)
        if f(math.exp(m)) < 0:
            a = m
        else:
            b = m
        if b - a < 1e-12:
            break
    v = math.exp(0.5 * (a + b))
    d1, _ = _d1_d2(s, k, t, r, q, v)
    vega = disc_s * norm_pdf(d1) * math.sqrt(t)
    res = price_tol if price_tol is not None else 1e-10 * max(price, 1.0)
    if vega <= 0 or res / vega > max_vol_err:
        return None, "the price barely depends on vol here, so it does not pin the vol down"
    return v, "ok"


def implied_vol(price: float, s, k, t, r, q, is_call: bool, price_tol: Optional[float] = None,
                max_vol_err: float = 1e-6) -> Optional[float]:
    """The vol, or None when the price does not determine one (see implied_vol_status for why)."""
    return implied_vol_status(price, s, k, t, r, q, is_call, price_tol, max_vol_err)[0]
