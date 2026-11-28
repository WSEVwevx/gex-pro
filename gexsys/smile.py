"""Implied-vol smiles from the previous session's per-contract IVs (London Strategic Edge), for the OCC chain.

LSE gives, after each session, one IV per traded contract, computed from that contract's LAST TRADE at the index
price of that moment (greeks_underlying_price). Each row is a different instant, so rows are never read as one
snapshot: every row is moved into time-scaled moneyness first.

The math (rules v1, fixed 2026-11-28 before any result was looked at):

  Rows kept, per root and expiry (a row is one contract):
    - IV in [0.03, 3.0]; a strike, an expiry and a last trade inside session P (open to close, marketcal);
    - the expiry after P's close (P's own expiring contracts say nothing about later days);
    - volume_today >= 1 and greeks_underlying_price S > 0;
    - out of the money at its own trade: puts with K < F, calls with K >= F (the liquid side; in-the-money IVs are
      noisy, and put-call parity makes the two sides the same vol);
    - the last trade in P's final 60 minutes. If an expiry then has too few bins (below), the whole session is used
      for that expiry, and the fit says so (window "session").
  Coordinates:  T = (expiry time - last trade) / 365 days, as the engine;  F = S * exp((r - q) T);
                x = ln(K / F) / sqrt(T)   (time-scaled log-moneyness: a 1-sd move is x = sigma).
  Bins:  width 0.1 * sigma_ref, sigma_ref = the VIX-family curve at that expiry (a tenth of a standard deviation).
         In each bin, rows further than max(2 vol points, 3 x MAD) from the bin's volume-weighted median IV are
         dropped (a stale print); the bin is then the volume-weighted mean of x AND of IV over the rest (both from the
         same rows: a median IV beside a mean x is biased on a sloped smile), weight = their total volume.
  Bad bins: a bin that is a lone stale print cannot be trimmed inside itself, so each bin is compared with a robust
         local line: the Theil-Sen line (median pairwise slope, median intercept) through the up to 3 bins on each side
         of it, itself left out, so a stale bin does not bend the reference of the good bins beside it. The worst bin
         is dropped while it misses by more than max(3 vol points, 4 x the median miss), at most a quarter of the bins
         (a smile is smooth over a few tenths of a standard deviation: its curvature there is a fraction of a vol point).
         Tested: up to 3 stale bins together among 30 are all removed, at either end too; on a handful of bins, two
         stale ones can hide each other (past what any median can resist) and stay, to show in the fit's miss.
  A fit needs >= 5 bins, >= 2 of them on each side of x = 0; otherwise the expiry has no fit of its own.
  Fit:   a monotone piecewise-cubic Hermite spline (PCHIP, Fritsch-Carlson slopes, scipy's end rule) of IV over x
         through the bins; flat IV beyond the first and last bin.
  Quality per expiry: volume-weighted RMS and max of (row IV - fit) in vol points over the rows within 9 vol points
         of the fit; rows further off are counted as outliers (stale prints), not hidden; rows, bins, screened bins,
         the x range.

  Today, per listed contract (strike K, expiry time E), at the current price S0 and time t0:
    T0 = (E - t0) / 365 days, F0 = S0 * exp((r - q) T0), x0 = ln(K / F0) / sqrt(T0), IV = fit_E(x0) * a(T0).
    The smile is carried in x (sticky in time-scaled moneyness): as an expiry nears, its smile narrows in strikes.
  An expiry without its own fit (too few points) takes total variance linear in time at the same x between the
    nearest fitted expiries before and after:  w_i = fit_i(x0)^2 * T_i,  w = w_a + (w_b - w_a)(T0 - T_a)/(T_b - T_a),
    IV = sqrt(w / T0); beyond the last (or before the first) fitted expiry, that expiry's fit at x0.
  The level a(T0) = 1 when P is the newest completed session; when LSE's Greeks lag one session (they are computed
    after each session and can land the evening after), the shape is P's and the level is moved by the index's own
    VIX-family curve between the two closes: a(T) = curve_new(T) / curve_P(T). Older than that: no smile.
  0DTE: today's expiring contracts get no IV (the engine drops them, as it dropped contracts without data in the
    Cboe era): one-day vol is not yesterday's two-day vol, and no study has validated it yet.

Exact readings (pinned after the independent re-computation of 2026-11-28, which matched every claim to 1e-13):
  - window: open <= last trade <= close; "last hour" is last trade >= close - 60 min (to the microsecond; LSE's
    nanoseconds are cut); the session window is used when the last-hour bins fail the full test (>= 5 bins, >= 2 on
    each side) after the screen; a bin at exactly x = 0 counts on neither side.
  - bins: index floor(x / width), the grid anchored at x = 0. Weighted median = the lowest value whose cumulative
    weight reaches half; MAD = the weighted median of |IV - median|; a row is kept when |IV - median| <= the limit.
  - screen: the signed miss against the Theil-Sen line of bins i-3..i+3 without i (fewer at an end); slope = the
    median of (v_b - v_a) / (x_b - x_a) over every pair a < b of them, intercept = the median of v - slope x; medians
    of an even count average the middle two. All misses and their median (sorted |miss|[n // 2], the candidate
    included) are recomputed after each drop; a bin is dropped when |miss| > the limit; ties take the lower x; it runs
    while >= 5 bins remain and fewer than int(0.25 x the bins it started with) are dropped.
  - quality: over every row in the window used (rows trimmed inside a bin included); a row counts as an outlier when
    |row IV - fit| > 9 vol points; RMS weights are volumes.
  - T: seconds / (365 x 86400). a(T0) is evaluated at today's T0. sigma_ref is the vol-date curve at the expiry's time
    left from now. Beyond the last (before the first) fitted expiry, that expiry's fit IV at x0 is used as is.
  - IV bounds are inclusive: 0.03 <= IV <= 3.0.

Gamma is the engine's own (pricing.model_gamma at the current price), never LSE's: LSE's gamma is at another price.
Pure functions: no network, no files. gexsys/providers/occ.py feeds it; tests/test_smile.py and the verifier check it.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

RULES = 1
IV_MIN, IV_MAX = 0.03, 3.0
LAST_WINDOW = timedelta(minutes=60)
BIN_SD = 0.10
MIN_BINS, MIN_SIDE = 5, 2
YEAR_S = 365.0 * 24 * 3600              # = gexsys.engine.YEAR_SECONDS (tested)


_STAMP = re.compile(r"(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:?\d\d)?$")


def stamp(v) -> Optional[datetime]:
    """An LSE time as an aware UTC datetime; None when missing or unreadable. LSE writes UTC without a zone and with
    nanoseconds ('2026-11-25 20:58:19.448381162'); a 'Z' or an offset is honoured; fractions past microseconds dropped."""
    m = _STAMP.match(str(v or "").strip())
    if not m:
        return None
    tz = m.group(4) or "Z"
    try:
        t = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}{(m.group(3) or '')[:7]}{'+00:00' if tz == 'Z' else tz}")
    except ValueError:
        return None
    return t.astimezone(timezone.utc)


def kind(row: dict) -> Optional[str]:
    """'C' or 'P' from LSE's contract_type ('call', 'put', 'C', 'P' ...)."""
    v = str(row.get("contract_type") or "").strip().upper()[:1]
    return v if v in ("C", "P") else None


@dataclass(frozen=True)
class Point:
    x: float          # ln(K / F) / sqrt(T)
    iv: float
    volume: float
    t: float          # years from the last trade to expiry
    strike: float
    late: bool        # traded in the session's final LAST_WINDOW


def points(rows: list, expiry: datetime, session_open: datetime, session_close: datetime, r: float, q: float) -> list[Point]:
    """One expiry's rows (all for that expiry time) as Points, by the rules in the module docstring."""
    out = []
    late_from = session_close - LAST_WINDOW
    for row in rows:
        try:
            k, iv, s = float(row.get("strike")), float(row.get("iv")), float(row.get("greeks_underlying_price"))
            vol = float(row.get("volume_today") or 0)
        except (TypeError, ValueError):
            continue
        typ, tt = kind(row), stamp(row.get("last_trade_at"))
        if not (typ and tt and all(map(math.isfinite, (k, iv, s, vol)))):
            continue
        if not (IV_MIN <= iv <= IV_MAX and k > 0 and s > 0 and vol >= 1 and session_open <= tt <= session_close):
            continue
        if expiry <= session_close:
            continue
        t = (expiry - tt).total_seconds() / YEAR_S
        f = s * math.exp((r - q) * t)
        if (typ == "P") != (k < f):
            continue                                   # in the money at its own trade
        out.append(Point(math.log(k / f) / math.sqrt(t), iv, vol, t, k, tt >= late_from))
    return out


def _wmedian(pairs: list) -> float:
    """Volume-weighted median of [(value, weight)]: the lowest value whose cumulative weight reaches half."""
    pairs = sorted(pairs)
    half, run = sum(w for _, w in pairs) / 2.0, 0.0
    for v, w in pairs:
        run += w
        if run >= half:
            return v
    return pairs[-1][0]


TRIM_FLOOR = 0.02                       # 2 vol points: rows closer than this to the bin's median are always kept
TRIM_MADS = 3.0


def bins(pts: list[Point], sigma_ref: float) -> list[tuple[float, float, float]]:
    """[(x, IV, weight)] sorted by x, one per bin of width BIN_SD * sigma_ref (module docstring)."""
    width = BIN_SD * sigma_ref
    groups: dict[int, list[Point]] = {}
    for p in pts:
        groups.setdefault(math.floor(p.x / width), []).append(p)
    out = []
    for g in groups.values():
        med = _wmedian([(p.iv, p.volume) for p in g])
        mad = _wmedian([(abs(p.iv - med), p.volume) for p in g])
        keep = [p for p in g if abs(p.iv - med) <= max(TRIM_FLOOR, TRIM_MADS * mad)]
        w = sum(p.volume for p in keep)
        out.append((sum(p.x * p.volume for p in keep) / w, sum(p.iv * p.volume for p in keep) / w, w))
    return sorted(out)


def pchip(xs: list[float], ys: list[float]) -> Callable[[float], float]:
    """Monotone cubic Hermite interpolant (Fritsch-Carlson interior slopes, scipy's three-point end rule); flat beyond
    the ends. xs strictly increasing, at least 2 points."""
    n = len(xs)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    s = [0.0] * n
    if n == 2:
        s = [d[0], d[0]]
    else:
        for i in range(1, n - 1):
            if d[i - 1] * d[i] > 0:
                w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
                s[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])

        def end(h0, h1, d0, d1):
            e = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
            if e * d0 <= 0:
                return 0.0
            if d0 * d1 <= 0 and abs(e) > abs(3 * d0):
                return 3 * d0
            return e
        s[0], s[-1] = end(h[0], h[1], d[0], d[1]), end(h[-1], h[-2], d[-1], d[-2])

    def f(x: float) -> float:
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        lo, hi = 0, n - 1
        while hi - lo > 1:                              # the segment holding x
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if xs[mid] <= x else (lo, mid)
        i, t = lo, (x - xs[lo]) / h[lo]
        return (ys[i] * (2 * t ** 3 - 3 * t ** 2 + 1) + h[i] * s[i] * (t ** 3 - 2 * t ** 2 + t)
                + ys[i + 1] * (-2 * t ** 3 + 3 * t ** 2) + h[i] * s[i + 1] * (t ** 3 - t ** 2))
    return f


@dataclass
class Fit:
    expiry: datetime
    window: str                     # "last hour" or "session"
    xs: list
    ivs: list
    rows: int
    rms: float                      # vol points (1.0 = one IV percentage point)
    worst: float
    f: Callable[[float], float] = field(repr=False, default=None)
    screened: int = 0               # bins the neighbour screen dropped
    outliers: int = 0               # rows more than 9 vol points off the fit (left out of rms and worst)

    def iv(self, x: float) -> float:
        return self.f(x)

    def info(self) -> dict:
        return {"expiry": self.expiry.isoformat(), "window": self.window, "rows": self.rows, "bins": len(self.xs),
                "rms_pts": round(self.rms, 3), "max_pts": round(self.worst, 3), "screened_bins": self.screened,
                "outlier_rows": self.outliers,
                "x_range": [round(self.xs[0], 4), round(self.xs[-1], 4)]}


SCREEN_FLOOR = 0.03                     # 3 vol points
SCREEN_MADS = 4.0
SCREEN_MAX = 0.25                       # share of bins the screen may drop


SCREEN_REACH = 3                        # bins on each side in the local line


def _median(v: list) -> float:
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _neighbour_miss(b: list, i: int) -> float:
    """Bin i's IV minus the Theil-Sen line through bins i-3..i+3, bin i left out (module docstring)."""
    nb = [b[j] for j in range(max(0, i - SCREEN_REACH), min(len(b), i + SCREEN_REACH + 1)) if j != i]
    slopes = [(nb[k][1] - nb[j][1]) / (nb[k][0] - nb[j][0]) for j in range(len(nb)) for k in range(j + 1, len(nb))]
    m = _median(slopes)
    c = _median([v - m * x for x, v, _ in nb])
    return b[i][1] - (c + m * b[i][0])


def screen(b: list) -> tuple[list, int]:
    """(bins without the stale ones, how many were dropped): module docstring, "Bad bins"."""
    b, dropped, most = list(b), 0, int(len(b) * SCREEN_MAX)
    while len(b) >= 5 and dropped < most:
        miss = [_neighbour_miss(b, i) for i in range(len(b))]
        mad = sorted(abs(m) for m in miss)[len(miss) // 2]
        worst = max(range(len(b)), key=lambda i: abs(miss[i]))
        if abs(miss[worst]) <= max(SCREEN_FLOOR, SCREEN_MADS * mad):
            break
        del b[worst]
        dropped += 1
    return b, dropped


def _try(pts: list[Point], sigma_ref: float) -> Optional[tuple]:
    b, dropped = screen(bins(pts, sigma_ref))
    if len(b) < MIN_BINS or sum(x < 0 for x, _, _ in b) < MIN_SIDE or sum(x > 0 for x, _, _ in b) < MIN_SIDE:
        return None
    xs, ys = [x for x, _, _ in b], [v for _, v, _ in b]
    return xs, ys, pchip(xs, ys), dropped


def fit(expiry: datetime, pts: list[Point], sigma_ref: float) -> tuple[Optional[Fit], str]:
    """(the expiry's fit or None, why not): the last hour first, the whole session when that is too thin."""
    for window, use in (("last hour", [p for p in pts if p.late]), ("session", pts)):
        got = _try(use, sigma_ref)
        if got:
            xs, ys, f, dropped = got
            # the miss is reported over the rows the fit stands for: a row more than the screen's floor off its own
            # bin is a stale print, counted (outliers) but not let into the RMS
            res = [((p.iv - f(p.x)) * 100.0, p.volume) for p in use]
            core = [(e, w) for e, w in res if abs(e) <= SCREEN_FLOOR * 100 * 3] or res
            rms = math.sqrt(sum(e * e * w for e, w in core) / sum(w for _, w in core))
            return Fit(expiry, window, xs, ys, len(use), rms, max(abs(e) for e, _ in core), f, dropped,
                       len(res) - len(core)), ""
        if window == "session" or len(use) == len(pts):
            break
    b = bins(pts, sigma_ref)
    return None, (f"{len(pts)} usable rows in {len(b)} bins ({sum(x < 0 for x, _, _ in b)} below the money, "
                  f"{sum(x > 0 for x, _, _ in b)} above); {MIN_BINS} bins with {MIN_SIDE} on each side are needed")


def moneyness(k: float, s0: float, t0: float, r: float, q: float) -> float:
    return math.log(k / (s0 * math.exp((r - q) * t0))) / math.sqrt(t0)


def surface_iv(fits: list[tuple[float, Fit]], t0: float, x0: float, own: Optional[Fit] = None) -> Optional[float]:
    """IV at time-to-expiry t0 and moneyness x0: the expiry's own fit, else total variance linear in time at the same
    x0 between the nearest fitted expiries [(T_i now, fit_i)] around t0, else the nearest one's IV at x0."""
    if own is not None:
        return own.iv(x0)
    if not fits:
        return None
    fits = sorted(fits, key=lambda tf: tf[0])
    before = [tf for tf in fits if tf[0] <= t0]
    after = [tf for tf in fits if tf[0] > t0]
    if before and after:
        (ta, fa), (tb, fb) = before[-1], after[0]
        wa, wb = fa.iv(x0) ** 2 * ta, fb.iv(x0) ** 2 * tb
        w = wa + (wb - wa) * (t0 - ta) / (tb - ta)
        return math.sqrt(max(w, 0.0) / t0)
    return (before[-1] if before else after[0])[1].iv(x0)


@dataclass
class Surface:
    """One underlying's fitted expiries, priced at the current price and time (module docstring, "Today")."""
    fits: dict                                   # expiry time -> Fit
    r: float
    q: float
    anchor: Callable[[float], float] = lambda t: 1.0      # a(T0): 1 unless the Greeks lag a session

    def iv(self, expiry: datetime, k: float, s0: float, now: datetime) -> Optional[float]:
        t0 = (expiry - now).total_seconds() / YEAR_S
        if t0 <= 0 or k <= 0 or s0 <= 0 or not self.fits:
            return None
        x0 = moneyness(k, s0, t0, self.r, self.q)
        live = [((e - now).total_seconds() / YEAR_S, f) for e, f in self.fits.items() if e > now]
        v = surface_iv(live, t0, x0, self.fits.get(expiry))
        return None if v is None else v * self.anchor(t0)
