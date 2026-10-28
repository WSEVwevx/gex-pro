"""Level selection from a GexResult.

Definitions (all in the options-underlying price space; mapping to futures is
done separately in mapping.py):

* call_wall   - strike with the largest |call-side modeled exposure| in the basket.
                Metric reported: |sum of call exposure at strike| in the result unit.
                Magnitude-based, so it does not depend on the sign convention, but it
                still depends on OI, gamma and the expiration basket.
* put_wall    - same, put side.
* max_positive / max_negative - strikes with the largest positive / most negative
                *net* modeled exposure under the chosen positioning model.
* concentrations - strikes whose |net| is at least `min_share` of total |net|,
                ranked, capped at `top_n`.
* clusters    - runs of adjacent significant strikes within `cluster_window_pct`
                of the reference price, reported as an exposure-weighted centre.

None of these are guaranteed support or resistance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .engine import GexResult
from .ladder import band_width


@dataclass
class LevelConfig:
    top_n: int = 6
    min_share: float = 0.04
    cluster_window_pct: float = 0.015
    wall_side_filter: bool = True    # call wall searched at/above ref, put wall at/below (False = anywhere)


def summarize(res: GexResult, cfg: Optional[LevelConfig] = None) -> dict:
    cfg = cfg or LevelConfig()
    out: dict = {
        "underlying": res.underlying, "source_kind": res.source_kind, "source": res.source,
        "asof": res.asof.isoformat(), "ref_price": res.spot, "ref_quality": res.spot_quality,
        "unit": res.unit, "positioning": res.positioning, "positioning_note": res.positioning_note,
        "basket": res.basket, "status": res.status, "warnings": list(res.warnings),
        "regime": res.regime, "net": res.totals.get("net"), "gross": res.totals.get("gross"),
        "call_total": res.totals.get("call"), "put_total": res.totals.get("put"),
        "zero_gamma": None, "zero_gamma_status": res.zero_gamma_status,
        "zero_gamma_alternatives": res.zero_gamma_crossings,
        "call_wall": None, "put_wall": None, "max_positive": None, "max_negative": None, "abs_gamma": None,
        "concentrations": [], "clusters": [], "expected_move": res.expected_move,
        "gamma_weighted_distance": res.gamma_weighted_distance,
        "near_spot_concentration": res.near_spot_concentration,
        "profile_coverage": res.profile_coverage, "excluded": res.excluded,
        "abs_by_strike": {str(k): v["abs"] for k, v in res.by_strike.items()},
        "by_expiry": res.by_expiry, "by_dte_bucket": res.by_dte_bucket,
    }
    if res.status == "UNAVAILABLE" or not res.by_strike:
        return out
    s = res.spot
    bs = res.by_strike
    if res.zero_gamma is not None:
        out["zero_gamma"] = {"price": res.zero_gamma, "kind": "estimate", "metric": "modeled net exposure = 0"}

    def pick(side: str, above: Optional[bool]):
        cands = [(k, v) for k, v in bs.items() if v[side] != 0]
        if cfg.wall_side_filter and above is not None:
            cands = [(k, v) for k, v in cands if (k >= s if above else k <= s)]
        if not cands:
            return None
        k, v = max(cands, key=lambda kv: abs(kv[1][side]))
        return {"price": k, "metric": f"|{side} exposure|", "value": abs(v[side]), "oi": v[side + "_oi"]}

    out["call_wall"] = pick("call", True)
    out["put_wall"] = pick("put", False)

    # absolute gamma strike: most TOTAL gamma (calls + puts, sign ignored) - independent of the sign assumption
    k_abs = max(bs, key=lambda k: bs[k]["abs"])
    out["abs_gamma"] = {"price": k_abs, "metric": "max total |exposure|", "value": bs[k_abs]["abs"]}

    pos = [(k, v["net"]) for k, v in bs.items() if v["net"] > 0]
    neg = [(k, v["net"]) for k, v in bs.items() if v["net"] < 0]
    if pos:
        k, n = max(pos, key=lambda kv: kv[1])
        out["max_positive"] = {"price": k, "metric": "max net exposure", "value": n}
    if neg:
        k, n = min(neg, key=lambda kv: kv[1])
        out["max_negative"] = {"price": k, "metric": "min net exposure", "value": n}

    out["ranked"] = ranked_levels(bs, s)

    tot_abs_net = sum(abs(v["net"]) for v in bs.values())
    if tot_abs_net > 0:
        ranked = sorted(bs.items(), key=lambda kv: abs(kv[1]["net"]), reverse=True)
        conc = []
        for k, v in ranked:
            share = abs(v["net"]) / tot_abs_net
            if share < cfg.min_share or len(conc) >= cfg.top_n:
                break
            conc.append({"price": k, "net": v["net"], "share": share, "sign": "+" if v["net"] > 0 else "-"})
        out["concentrations"] = conc

        sig = sorted(k for k, v in bs.items()
                     if abs(v["net"]) / tot_abs_net >= cfg.min_share and abs(k - s) <= cfg.cluster_window_pct * s)
        strikes = list(bs)
        clusters, run = [], []
        for k in sig:
            if run and strikes.index(k) - strikes.index(run[-1]) > 1:
                clusters.append(run)
                run = []
            run.append(k)
        if run:
            clusters.append(run)
        for run in clusters:
            w = sum(abs(bs[k]["net"]) for k in run)
            centre = sum(k * abs(bs[k]["net"]) for k in run) / w
            net = sum(bs[k]["net"] for k in run)
            out["clusters"].append({"price": centre, "strikes": run, "net": net, "share": w / tot_abs_net})
    return out


RANK_WINDOW = 0.06          # ranked levels: strikes within 6% of the reference price
RANK_N = {"call": 5, "put": 5, "abs": 3}
RANK0_WINDOW = 0.03         # first expiry: its gamma sits close to price
RANK0_N = {"call": 7, "put": 7, "abs": 3}


def ranked_levels(bs: dict, spot: float, window: float = RANK_WINDOW, n: Optional[dict] = None, banded: bool = True) -> dict:
    """The strongest strikes near price, for the chart's level tags (C1.., P1.., Ab1..).

    call: most positive net GEX first; put: most negative net GEX first; abs: most total gamma (calls and
    puts, sign ignored) first. Banded: strongest first, and a strike within one band width (40 points on
    NDX, 10 on SPX) of a level already taken adds its gamma to that level instead of taking a rank, so
    levels sit at real strikes at least a band apart. share = the level's |net| (or total) over the sum
    across all strikes."""
    n = n or RANK_N
    near = {k: v for k, v in bs.items() if spot and abs(k - spot) <= window * spot}
    tot_net = sum(abs(v["net"]) for v in bs.values()) or 1.0
    tot_abs = sum(v["abs"] for v in bs.values()) or 1.0
    w = band_width(spot) if banded and spot else 0.0

    def pick(vals: list) -> list:                     # [(strike, strength)] -> [[strike, summed strength]]
        kept: list = []
        for k, v in sorted(vals, key=lambda kv: -kv[1]):
            home = next((x for x in kept if abs(x[0] - k) < w), None)
            if home:
                home[1] += v
            else:
                kept.append([k, v])
        return sorted(kept, key=lambda x: -x[1])

    pos = pick([(k, v["net"]) for k, v in near.items() if v["net"] > 0])
    neg = pick([(k, -v["net"]) for k, v in near.items() if v["net"] < 0])
    ab = pick([(k, v["abs"]) for k, v in near.items() if v["abs"] > 0])
    return {"call": [{"price": k, "value": v, "share": v / tot_net} for k, v in pos[:n["call"]]],
            "put": [{"price": k, "value": -v, "share": v / tot_net} for k, v in neg[:n["put"]]],
            "abs": [{"price": k, "value": v, "share": v / tot_abs} for k, v in ab[:n["abs"]]]}
