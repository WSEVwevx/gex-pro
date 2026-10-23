"""Historical replay & calibration of the *calculations* (not trading outcomes).

Metrics are computed over stored summaries in time order:
  * level stability: absolute shift of zero gamma / walls between consecutive snapshots
  * shift frequency: share of snapshots where a level moved at all
  * regime changes and missing-data frequency
  * data latency: computation time minus reference-price timestamp
Sensitivity analysis re-runs one chain under every positioning model.

Strategy evaluation is deliberately out of scope here: it needs a pre-registered
methodology, transaction costs, slippage and out-of-sample data (docs/METHODOLOGY.md §9).
"""
from __future__ import annotations

import statistics
from datetime import datetime
from typing import Iterable

from . import engine as eng
from .levels import summarize
from .models import ChainSnapshot


def _price(s: dict, key: str):
    v = s.get(key)
    return v.get("price") if isinstance(v, dict) else v


def stability(summaries: Iterable[dict]) -> dict:
    ss = list(summaries)
    out: dict = {"snapshots": len(ss)}
    if not ss:
        return out
    out["unavailable_share"] = sum(1 for s in ss if s.get("status") == "UNAVAILABLE") / len(ss)
    out["degraded_share"] = sum(1 for s in ss if s.get("status") == "DEGRADED") / len(ss)
    out["regime_changes"] = sum(1 for a, b in zip(ss, ss[1:]) if a.get("regime") != b.get("regime"))
    for key in ("zero_gamma", "call_wall", "put_wall", "max_positive", "max_negative"):
        shifts = []
        for a, b in zip(ss, ss[1:]):
            pa, pb = _price(a, key), _price(b, key)
            if pa is not None and pb is not None:
                shifts.append(abs(pb - pa))
        if shifts:
            out[key] = {"mean_abs_shift": statistics.fmean(shifts), "max_abs_shift": max(shifts),
                        "moved_share": sum(1 for x in shifts if x > 0) / len(shifts),
                        "missing_share": sum(1 for s in ss if _price(s, key) is None) / len(ss)}
    lat = []
    for s in ss:
        if s.get("asof") and s.get("ref_time"):
            lat.append((datetime.fromisoformat(s["asof"]) - datetime.fromisoformat(s["ref_time"])).total_seconds())
    if lat:
        out["latency_s"] = {"mean": statistics.fmean(lat), "max": max(lat)}
    return out


def sensitivity(snap: ChainSnapshot, base: eng.EngineConfig | None = None) -> dict:
    """Zero gamma, regime and walls under each positioning model for the same chain."""
    base = base or eng.EngineConfig()
    out = {}
    for model in eng.POSITIONING_MODELS:
        cfg = eng.EngineConfig(**{**base.__dict__, "positioning": model})
        s = summarize(eng.compute(snap, cfg))
        out[model] = {"zero_gamma": _price(s, "zero_gamma"), "regime": s["regime"], "net": s["net"],
                      "call_wall": _price(s, "call_wall"), "put_wall": _price(s, "put_wall"),
                      "max_positive": _price(s, "max_positive"), "max_negative": _price(s, "max_negative")}
    return out
