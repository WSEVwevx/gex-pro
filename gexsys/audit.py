"""Live data audit: `python -m gexsys audit [--config ...]`.

Pulls the real chain for each config and checks, end to end:
  data       chain present, enough near-money open interest, IV coverage
  cross      vendor gamma vs an independent Black-Scholes recomputation; vendor IV vs IV solved from the
             bid/ask mid (both only on liquid near-money contracts, where the comparison is meaningful)
  levels     call wall >= price >= put wall, zero gamma found or explicitly absent, every level within the
             indicator's 8% safety distance, max pain and expected move in sane ranges
  accounting by-strike and by-expiry sums equal the totals
  payload    the TradingView paste is complete, short enough, and carries the same numbers
Each check is PASS, WARN (worth a look, not wrong) or FAIL (a bug or bad data).
"""
from __future__ import annotations

import math
import statistics
from typing import Optional

from . import engine as eng
from . import pricing
from .export import parse_payload
from .models import OptionType
from .normalize import normalize
from .pipeline import run_once


class _Replay:
    """Feeds one already-fetched snapshot to run_once, so every check sees the same data."""

    def __init__(self, provider, snap):
        self._p, self._snap = provider, snap
        self.name = getattr(provider, "name", "")
        self.label = getattr(provider, "last_label", None) or getattr(provider, "label", "")

    def fetch_snapshot(self, *a, **k):
        return self._snap

    def futures_basis(self, *a, **k):
        fb = getattr(self._p, "futures_basis", None)
        return fb(*a, **k) if fb else None


def _p(v) -> Optional[float]:
    return v.get("price") if isinstance(v, dict) else v


def audit(cfg, provider) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []

    def add(name, ok, detail, warn_only=False):
        out.append((name, "PASS" if ok else ("WARN" if warn_only else "FAIL"), detail))

    raw = provider.fetch_snapshot(cfg.source, cfg.engine.max_dte, cfg.engine.include_0dte)
    snap = normalize(raw)
    s = snap.spot
    add("data: underlying price", bool(s), f"{snap.underlying} {s} ({snap.spot_quality.value}) from {snap.source}")
    near = [c for c in snap.contracts if s and abs(c.strike / s - 1) <= 0.05 and (c.open_interest or 0) > 0]
    add("data: near-money open interest", len(near) >= 20, f"{len(near)} contracts within 5% with OI > 0")

    # ---- cross-checks against an independent recomputation
    futures = snap.source_kind.value == "FUT"
    q = snap.rate if futures else snap.div_yield
    asof = snap.fetched_at
    g_err, iv_err = [], []
    for c in near:
        t = (c.expiration - asof).total_seconds() / eng.YEAR_SECONDS
        if t <= 1 / 365 or not c.iv:
            continue                                            # skip 0DTE: gamma there is too sensitive to compare
        if c.gamma and c.gamma >= 0.001:                        # vendor gamma has 4 decimals; tiny values are rounding
            mine = pricing.model_gamma(s, c.strike, t, snap.rate, q, c.iv, futures)
            g_err.append(abs(mine / c.gamma - 1))
        mid = c.mid
        if mid and c.bid and c.bid > 0 and (c.ask - c.bid) / mid < 0.10 and mid > 1.0:
            solved = pricing.implied_vol(mid, s, c.strike, t, snap.rate, q, c.option_type == OptionType.CALL)
            if solved:
                iv_err.append(abs(solved - c.iv))
    if g_err:
        med = statistics.median(g_err)
        add("cross: vendor gamma vs Black-Scholes", med < 0.10,
            f"median difference {med:.1%} on {len(g_err)} contracts (vendor gamma is rounded to 4 decimals)", warn_only=True)
    else:
        add("cross: vendor gamma vs Black-Scholes", True, "no vendor gamma large enough to compare (skipped)")
    if iv_err:
        med = statistics.median(iv_err)
        add("cross: vendor IV vs IV from bid/ask mid", med < 0.02,
            f"median difference {med * 100:.2f} vol points on {len(iv_err)} liquid contracts"
            + ("" if snap.spot_quality.value == "RT" else " (delayed quotes vs a later price can widen this)"), warn_only=True)
    else:
        add("cross: vendor IV vs IV from bid/ask mid", True, "no liquid two-sided quotes now (market closed?) - skipped")

    # ---- full pipeline on the same data
    r = run_once(cfg, _Replay(provider, raw))
    sm, L = r["summary"], (r["mapped"] or r["summary"])
    add("levels: calculation status", sm["status"] != "UNAVAILABLE", f"{sm['status']}; warnings: {len(sm['warnings'])}")
    if sm["status"] == "UNAVAILABLE":
        return out
    ref = L.get("futures_equiv_of_ref") or sm["ref_price"]
    cw, pw, zg = _p(L["call_wall"]), _p(L["put_wall"]), _p(L["zero_gamma"])
    add("levels: call wall at/above price", cw is None or cw >= ref - 1e-6, f"call wall {cw} vs price {ref:.2f}")
    add("levels: put wall at/below price", pw is None or pw <= ref + 1e-6, f"put wall {pw} vs price {ref:.2f}")
    add("levels: zero gamma", zg is not None or sm["zero_gamma_status"].startswith("NO CROSSING"),
        f"{zg} ({sm['zero_gamma_status']})")
    far = [(k, _p(L[k])) for k in ("zero_gamma", "call_wall", "put_wall", "max_positive", "max_negative", "abs_gamma")
           if _p(L.get(k)) is not None and abs(_p(L[k]) / ref - 1) > 0.08]
    add("levels: all within the indicator's 8% safety distance", not far, f"too far: {far}" if far else "all key levels within 8%")
    ex = L.get("extras") or {}
    mp = (ex.get("max_pain") or [{}])[0].get("price")
    add("levels: nearest max pain within 5%", mp is None or abs(mp / ref - 1) <= 0.05, f"{mp}", warn_only=True)
    em = (ex.get("expected_move") or {})
    d = em.get("daily_points_fut") or em.get("daily_points")
    add("levels: daily expected move 0.2%-5% of price", d is not None and 0.002 * ref < d < 0.05 * ref,
        f"+/-{d:.1f} points" if d else "missing")
    fac = (r["mapped"] or {}).get("mapping", {}).get("factor")
    if fac:
        add("levels: futures/index ratio plausible", 0.98 < fac < 1.05, f"factor {fac:.6f}")

    # ---- accounting
    res_net = sm["net"]
    by_strike = sum(b["net"] for b in r["by_strike"])
    by_exp = sum(v["net"] for v in sm["by_expiry"].values())
    add("accounting: strikes sum to net GEX", math.isclose(by_strike, res_net, rel_tol=1e-9, abs_tol=1e-3), f"{by_strike:.4g} vs {res_net:.4g}")
    add("accounting: expirations sum to net GEX", math.isclose(by_exp, res_net, rel_tol=1e-9, abs_tol=1e-3), f"{by_exp:.4g} vs {res_net:.4g}")
    g = ex.get("greeks") or {}
    add("greeks: vanna/charm computed", bool(g), f"vanna ${g.get('vanna_usd_per_vol_pt', 0) / 1e6:,.0f}M per IV point, "
        f"charm ${g.get('charm_usd_per_day', 0) / 1e6:,.0f}M per day, coverage {g.get('coverage', 0):.0%}" if g else "missing")

    # ---- the TradingView paste
    pl = r["pine"]
    d = parse_payload(pl)
    add("payload: complete (END marker)", d["complete"], f"{len(pl)} characters")
    add("payload: short enough", len(pl) <= 1800, f"{len(pl)} of 1800 characters")
    same = all(abs(float(d[k]) - _p(sm[n])) < 0.006 for k, n in (("zg", "zero_gamma"), ("cw", "call_wall"), ("pw", "put_wall"))
               if d.get(k) and _p(sm.get(n)) is not None)
    add("payload: carries the same levels", same, f"zg {d.get('zg')}  cw {d.get('cw')}  pw {d.get('pw')}  ag {d.get('ag')}")
    return out


def print_report(title: str, rows: list[tuple[str, str, str]]) -> int:
    print(f"\n=== {title} ===")
    for name, status, detail in rows:
        print(f"  [{status}] {name:<52} {detail}")
    fails = sum(1 for _, st, _ in rows if st == "FAIL")
    warns = sum(1 for _, st, _ in rows if st == "WARN")
    print(f"  -> {len(rows) - fails - warns} passed, {warns} warnings, {fails} failed")
    return fails
