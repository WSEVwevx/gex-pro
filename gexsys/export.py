"""TradingView bridge: compact text payload pasted into the Pine indicator's
"Levels payload" input.

Why a pasted payload: Pine Script cannot make HTTP requests, and Pine Seeds
(request.seed) is closed to new repositories and end-of-day only.  A text input
is the only documented way to get externally computed values into a standard
Pine indicator.  It is therefore a *manual snapshot*, not a live feed.

Format (v1), semicolon-separated key=value tokens, ASCII only, plain decimals
(no scientific notation - Pine's str.tonumber support for exponents is not relied on):

  GEX1;mkt=NQ;src=NDX;kind=INDEX;tv=NASDAQ:NDX;map=ratio;fac=1.010123;off=0;
  ts=1760972400000;ref=20000.00;q=DL;oi=EOD;gk=PROV;model=conventional;unit=USD1PCT;
  netb=1.234;reg=POS;st=OK;zg=19850.00;zgs=E;cw=20200;pw=19500;mp=20200;mn=19800;
  em=180.5;bk=2026-10-20..2026-11-19;dzg=-12.5;preg=POS;
  L=20200:+:0.180,19800:-:0.120;R=C20200.00:18.0,P19500.00:12.0,A20000.00:9.5

R = ranked levels near price for the chart's tags: C (most positive net GEX first), P (most negative
net GEX first), A (most total gamma first), each "price:share %" in rank order.

Level prices are in the OPTIONS-UNDERLYING space (e.g. NDX points).  The Pine
script maps them to the chart with either a live TradingView reference symbol
(`tv`) or the snapshot factor/offset (`fac`, `off`).  `fac`=0 means the service
had no futures reference price and Pine must use the live mapping.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .mapping import SOURCES

UNIT_CODES = {"usd_per_1pct": "USD1PCT", "usd_per_point": "USDPT", "delta_per_point": "DPT"}
MAX_LEN = 1800


def _n(x: Optional[float], nd: int = 2) -> str:
    return "" if x is None else f"{x:.{nd}f}"


def _p(lv) -> Optional[float]:
    if isinstance(lv, dict):
        return lv.get("src_price", lv.get("price"))
    return lv


def pine_payload(summary: dict, market: str, source_key: str, method: str,
                 factor: Optional[float] = None, offset: float = 0.0,
                 quote_quality: str = "DL", greeks_quality: str = "PROV",
                 delta: Optional[dict] = None, max_levels: int = 6, provider: str = "") -> str:
    src = SOURCES[source_key]
    asof = datetime.fromisoformat(summary["asof"])
    em = (summary.get("expected_move") or {}).get("one_sigma_points")
    basket = summary.get("basket") or []
    zgs = summary.get("zero_gamma_status", "")
    tok = {
        "prov": "".join(ch for ch in provider.upper() if ch.isalnum())[:8] or "?",
        "mkt": market, "src": source_key, "kind": src.kind.value, "tv": src.tv_symbol, "map": method,
        "fac": _n(factor, 6) if factor else "0", "off": _n(offset, 4),
        "ts": str(int(asof.timestamp() * 1000)), "ref": _n(summary.get("ref_price")),
        "q": summary.get("ref_quality", quote_quality),
        "oi": "SYN" if summary.get("ref_quality") == "SYN" else "EOD", "gk": greeks_quality,
        "model": summary.get("positioning", ""), "unit": UNIT_CODES.get(summary.get("unit"), "?"),
        "netb": _n(summary["net"] / 1e9, 4) if summary.get("net") is not None else "",
        "reg": {"POSITIVE": "POS", "NEGATIVE": "NEG", "INDETERMINATE": "IND"}.get(summary.get("regime"), "NA"),
        "st": summary.get("status", "NA"),
        "zg": _n(_p(summary.get("zero_gamma"))),
        "zgs": "E" if zgs.startswith("ESTIMATE") else ("X" if zgs.startswith("NO CROSSING") else "NA"),
        "cw": _n(_p(summary.get("call_wall"))), "pw": _n(_p(summary.get("put_wall"))),
        "mp": _n(_p(summary.get("max_positive"))), "mn": _n(_p(summary.get("max_negative"))),
        "ag": _n(_p(summary.get("abs_gamma"))),
        "em": _n(em), "bk": f"{basket[0]}..{basket[-1]}" if basket else "",
    }
    if summary.get("etf"):
        tok["etf"] = summary["etf"]              # ETF options folded into the index chain, e.g. SPY
    if delta:
        if delta.get("zero_gamma") is not None:
            tok["dzg"] = _n(delta["zero_gamma"])
        if delta.get("prev_regime"):
            tok["preg"] = {"POSITIVE": "POS", "NEGATIVE": "NEG", "INDETERMINATE": "IND"}.get(delta["prev_regime"], "NA")
    levels = []
    for c in (summary.get("concentrations") or [])[:max_levels]:
        levels.append(f"{_p(c):.2f}:{c['sign']}:{c['share']:.3f}")
    tok["L"] = ",".join(levels)
    rk = summary.get("ranked") or {}
    tok["R"] = ",".join(f"{code}{_p(x):.2f}:{100 * x['share']:.1f}" for side, code in (("call", "C"), ("put", "P"), ("abs", "A"))
                        for x in rk.get(side) or [])
    tok.update(extras_tokens(summary.get("extras") or {}))
    out = "GEX1;" + ";".join(f"{k}={v}" for k, v in tok.items()) + ";END"
    if any(ch in out for ch in "\n\r\"|") or len(out) > MAX_LEN:
        raise ValueError(f"payload invalid or too long ({len(out)} chars)")
    return out


def extras_tokens(ex: dict) -> dict:
    """Tokens for gexsys/extras.py levels (options-underlying prices, like every level here).

    x0 nearest-expiration label ("0DTE" or "next MM-DD"); z0/c0/p0 its zero gamma / call wall / put wall
    vc/vp volume walls; oc/op open-interest walls
    xp max pain "YYYY-MM-DD:price" for the first two expirations
    ema anchor, emd daily 1-sd points, emw weekly 1-sd points, emx weekly expiration
    P  GEX profile "base/width/v1,v2,..." with v in -99..99 (bin i centred at base + i*width)
    """
    t: dict = {}
    n = ex.get("nearest")
    if n:
        t.update({"x0": n["label"], "z0": _n(_p(n.get("zero_gamma"))), "c0": _n(_p(n.get("call_wall"))),
                  "p0": _n(_p(n.get("put_wall")))})
    for k, key in (("vc", "vol_call"), ("vp", "vol_put"), ("oc", "oi_call"), ("op", "oi_put")):
        if ex.get(key):
            t[k] = _n(_p(ex[key]))
    if ex.get("max_pain"):
        t["xp"] = ",".join(f"{m['expiration']}:{_p(m):.2f}" for m in ex["max_pain"][:2])
    em = ex.get("expected_move")
    if em:
        t["ema"] = _n(em["anchor"])
        if em.get("daily_points") is not None:
            t["emd"] = _n(em["daily_points"])
        if em.get("weekly_points") is not None:
            t.update({"emw": _n(em["weekly_points"]), "emx": em["weekly_expiry"]})
    g = ex.get("greeks")
    if g:
        t["vxm"] = _n(g["vanna_usd_per_vol_pt"] / 1e6, 1)       # $M of dealer delta per +1 IV point
        t["chm"] = _n(g["charm_usd_per_day"] / 1e6, 1)          # $M of dealer delta per day of decay
    pr = ex.get("profile")
    if pr:
        t["P"] = f"{pr['base']:g}/{pr['width']:g}/" + ",".join(str(v) for v in pr["values"])
    return t


def combine(payloads: list[str]) -> str:
    """Join several payloads (markets x providers) into one paste; the Pine script keeps
    only the ones matching the chart's market."""
    return "|".join(p for p in payloads if p)


def parse_combined(text: str) -> list[dict]:
    return [parse_payload(p) for p in text.strip().split("|") if p.strip()]


def parse_payload(text: str) -> dict:
    """Reference parser mirroring the Pine implementation (used by tests)."""
    parts = text.strip().split(";")
    if not parts or parts[0] != "GEX1":
        raise ValueError("not a GEX1 payload")
    out: dict = {"complete": parts[-1] == "END"}
    for p in parts[1:]:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        out[k] = v
    lv = []
    for item in filter(None, out.get("L", "").split(",")):
        price, sign, share = item.split(":")
        lv.append((float(price), sign, float(share)))
    out["levels"] = lv
    return out
