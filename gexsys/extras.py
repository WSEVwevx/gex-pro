"""Additional options levels beyond the core GEX set.

All prices are in the options-underlying space (mapped to futures in mapping.py).

* 0DTE / next-expiration levels - the core GEX levels recomputed on the NEAREST expiration in
  the basket only.  Labeled "0DTE" only when it expires today (ET), else "next <MM-DD>".
* Volume walls - strikes within +/-5% of the reference price with the largest call / put VOLUME summed
  over the basket (calls at/above price, puts at/below, like the GEX walls).  Volume is
  today's (15-min delayed) and therefore moves intraday, unlike open interest (EOD).
  Outside the session it is the last session's volume.
* OI walls - strikes within +/-5% of the reference price with the largest raw call / put open interest
  (no gamma weighting).
* Max pain - per expiration, the settlement price that minimises the total intrinsic value
  paid to option holders:  argmin_K* sum_calls OI*max(0,K*-K) + sum_puts OI*max(0,K-K*),
  searched over that expiration's strikes.  A popular statistic, not a price target.
* Expected-move bands - anchor +/- anchor * IV_atm * sqrt(N/252):
    daily : N = 1, IV of the nearest expiration with >= 1 calendar day left (avoids 0DTE decay
            distortion);
    weekly: N = trading days from the session date through this week's last expiration, IV of
            that expiration.
  Anchor = previous session close during RTH, the last close outside RTH (so the bands are fixed
  for the whole session instead of moving with every snapshot).
* GEX profile - net exposure aggregated into equal-width price bins around the reference price,
  scaled to integers -99..99 for compact transport to TradingView.
"""
from __future__ import annotations

import dataclasses
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from . import engine as eng
from . import marketcal, pricing
from .levels import LevelConfig, summarize
from .models import ChainSnapshot, OptionContract, OptionType

NICE_WIDTHS = (0.5, 1, 2, 2.5, 5, 10, 25, 50, 100, 250)


def _basket_contracts(snap: ChainSnapshot, basket: list[str]) -> list[OptionContract]:
    b = set(basket)
    return [c for c in snap.contracts if c.expiration.date().isoformat() in b]


def nearest_expiry_levels(snap: ChainSnapshot, cfg: eng.EngineConfig, res: eng.GexResult) -> Optional[dict]:
    if not res.basket:
        return None
    exp0 = res.basket[0]
    today = res.asof.astimezone(marketcal.NY).date().isoformat()
    label = "0DTE" if exp0 == today else f"next {exp0[5:]}"
    sub = eng.compute(snap, dataclasses.replace(cfg, expirations=[exp0]), asof=res.asof)
    s = summarize(sub, LevelConfig(top_n=0))
    return {"expiration": exp0, "label": label, "status": sub.status,
            "zero_gamma": s["zero_gamma"], "call_wall": s["call_wall"], "put_wall": s["put_wall"],
            "net": s["net"], "regime": s["regime"]}


def _argmax_by_strike(contracts, typ: OptionType, attr: str) -> Optional[dict]:
    tot: dict[float, float] = defaultdict(float)
    for c in contracts:
        v = getattr(c, attr)
        if c.option_type == typ and v is not None and v > 0:
            tot[c.strike] += v
    if not tot:
        return None
    k = max(tot, key=lambda x: (tot[x], -x))
    return {"price": k, "value": tot[k], "metric": f"max {typ.name.lower()} {attr.replace('_', ' ')}"}


def volume_and_oi_walls(snap: ChainSnapshot, basket: list[str], window_pct: float = 0.05) -> dict:
    """Searched within +/-window_pct of the reference price: far-OTM hedges are real but not intraday levels."""
    s = snap.spot or 0.0
    cs = [c for c in _basket_contracts(snap, basket) if s and abs(c.strike / s - 1.0) <= window_pct]
    calls = [c for c in cs if c.strike >= s]     # same side rule as the GEX walls: calls at/above price,
    puts = [c for c in cs if c.strike <= s]      # puts at/below
    return {"vol_call": _argmax_by_strike(calls, OptionType.CALL, "volume"),
            "vol_put": _argmax_by_strike(puts, OptionType.PUT, "volume"),
            "oi_call": _argmax_by_strike(calls, OptionType.CALL, "open_interest"),
            "oi_put": _argmax_by_strike(puts, OptionType.PUT, "open_interest")}


def max_pain(contracts: list[OptionContract]) -> Optional[float]:
    """Strike minimising total intrinsic payout to holders (ties -> lower strike)."""
    calls = [(c.strike, c.open_interest) for c in contracts if c.option_type == OptionType.CALL and c.open_interest]
    puts = [(c.strike, c.open_interest) for c in contracts if c.option_type == OptionType.PUT and c.open_interest]
    strikes = sorted({k for k, _ in calls} | {k for k, _ in puts})
    if not strikes:
        return None
    best, best_pay = None, math.inf
    for s in strikes:
        pay = sum(oi * max(0.0, s - k) for k, oi in calls) + sum(oi * max(0.0, k - s) for k, oi in puts)
        if pay < best_pay - 1e-9:
            best, best_pay = s, pay
    return best


def max_pain_by_expiry(snap: ChainSnapshot, basket: list[str]) -> list[dict]:
    by: dict[str, list] = defaultdict(list)
    for c in _basket_contracts(snap, basket):
        by[c.expiration.date().isoformat()].append(c)
    out = []
    for e in sorted(by):
        mp = max_pain(by[e])
        if mp is not None:
            out.append({"expiration": e, "price": mp, "oi": sum(c.open_interest or 0 for c in by[e])})
    return out


def atm_iv(contracts: list[OptionContract], expiry: str, spot: float) -> Optional[float]:
    cs = [c for c in contracts if c.expiration.date().isoformat() == expiry and c.iv]
    if not cs:
        return None
    k = min({c.strike for c in cs}, key=lambda x: abs(x - spot))
    ivs = [c.iv for c in cs if c.strike == k]
    return sum(ivs) / len(ivs)


def session_date(asof: datetime) -> date:
    """The trading session the bands are for: today during/before RTH, else the next trading day."""
    t = asof.astimezone(marketcal.NY)
    d = t.date()
    if marketcal.is_trading_day(d) and t.time() < marketcal.rth_close(d):
        return d
    d += timedelta(days=1)
    while not marketcal.is_trading_day(d):
        d += timedelta(days=1)
    return d


def expected_moves(snap: ChainSnapshot, basket: list[str], asof: datetime, ivs_from: list[OptionContract]) -> Optional[dict]:
    if snap.spot is None or not basket:
        return None
    rth = marketcal.session_state(asof) == "RTH"
    anchor = snap.prev_close if (rth and snap.prev_close) else snap.spot
    anchor_kind = "previous close" if (rth and snap.prev_close) else "last close/price"
    sd = session_date(asof)
    out = {"anchor": anchor, "anchor_kind": anchor_kind, "session": sd.isoformat()}
    daily_exp = next((e for e in basket if date.fromisoformat(e) > asof.astimezone(marketcal.NY).date()), None)
    if daily_exp:
        iv = atm_iv(ivs_from, daily_exp, snap.spot)
        if iv:
            out.update(daily_points=anchor * iv * math.sqrt(1 / 252), daily_iv=iv, daily_iv_expiry=daily_exp)
    friday = sd + timedelta(days=(4 - sd.weekday()) % 7)
    weekly = [e for e in basket if sd <= date.fromisoformat(e) <= friday]
    if weekly:
        we = weekly[-1]
        n = sum(1 for i in range((date.fromisoformat(we) - sd).days + 1)
                if marketcal.is_trading_day(sd + timedelta(days=i)))
        iv = atm_iv(ivs_from, we, snap.spot)
        if iv and n > 0:
            out.update(weekly_points=anchor * iv * math.sqrt(n / 252), weekly_iv=iv, weekly_expiry=we, weekly_days=n)
    return out if len(out) > 3 else None


def profile_bins(res: eng.GexResult, window_pct: float = 0.025, target_bins: int = 40) -> Optional[dict]:
    """Net exposure in equal-width bins around the reference price, scaled to ints -99..99."""
    s = res.spot
    if not res.by_strike or not s or not math.isfinite(s):
        return None
    span = 2 * window_pct * s
    width = min(NICE_WIDTHS, key=lambda w: abs(span / w - target_bins))
    lo = math.floor((s * (1 - window_pct)) / width) * width
    n = int(math.ceil(span / width)) + 1
    vals = [0.0] * n
    for k, v in res.by_strike.items():
        i = int(round((k - lo) / width))
        if 0 <= i < n:
            vals[i] += v["net"]
    m = max((abs(v) for v in vals), default=0.0)
    if m <= 0:
        return None
    return {"base": lo, "width": width, "values": [int(round(99 * v / m)) for v in vals], "max_abs": m}


def greek_exposures(snap: ChainSnapshot, res: eng.GexResult) -> Optional[dict]:
    """Dealer vanna and charm exposure under the same positioning signs as GEX.

    vanna_usd_per_vol_pt = sum s*OI*M*vanna*S*0.01  -> change in dealer dollar delta if implied vol rises 1 point
    charm_usd_per_day    = sum s*OI*M*charm*S/365   -> change in dealer dollar delta per calendar day of decay
    Dealers stay hedged by trading the OPPOSITE of their delta change, so the implied hedge flow is the
    negative of each number (charm_flow_usd_per_day).  Only contracts with an IV contribute; coverage says how much.
    """
    s = res.spot
    rows = [r for r in res.rows if r.iv]
    if not rows or not s:
        return None
    futures = snap.source_kind.value == "FUT"
    q = snap.rate if futures else snap.div_yield
    vex = cex = 0.0
    for r in rows:
        c = r.contract
        w = r.sign * c.open_interest * c.multiplier * s
        vex += w * pricing.bsm_vanna(s, c.strike, r.t_years, snap.rate, q, r.iv) * 0.01
        cex += w * pricing.bsm_charm(s, c.strike, r.t_years, snap.rate, q, r.iv, c.option_type == OptionType.CALL) / 365.0
    gross = sum(abs(r.exposure) for r in res.rows)
    return {"vanna_usd_per_vol_pt": vex, "charm_usd_per_day": cex, "charm_flow_usd_per_day": -cex,
            "coverage": sum(abs(r.exposure) for r in rows) / gross if gross else 0.0}


def flow_ratios(snap: ChainSnapshot, basket: list[str]) -> dict:
    """Put/call open interest and volume over the basket, plus 0DTE's share of today's volume."""
    cs = _basket_contracts(snap, basket)
    tot = {(t, a): sum((getattr(c, a) or 0.0) for c in cs if c.option_type == t)
           for t in (OptionType.CALL, OptionType.PUT) for a in ("open_interest", "volume")}
    c_oi, p_oi = tot[(OptionType.CALL, "open_interest")], tot[(OptionType.PUT, "open_interest")]
    c_v, p_v = tot[(OptionType.CALL, "volume")], tot[(OptionType.PUT, "volume")]
    first = basket[0] if basket else None
    vol0 = sum((c.volume or 0.0) for c in cs if first and c.expiration.date().isoformat() == first)
    return {"call_oi": c_oi, "put_oi": p_oi, "pc_oi": p_oi / c_oi if c_oi else None,
            "call_volume": c_v, "put_volume": p_v, "pc_volume": p_v / c_v if c_v else None,
            "nearest_volume_share": vol0 / (c_v + p_v) if (c_v + p_v) else None}


def compute_extras(snap: ChainSnapshot, cfg: eng.EngineConfig, res: eng.GexResult) -> dict:
    if res.status == "UNAVAILABLE":
        return {}
    basket_cs = _basket_contracts(snap, res.basket)
    # IVs for the bands: the engine's own (vendor IV or solved), so contracts with solved IV count too
    with_iv = [r.contract if r.contract.iv else dataclasses.replace(r.contract, iv=r.iv) for r in res.rows if r.iv]
    return {
        "nearest": nearest_expiry_levels(snap, cfg, res),
        **volume_and_oi_walls(snap, res.basket),
        "max_pain": max_pain_by_expiry(snap, res.basket),
        "expected_move": expected_moves(snap, res.basket, res.asof, with_iv or basket_cs),
        "profile": profile_bins(res),
        "ratios": flow_ratios(snap, res.basket),
        "greeks": greek_exposures(snap, res),
    }
