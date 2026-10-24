"""Gamma-exposure (GEX) calculation engine.

Conventions (see docs/METHODOLOGY.md for the full derivation)
-------------------------------------------------------------
For one contract i:

    base_i = s_i * OI_i * Gamma_i * M_i          change in underlying-equivalent delta per 1.0 point

    UNIT "delta_per_point" :  base_i
    UNIT "usd_per_point"   :  base_i * S          change in dollar delta per 1.0 point move
    UNIT "usd_per_1pct"    :  base_i * S * S * 0.01   change in dollar delta for a 1% move (default)

M_i is "notional units per point of underlying": 100 shares for SPX/NDX/SPY/QQQ
options, $50 for ES options, $20 for NQ options.  With that definition the same
formula yields dollars for equity-style and futures options alike.

s_i is the *assumed* dealer positioning sign.  Public open interest does not
reveal who is long or short; every sign convention is a modelling assumption.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .models import ChainSnapshot, OptionContract, OptionType, Quality, SourceKind
from . import pricing

YEAR_SECONDS = 365.0 * 24 * 3600

POSITIONING_MODELS = {
    # name: (call sign, put sign, description)
    "conventional": (1.0, -1.0, "Conventional approximation: dealers assumed long call gamma, short put gamma "
                                "(customers assumed to sell calls / buy puts). NOT observed positioning."),
    "dealer_short_all": (-1.0, -1.0, "Dealers assumed short all options (customers net long calls and puts)."),
    "dealer_long_all": (1.0, 1.0, "Dealers assumed long all options (customers net short calls and puts)."),
}

UNITS = {
    "usd_per_1pct": "USD change in dealer delta for a 1% underlying move",
    "usd_per_point": "USD change in dealer delta for a 1.0 point underlying move",
    "delta_per_point": "Underlying-equivalent units of delta change per 1.0 point move",
}


class ConfigError(ValueError):
    pass


@dataclass
class EngineConfig:
    positioning: str = "conventional"
    call_sign: Optional[float] = None       # only for positioning == "custom"
    put_sign: Optional[float] = None
    unit: str = "usd_per_1pct"
    include_0dte: bool = True
    max_dte: float = 45.0                   # calendar days
    expirations: Optional[list[str]] = None  # explicit ISO dates (YYYY-MM-DD); overrides max_dte
    grid_pct: float = 0.05                  # zero-gamma search range: spot * (1 +/- grid_pct)
    grid_steps: int = 201
    regime_band: float = 0.05               # |net|/gross below this -> INDETERMINATE
    zero_gamma_band_pct: float = 0.0015     # spot within this of zero gamma -> INDETERMINATE
    max_spot_age_s: float = 900.0
    min_profile_coverage: float = 0.8       # share of gross GEX that must be re-priceable for zero gamma
    recompute_greeks: str = "missing_only"  # missing_only | always
    max_far_share: float = 0.5              # >this share of gross from strikes >10% away -> data implausible

    def signs(self) -> tuple[float, float]:
        if self.positioning == "custom":
            if self.call_sign is None or self.put_sign is None:
                raise ConfigError("positioning='custom' requires call_sign and put_sign")
            if self.call_sign not in (-1.0, 1.0, -1, 1) or self.put_sign not in (-1.0, 1.0, -1, 1):
                raise ConfigError("custom signs must be +1 or -1")
            return float(self.call_sign), float(self.put_sign)
        if self.positioning not in POSITIONING_MODELS:
            raise ConfigError(f"unknown positioning model {self.positioning!r}; "
                              f"choose one of {sorted(POSITIONING_MODELS) + ['custom']}")
        c, p, _ = POSITIONING_MODELS[self.positioning]
        return c, p

    def validate(self) -> None:
        self.signs()
        if self.unit not in UNITS:
            raise ConfigError(f"unknown unit {self.unit!r}; choose one of {sorted(UNITS)}")
        if not 0 < self.grid_pct <= 0.5:
            raise ConfigError("grid_pct must be in (0, 0.5]")
        if self.grid_steps < 11:
            raise ConfigError("grid_steps must be >= 11")
        if self.max_dte < 0:
            raise ConfigError("max_dte must be >= 0")
        if self.recompute_greeks not in ("missing_only", "always"):
            raise ConfigError("recompute_greeks must be 'missing_only' or 'always'")
        if self.expirations:
            for e in self.expirations:
                try:
                    datetime.strptime(e, "%Y-%m-%d")
                except ValueError as ex:
                    raise ConfigError(f"invalid expiration {e!r}: expected YYYY-MM-DD") from ex


def unit_scale(unit: str, s: float) -> float:
    if unit == "delta_per_point":
        return 1.0
    if unit == "usd_per_point":
        return s
    if unit == "usd_per_1pct":
        return s * s * 0.01
    raise ConfigError(f"unknown unit {unit!r}")


def convert_units(value: float, from_unit: str, to_unit: str, s: float) -> float:
    """Convert an aggregate exposure between units at the same reference price s."""
    return value / unit_scale(from_unit, s) * unit_scale(to_unit, s)


@dataclass
class ContractExposure:
    contract: OptionContract
    t_years: float
    dte: float
    gamma: float
    gamma_quality: Quality
    iv: Optional[float]
    sign: float
    exposure: float


@dataclass
class GexResult:
    underlying: str
    source_kind: str
    source: str
    asof: datetime
    spot: float
    spot_quality: str
    unit: str
    positioning: str
    positioning_note: str
    basket: list[str]
    rows: list[ContractExposure]
    by_strike: dict[float, dict]
    by_expiry: dict[str, dict]
    by_dte_bucket: dict[str, dict]
    totals: dict
    profile: list[tuple[float, float]]
    profile_coverage: float
    zero_gamma: Optional[float]
    zero_gamma_crossings: list[float]
    zero_gamma_status: str
    regime: str
    expected_move: Optional[dict]
    gamma_weighted_distance: Optional[float]
    near_spot_concentration: Optional[float]
    excluded: dict
    warnings: list[str] = field(default_factory=list)
    status: str = "OK"   # OK | DEGRADED | UNAVAILABLE


DTE_BUCKETS = [("0DTE", 0, 1), ("1DTE", 1, 2), ("2-7D", 2, 8), ("8-30D", 8, 31), ("31D+", 31, 10_000)]


def _bucket(dte_days: float) -> str:
    whole = math.floor(dte_days)
    for name, lo, hi in DTE_BUCKETS:
        if lo <= whole < hi:
            return name
    return "31D+"


def _is_futures(snap: ChainSnapshot) -> bool:
    return snap.source_kind == SourceKind.FUTURES


def _contract_gamma_at(c: OptionContract, s: float, t: float, iv: float, snap: ChainSnapshot) -> float:
    return pricing.model_gamma(s, c.strike, t, snap.rate, snap.div_yield, iv, _is_futures(snap))


def _solve_iv(c: OptionContract, s: float, t: float, snap: ChainSnapshot) -> Optional[float]:
    mid = c.mid
    if mid is None:
        return None
    q = snap.rate if _is_futures(snap) else snap.div_yield
    return pricing.implied_vol(mid, s, c.strike, t, snap.rate, q, c.option_type == OptionType.CALL)


def select_basket(snap: ChainSnapshot, cfg: EngineConfig, asof: datetime) -> list[datetime]:
    exps = []
    explicit = set(cfg.expirations or [])
    for e in snap.expirations():
        t = (e - asof).total_seconds()
        if t <= 0:
            continue
        dte = t / 86400.0
        is_0dte = e.date() == asof.astimezone(e.tzinfo).date()
        if explicit:
            if e.date().isoformat() in explicit:
                exps.append(e)
            continue
        if is_0dte and not cfg.include_0dte:
            continue
        if dte <= cfg.max_dte + 1e-9:
            exps.append(e)
    return exps


def compute(snap: ChainSnapshot, cfg: Optional[EngineConfig] = None, asof: Optional[datetime] = None) -> GexResult:
    cfg = cfg or EngineConfig()
    cfg.validate()
    asof = asof or snap.fetched_at
    if asof.tzinfo is None:
        raise ConfigError("asof must be timezone-aware")
    call_sign, put_sign = cfg.signs()
    pos_note = POSITIONING_MODELS.get(cfg.positioning, (0, 0, f"Custom signs: calls {call_sign:+.0f}, puts {put_sign:+.0f}"))[2]
    warnings = list(snap.warnings)
    excluded = {"zero_or_missing_oi": 0, "missing_greeks": 0, "expired_or_outside_basket": 0}

    if snap.spot is None or snap.spot <= 0 or not math.isfinite(snap.spot):
        return _unavailable(snap, cfg, asof, pos_note, "underlying reference price unavailable")
    s = snap.spot
    if snap.spot_time is not None and (asof - snap.spot_time).total_seconds() > cfg.max_spot_age_s:
        warnings.append(f"underlying price is stale ({(asof - snap.spot_time).total_seconds():.0f}s old)")
    if snap.spot_quality == Quality.SYNTHETIC and "SYNTHETIC data - not market data" not in warnings:
        warnings.append("SYNTHETIC data - not market data")

    basket = select_basket(snap, cfg, asof)
    basket_set = set(basket)
    if not basket:
        return _unavailable(snap, cfg, asof, pos_note, "no expirations in selected basket")

    rows: list[ContractExposure] = []
    scale = unit_scale(cfg.unit, s)
    # each expiration's quoted IVs by strike: the fallback when a contract has neither an IV nor a
    # solvable mid (typically deep in the money, where the mid sits below intrinsic value)
    smile: dict[datetime, list[tuple[float, float]]] = {}
    n_borrowed = 0
    for c in snap.contracts:
        if c.iv is not None and c.iv > 0 and c.expiration in basket_set:
            smile.setdefault(c.expiration, []).append((c.strike, c.iv))
    for c in snap.contracts:
        if c.expiration not in basket_set:
            excluded["expired_or_outside_basket"] += 1
            continue
        if c.open_interest is None or c.open_interest <= 0:
            excluded["zero_or_missing_oi"] += 1
            continue
        t = (c.expiration - asof).total_seconds() / YEAR_SECONDS
        iv = c.iv
        gamma, gq = c.gamma, c.greeks_quality
        need = gamma is None or cfg.recompute_greeks == "always"
        if need:
            if iv is None:
                iv = _solve_iv(c, s, t, snap)
            if iv is None and smile.get(c.expiration):
                iv = min(smile[c.expiration], key=lambda kv: abs(kv[0] - c.strike))[1]
                n_borrowed += 1
            if iv is not None and iv > 0:
                gamma, gq = _contract_gamma_at(c, s, t, iv, snap), Quality.MODEL_CALC
            elif cfg.recompute_greeks == "always":
                gamma = None              # never fall back to the vendor's rounded gamma in this mode
        if gamma is None or not math.isfinite(gamma) or gamma < 0:
            excluded["missing_greeks"] += 1
            continue
        sign = call_sign if c.option_type == OptionType.CALL else put_sign
        exp_val = sign * c.open_interest * gamma * c.multiplier * scale
        rows.append(ContractExposure(c, t, t * 365.0, gamma, gq, iv, sign, exp_val))

    if not rows:
        return _unavailable(snap, cfg, asof, pos_note, "no contracts with both open interest and gamma")
    # Plausibility guard: real chains concentrate gamma near the money.  If most exposure sits far
    # away, the source's OI/IV near the money is missing or broken (e.g. a feed blanked overnight) - refuse.
    gross0 = sum(abs(r.exposure) for r in rows)
    far = sum(abs(r.exposure) for r in rows if abs(r.contract.strike / s - 1.0) > 0.10)
    if gross0 > 0 and far / gross0 > cfg.max_far_share:
        return _unavailable(snap, cfg, asof, pos_note,
                            f"data implausible: {far / gross0:.0%} of exposure is >10% from price "
                            "(near-the-money open interest/IV missing at this source)")

    by_strike: dict[float, dict] = {}
    by_expiry: dict[str, dict] = {}
    by_bucket: dict[str, dict] = {}
    for r in rows:
        k = r.contract.level_strike
        d = by_strike.setdefault(k, {"call": 0.0, "put": 0.0, "net": 0.0, "abs": 0.0, "call_oi": 0.0, "put_oi": 0.0})
        side = "call" if r.contract.option_type == OptionType.CALL else "put"
        d[side] += r.exposure
        d[side + "_oi"] += r.contract.open_interest
        d["net"] += r.exposure
        d["abs"] += abs(r.exposure)
        ek = r.contract.expiration.date().isoformat()
        e = by_expiry.setdefault(ek, {"call": 0.0, "put": 0.0, "net": 0.0, "abs": 0.0, "dte": round(r.dte, 3)})
        e[side] += r.exposure
        e["net"] += r.exposure
        e["abs"] += abs(r.exposure)
        b = by_bucket.setdefault(_bucket(r.dte), {"net": 0.0, "abs": 0.0})
        b["net"] += r.exposure
        b["abs"] += abs(r.exposure)
    by_strike = dict(sorted(by_strike.items()))

    nets = [v["net"] for v in by_strike.values()]
    gross = sum(abs(r.exposure) for r in rows)
    totals = {
        "net": sum(r.exposure for r in rows),
        "call": sum(r.exposure for r in rows if r.contract.option_type == OptionType.CALL),
        "put": sum(r.exposure for r in rows if r.contract.option_type == OptionType.PUT),
        "gross": gross,
        "positive_strikes_sum": sum(n for n in nets if n > 0),
        "negative_strikes_sum": sum(n for n in nets if n < 0),
        "contracts_used": len(rows),
    }
    # gamma density: net exposure per point of strike spacing (comparable across grids)
    strikes = list(by_strike)
    for i, k in enumerate(strikes):
        lo = strikes[i - 1] if i > 0 else None
        hi = strikes[i + 1] if i + 1 < len(strikes) else None
        gaps = [g for g in ((k - lo) if lo else None, (hi - k) if hi else None) if g]
        spacing = sum(gaps) / len(gaps) if gaps else 1.0
        by_strike[k]["density_per_point"] = by_strike[k]["net"] / spacing

    profile, coverage = gamma_profile(rows, snap, cfg, s)
    crossings = find_crossings(profile)
    if coverage < cfg.min_profile_coverage:
        zg, zg_status = None, f"UNAVAILABLE: only {coverage:.0%} of gross GEX has IV for re-pricing"
        warnings.append(zg_status)
    elif not crossings:
        zg, zg_status = None, f"NO CROSSING within +/-{cfg.grid_pct:.1%} of reference"
    else:
        zg = min(crossings, key=lambda x: abs(x - s))
        zg_status = "ESTIMATE" if len(crossings) == 1 else f"ESTIMATE ({len(crossings)} crossings; nearest to reference selected)"

    regime = classify_regime(totals["net"], gross, s, zg, cfg)
    em = expected_move(rows, snap, s, asof)
    gw = sum(abs(v["net"]) * abs(k - s) for k, v in by_strike.items())
    gabs = sum(abs(v["net"]) for v in by_strike.values())
    near = sum(v["abs"] for k, v in by_strike.items() if abs(k - s) <= 0.01 * s)

    status = "OK"
    if excluded["missing_greeks"] > 0:
        warnings.append(f"{excluded['missing_greeks']} contracts excluded for missing Greeks/IV")
    if n_borrowed:
        warnings.append(f"{n_borrowed} contracts without a usable IV used the nearest strike's IV (same expiration)")
    if any("stale" in w for w in warnings) or coverage < cfg.min_profile_coverage:
        status = "DEGRADED"

    return GexResult(
        underlying=snap.underlying, source_kind=snap.source_kind.value, source=snap.source, asof=asof,
        spot=s, spot_quality=snap.spot_quality.value, unit=cfg.unit, positioning=cfg.positioning,
        positioning_note=pos_note, basket=[e.date().isoformat() for e in basket], rows=rows,
        by_strike=by_strike, by_expiry=by_expiry, by_dte_bucket=by_bucket, totals=totals,
        profile=profile, profile_coverage=coverage, zero_gamma=zg, zero_gamma_crossings=crossings,
        zero_gamma_status=zg_status, regime=regime, expected_move=em,
        gamma_weighted_distance=(gw / gabs) if gabs else None,
        near_spot_concentration=(near / gross) if gross else None,
        excluded=excluded, warnings=warnings, status=status,
    )


def gamma_profile(rows: list[ContractExposure], snap: ChainSnapshot, cfg: EngineConfig,
                  s: float) -> tuple[list[tuple[float, float]], float]:
    """Net modeled exposure as a function of a hypothetical underlying price.

    Method: sticky-strike.  Each contract keeps its implied volatility and time
    to expiry (no decay over the grid); gamma is *recomputed* with the pricing
    model at every grid price P, and the unit scale uses P.  Open interest and
    positioning signs are held constant.
    """
    priceable = [r for r in rows if r.iv is not None and r.iv > 0]
    gross = sum(abs(r.exposure) for r in rows)
    coverage = (sum(abs(r.exposure) for r in priceable) / gross) if gross else 0.0
    lo, hi = s * (1 - cfg.grid_pct), s * (1 + cfg.grid_pct)
    n = cfg.grid_steps
    out = []
    for i in range(n):
        p = lo + (hi - lo) * i / (n - 1)
        sc = unit_scale(cfg.unit, p)
        tot = 0.0
        for r in priceable:
            g = _contract_gamma_at(r.contract, p, r.t_years, r.iv, snap)
            tot += r.sign * r.contract.open_interest * g * r.contract.multiplier * sc
        out.append((p, tot))
    return out, coverage


def find_crossings(profile: list[tuple[float, float]]) -> list[float]:
    """Prices where the profile changes sign, by linear interpolation between grid points."""
    xs = []
    for (p0, v0), (p1, v1) in zip(profile, profile[1:]):
        if v0 == 0.0:
            if not xs or abs(xs[-1] - p0) > 1e-9:
                xs.append(p0)
            continue
        if v0 * v1 < 0:
            xs.append(p0 + (p1 - p0) * (-v0) / (v1 - v0))
    return xs


def classify_regime(net: float, gross: float, s: float, zg: Optional[float], cfg: EngineConfig) -> str:
    if gross <= 0:
        return "INDETERMINATE"
    if abs(net) / gross < cfg.regime_band:
        return "INDETERMINATE"
    if zg is not None and abs(s - zg) / s < cfg.zero_gamma_band_pct:
        return "INDETERMINATE"
    return "POSITIVE" if net > 0 else "NEGATIVE"


def expected_move(rows: list[ContractExposure], snap: ChainSnapshot, s: float, asof: datetime) -> Optional[dict]:
    """1-sigma move to the nearest expiry from ATM IV, plus ATM straddle mid when quoted."""
    if not rows:
        return None
    nearest = min(r.contract.expiration for r in rows)
    sub = [r for r in rows if r.contract.expiration == nearest]
    # nearest strike with both a call and a put: one side alone can carry a skewed vendor IV
    both = ({r.contract.strike for r in sub if r.contract.option_type == OptionType.CALL and r.iv}
            & {r.contract.strike for r in sub if r.contract.option_type == OptionType.PUT and r.iv})
    atm_k = min(both or {r.contract.strike for r in sub}, key=lambda k: abs(k - s))
    atm = [r for r in sub if r.contract.strike == atm_k]
    ivs = [r.iv for r in atm if r.iv]
    t = atm[0].t_years
    out = {"expiration": nearest.date().isoformat(), "atm_strike": atm_k, "t_years": t}
    if ivs:
        iv = sum(ivs) / len(ivs)
        out.update({"atm_iv": iv, "one_sigma_points": s * iv * math.sqrt(t)})
    mids = {r.contract.option_type: r.contract.mid for r in atm}
    if mids.get(OptionType.CALL) is not None and mids.get(OptionType.PUT) is not None:
        out["straddle_mid_points"] = mids[OptionType.CALL] + mids[OptionType.PUT]
    return out if len(out) > 3 else None


def _unavailable(snap, cfg, asof, pos_note, reason) -> GexResult:
    return GexResult(
        underlying=snap.underlying, source_kind=snap.source_kind.value, source=snap.source, asof=asof,
        spot=snap.spot or float("nan"), spot_quality=snap.spot_quality.value, unit=cfg.unit,
        positioning=cfg.positioning, positioning_note=pos_note, basket=[], rows=[], by_strike={},
        by_expiry={}, by_dte_bucket={}, totals={"net": None, "gross": None}, profile=[], profile_coverage=0.0,
        zero_gamma=None, zero_gamma_crossings=[], zero_gamma_status="UNAVAILABLE", regime="UNAVAILABLE",
        expected_move=None, gamma_weighted_distance=None, near_spot_concentration=None,
        excluded={}, warnings=list(snap.warnings) + [reason], status="UNAVAILABLE",
    )


def diff(prev: dict, cur: dict) -> dict:
    """Compare two level summaries (as produced by levels.summarize)."""
    out = {}
    for key in ("zero_gamma", "call_wall", "put_wall", "max_positive", "max_negative"):
        a, b = _lvl(prev, key), _lvl(cur, key)
        out[key] = None if a is None or b is None else b - a
    pn, cn = prev.get("net"), cur.get("net")
    out["net_change"] = None if pn is None or cn is None else cn - pn
    out["regime_changed"] = prev.get("regime") != cur.get("regime")
    out["prev_regime"] = prev.get("regime")
    # concentration shift: total-variation distance between normalized |net| by strike
    pa, ca = prev.get("abs_by_strike") or {}, cur.get("abs_by_strike") or {}
    sp, sc = sum(pa.values()), sum(ca.values())
    if sp > 0 and sc > 0:
        keys = set(pa) | set(ca)
        out["concentration_shift"] = 0.5 * sum(abs(pa.get(k, 0) / sp - ca.get(k, 0) / sc) for k in keys)
    else:
        out["concentration_shift"] = None
    return out


def _lvl(d: dict, key: str) -> Optional[float]:
    v = d.get(key)
    if isinstance(v, dict):
        return v.get("price")
    return v
