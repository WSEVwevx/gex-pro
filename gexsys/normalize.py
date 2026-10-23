"""Chain validation and normalisation.

Never invents values: invalid fields become None (and are counted), invalid
contracts are dropped (and counted), and every action is recorded in
snapshot.warnings so it reaches the dashboard.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from .models import ChainSnapshot, OptionContract, OptionType, Quality

log = logging.getLogger(__name__)

OCC_RE = re.compile(r"^(?:O:)?([A-Z0-9]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")


def parse_occ(symbol: str) -> Optional[dict]:
    """Parse an OCC option symbol, e.g. 'SPXW261020C05800000'. Returns None if invalid."""
    m = OCC_RE.match(symbol.replace(" ", "").upper())
    if not m:
        return None
    root, yy, mm, dd, cp, strike = m.groups()
    try:
        exp = datetime(2000 + int(yy), int(mm), int(dd)).date()
    except ValueError:
        return None
    return {"root": root, "expiration": exp, "type": OptionType(cp), "strike": int(strike) / 1000.0}


def _fin(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def normalize(snap: ChainSnapshot, check_occ: bool = False, max_quote_age_s: Optional[float] = None,
              now: Optional[datetime] = None) -> ChainSnapshot:
    now = now or datetime.now(timezone.utc)
    counts = {"invalid": 0, "duplicate": 0, "bad_oi": 0, "bad_iv": 0, "bad_gamma": 0, "crossed_quote": 0,
              "stale_quote": 0, "occ_mismatch": 0}
    seen: dict[tuple, OptionContract] = {}
    for c in snap.contracts:
        if c.strike is None or not _fin(c.strike) or c.strike <= 0 or not c.multiplier or c.multiplier <= 0 \
                or c.expiration is None or c.expiration.tzinfo is None:
            counts["invalid"] += 1
            continue
        if check_occ:
            p = parse_occ(c.symbol)
            if p is None:
                counts["invalid"] += 1
                continue
            if abs(p["strike"] - c.strike) > 1e-6 or p["type"] != c.option_type \
                    or p["expiration"] != c.expiration.date():
                counts["occ_mismatch"] += 1
                continue
        upd = {}
        oi = _fin(c.open_interest)
        if c.open_interest is not None and (oi is None or oi < 0):
            upd["open_interest"] = None
            counts["bad_oi"] += 1
        if c.iv is not None and not (_fin(c.iv) and 0 < c.iv <= 5.0):
            upd["iv"] = None
            counts["bad_iv"] += 1
        if c.gamma is not None and not (_fin(c.gamma) is not None and c.gamma >= 0):
            upd["gamma"] = None
            upd["greeks_quality"] = Quality.MISSING
            counts["bad_gamma"] += 1
        if c.bid is not None and c.ask is not None and c.ask < c.bid:
            upd["bid"] = upd["ask"] = None
            counts["crossed_quote"] += 1
        if max_quote_age_s is not None and c.last_time is not None \
                and (now - c.last_time).total_seconds() > max_quote_age_s and c.quote_quality != Quality.SYNTHETIC:
            upd["quote_quality"] = Quality.STALE
            counts["stale_quote"] += 1
        if upd:
            c = replace(c, **upd)
        k = c.key()
        if k in seen:
            counts["duplicate"] += 1
            prev = seen[k]
            # keep the most recently updated record
            if (c.greeks_time or c.last_time or datetime.min.replace(tzinfo=timezone.utc)) >= \
                    (prev.greeks_time or prev.last_time or datetime.min.replace(tzinfo=timezone.utc)):
                seen[k] = c
            continue
        seen[k] = c
    warnings = list(snap.warnings)
    for k, v in counts.items():
        if v:
            warnings.append(f"normalize: {v} {k.replace('_', ' ')}")
            log.info("normalize %s=%d underlying=%s", k, v, snap.underlying)
    return replace(snap, contracts=list(seen.values()), warnings=warnings)
