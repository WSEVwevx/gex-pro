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
* Expected-move bands - from implied total variance, w(e) = IV_atm(e)^2 * T(e), with T in calendar
  years exactly as the IVs are annualized (so no 252-vs-365 mismatch):
    daily : variance of one full session. Outside RTH: w of the expiration that settles at the next
            session's close (it covers exactly the overnight plus that session). During RTH: the
            forward variance w(next session) - w(today) between the two session-close expirations.
            Without daily expirations: w(first expiration) / sessions until it.
    weekly: through this week's last expiration: w(that expiration) outside RTH; during RTH today's
            full-session variance plus w(week) - w(today).
  1-sd points = price * sqrt(variance). Anchor = previous session close during RTH, the last close
  outside RTH (so the bands are fixed for the whole session instead of moving with every snapshot).
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
            tot[c.level_strike] += v
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
    # candidate settlement prices: the listed (level) strikes; payouts use each contract's exact strike
    strikes = sorted({c.level_strike for c in contracts if c.open_interest})
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
    own = [c for c in cs if c.group_strike is None]     # the index's own options; converted ETF ones only as fallback
    cs = own or cs
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


def _session_close_expiry(w: dict, d: date) -> Optional[datetime]:
    """The expiration settling at the close of session d (the latest one dated d)."""
    return max((e for e in w if e.astimezone(marketcal.NY).date() == d), default=None)


def _sessions(first: date, last: date) -> int:
    return sum(1 for i in range((last - first).days + 1) if marketcal.is_trading_day(first + timedelta(days=i)))


def expected_moves(snap: ChainSnapshot, basket: list[str], asof: datetime, ivs_from: list[OptionContract]) -> Optional[dict]:
    if snap.spot is None or not basket:
        return None
    rth = marketcal.session_state(asof) == "RTH"
    anchor = snap.prev_close if (rth and snap.prev_close) else snap.spot
    anchor_kind = "previous close" if (rth and snap.prev_close) else "last close/price"
    sd = session_date(asof)
    out = {"anchor": anchor, "anchor_kind": anchor_kind, "session": sd.isoformat()}
    # implied total variance to each expiration: ATM IV^2 x calendar years remaining
    b = set(basket)
    days = sorted({c.expiration.date().isoformat() for c in ivs_from if c.iv and c.expiration > asof
                   and c.expiration.date().isoformat() in b})
    w, iv_of = {}, {}
    for e in sorted({c.expiration for c in ivs_from if c.iv and c.expiration > asof and c.expiration.date().isoformat() in b}):
        iv = atm_iv([c for c in ivs_from if c.expiration == e], e.date().isoformat(), snap.spot)
        if iv:
            w[e], iv_of[e] = iv * iv * (e - asof).total_seconds() / eng.YEAR_SECONDS, iv
    if not w or not days:
        return out if len(out) > 3 else None
    nxt = sd + timedelta(days=1)
    while not marketcal.is_trading_day(nxt):
        nxt += timedelta(days=1)
    e_today = _session_close_expiry(w, sd) if rth else None
    e_next = _session_close_expiry(w, nxt if rth else sd)
    dvar, used = None, None
    if rth and e_today and e_next and w[e_next] > w[e_today]:
        dvar, used, method = w[e_next] - w[e_today], e_next, "forward variance between session expirations"
    elif not rth and e_next:
        dvar, used, method = w[e_next], e_next, "variance to the next session's expiration"
    if dvar is None:
        used = min(w)
        n = _sessions(sd, used.astimezone(marketcal.NY).date())
        dvar, method = w[used] / max(n, 1), f"average per session over {max(n, 1)} sessions"
    out.update(daily_points=snap.spot * math.sqrt(dvar), daily_iv=iv_of[used],
               daily_iv_expiry=used.date().isoformat(), daily_method=method)
    friday = sd + timedelta(days=(4 - sd.weekday()) % 7)
    weekly = [e for e in w if sd <= e.astimezone(marketcal.NY).date() <= friday]
    if weekly:
        we = max(weekly)
        if rth and e_today:
            wvar = dvar + max(0.0, w[we] - w[e_today])      # today's full session + the rest of the week
        else:
            wvar = w[we] if not rth else max(w[we], dvar)
        out.update(weekly_points=snap.spot * math.sqrt(wvar), weekly_iv=iv_of[we],
                   weekly_expiry=we.date().isoformat(), weekly_days=_sessions(sd, we.astimezone(marketcal.NY).date()))
    return out


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


def term_structure(snap: ChainSnapshot, res: eng.GexResult, max_n: int = 12) -> list[dict]:
    """Per expiration: ATM IV, and the IVs of the ~25-delta put and call (BSM delta at the reference
    price with each option's own IV). skew_pts = put25 - call25 in vol points: how much more downside
    protection costs than upside. The index's own options are used when present (ETF ones otherwise)."""
    s = snap.spot
    if not s or not res.basket:
        return []
    b = set(res.basket)
    q = snap.rate if snap.source_kind.value == "FUT" else snap.div_yield
    exps = sorted({c.expiration for c in snap.contracts if c.iv and c.expiration > res.asof
                   and c.expiration.date().isoformat() in b})
    out = []
    for e in exps[:max_n]:
        cs = [c for c in snap.contracts if c.expiration == e and c.iv]
        cs = [c for c in cs if c.group_strike is None] or cs
        t = (e - res.asof).total_seconds() / eng.YEAR_SECONDS
        atm = atm_iv(cs, e.date().isoformat(), s)

        def wing(is_call: bool):
            best = None
            for c in cs:
                if (c.option_type == OptionType.CALL) != is_call:
                    continue
                d = pricing.bsm_delta(s, c.strike, t, snap.rate, q, c.iv, is_call)
                if 0.10 <= abs(d) <= 0.40 and (best is None or abs(abs(d) - 0.25) < abs(abs(best[0]) - 0.25)):
                    best = (d, c)
            return best
        p25, c25 = wing(False), wing(True)
        out.append({"expiration": e.date().isoformat(), "settle": e.astimezone(marketcal.NY).strftime("%H:%M"),
                    "dte": round(t * 365, 2), "atm_iv": atm,
                    "put25_iv": p25[1].iv if p25 else None, "put25_strike": p25[1].strike if p25 else None,
                    "call25_iv": c25[1].iv if c25 else None, "call25_strike": c25[1].strike if c25 else None,
                    "skew_pts": (p25[1].iv - c25[1].iv) * 100 if p25 and c25 else None})
    return out


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
        "term": term_structure(snap, res),
    }
