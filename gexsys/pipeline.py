"""One end-to-end calculation cycle: fetch -> normalize -> GEX -> levels ->
mapping -> diff -> Pine payload -> store -> alerts."""
from __future__ import annotations

import dataclasses
import logging
from datetime import datetime, timezone
from typing import Optional

from . import engine as eng
from .alerts import AlertEngine
from .config import MarketConfig
from .export import pine_payload
from .ladder import build_ladder
from .bias import compute as compute_bias
from .extras import compute_extras
from .levels import summarize
from .mapping import FUTURES, SOURCES, MappingContext, MappingError, map_summary
from .marketcal import session_state
from .models import Quality
from .normalize import normalize
from .storage import SnapshotStore

log = logging.getLogger(__name__)


def _carry(cfg: MarketConfig, s, st, note: str = "") -> Optional[tuple]:
    from .basis import carry_fair_value
    fv = carry_fair_value(cfg.market, cfg.source, s, st, cfg.futures_ref.get("rate"), cfg.futures_ref.get("div_yield"))
    if not fv:
        return None
    fp, code, r, q = fv
    return fp, st, f"carry-model fair value for {code} (r {r:.2%}, dividend {q:.2%}){note}; market price differs by a few points", s, st


def _futures_ref(cfg: MarketConfig, snap, override: Optional[tuple], provider=None) -> tuple:
    """(futures price, futures time, mode, source price, source time) used for the basis."""
    s, st = snap.spot, snap.spot_time
    if override:
        return override[0], override[1], "manual", s, st
    mode = cfg.futures_ref.get("mode", "none")
    if mode == "manual" and cfg.futures_ref.get("price"):
        t = cfg.futures_ref.get("time")
        return float(cfg.futures_ref["price"]), datetime.fromisoformat(t) if t else st, "manual", s, st
    if mode == "synthetic_basis" and s:
        return s * float(cfg.futures_ref.get("factor", 1.0105)), st, "synthetic", s, st
    if mode == "carry" and s and st:
        c = _carry(cfg, s, st)
        if c:
            return c
    return None, None, "none", s, st


def run_once(cfg: MarketConfig, provider, store: Optional[SnapshotStore] = None,
             alerts: Optional[AlertEngine] = None, futures_ref: Optional[tuple] = None) -> dict:
    src = SOURCES[cfg.source]
    snap = provider.fetch_snapshot(cfg.source, cfg.engine.max_dte, cfg.engine.include_0dte)
    snap = normalize(snap, check_occ=getattr(provider, "name", "") == "cboe")
    ecfg = cfg.engine
    if src.kind.value != "FUT" and session_state(snap.fetched_at) != "RTH":
        # cash index / ETF is not trading: its last close is the correct reference, not "stale"
        ecfg = dataclasses.replace(cfg.engine, max_spot_age_s=4 * 86400)
        snap.warnings.append("cash market closed - reference is the last close; levels from last session's data")
    res = eng.compute(snap, ecfg, asof=snap.fetched_at)
    summary = summarize(res, cfg.levels)
    summary["extras"] = compute_extras(snap, ecfg, res)
    summary["market"] = cfg.market
    summary["options_source"] = cfg.source
    summary["tv_ref_symbol"] = src.tv_symbol
    summary["ref_time"] = snap.spot_time.isoformat() if snap.spot_time else None

    summary["etf"] = next((c.root for c in snap.contracts if c.group_strike is not None), None)
    summary["provider"] = getattr(provider, "last_label", None) or getattr(provider, "label", getattr(provider, "name", "?").upper())
    mapped, map_note = None, ""
    fprice, ftime, fmode, sprice, stime = _futures_ref(cfg, snap, futures_ref, provider)
    method = cfg.method
    try:
        ctx = MappingContext(cfg.market, cfg.source, method, fprice, ftime, sprice, stime,
                             max_skew_s=float(cfg.mapping.get("max_skew_s", 60)),
                             calendar_spread=cfg.mapping.get("calendar_spread"))
        if method in ("ratio", "offset") and fprice is None:
            map_note = "no futures reference in service; mapping is done live in TradingView"
        elif res.status != "UNAVAILABLE":
            mapped = map_summary(summary, ctx)
            mapped["mapping"]["futures_ref_mode"] = fmode
            # futures-space equivalent of the options reference price (for distances on the website)
            mapped["futures_equiv_of_ref"] = ctx.map_price(snap.spot)
    except MappingError as e:
        map_note = f"mapping refused: {e}"
        summary["warnings"].append(map_note)
    summary["mapping_note"] = map_note

    store_key = f"{cfg.market}-{summary['provider']}"   # each source has its own history
    prev = store.latest(store_key) if store else None
    delta = eng.diff(prev, summary) if prev else None
    gq = "SYN" if snap.spot_quality == Quality.SYNTHETIC else _greeks_label(res)
    factor = mapped["mapping"]["factor"] if mapped else None
    offset = mapped["mapping"]["offset"] if mapped else 0.0
    payload = pine_payload(summary, cfg.market, cfg.source, method, factor=factor, offset=offset,
                           greeks_quality=gq, delta=delta,
                           provider=summary["provider"]) if res.status != "UNAVAILABLE" else ""
    if store:
        store.save(store_key, summary, raw=snap)
    # compare like with like: the stored previous summary is in index points, so is `summary`
    # (comparing it with the futures-mapped levels reported the basis as a several-hundred-tick "shift")
    fired = alerts.evaluate(cfg.market, prev, summary, FUTURES[cfg.market].tick_size) if alerts else []
    return {
        "summary": summary, "mapped": mapped, "delta": delta, "pine": payload, "alerts": fired,
        "bias": compute_bias(mapped or summary, datetime.now(timezone.utc)),
        "profile": [{"price": p, "net": v} for p, v in res.profile],
        "by_strike": [{"strike": k, "call": v["call"], "put": v["put"], "net": v["net"]}
                      for k, v in res.by_strike.items()],
        "ladder": build_ladder(res, snap) if res.status != "UNAVAILABLE" else None,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def _greeks_label(res) -> str:
    qs = {r.gamma_quality for r in res.rows}
    if qs == {Quality.PROVIDER_CALC}:
        return "PROV"
    if qs == {Quality.MODEL_CALC}:
        return "CALC"
    return "MIX" if qs else "NA"
