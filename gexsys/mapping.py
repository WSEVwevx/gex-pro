"""Options-underlying -> futures price mapping for NQ/MNQ and ES/MES.

SPX/NDX index options, SPY/QQQ ETF options and ES/NQ futures options are
different instruments.  A strike in one space is *translated* to a futures
price with an explicit, logged method:

* ratio    L_fut = L_src * (F / U), F and U observed within max_skew_s of each other.
           Required for ETF sources (QQQ ~ NDX/41, SPY ~ SPX/10 - the factor drifts
           with dividends and fees, so it is never hard-coded).
* offset   L_fut = L_src + (F - U).  Basis is additive; allowed only when the source
           is the same index the future tracks (NDX->NQ, SPX->ES).
* identity L_fut = L_src.  Only for futures options whose underlying IS the charted
           contract.  For a different contract month use calendar_offset.

Every mapped level keeps the source instrument, method, factor and timestamps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .models import SourceKind


class MappingError(ValueError):
    pass


@dataclass(frozen=True)
class FuturesSpec:
    root: str
    tick_size: float
    point_value: float
    full_size_root: str        # MNQ -> NQ, MES -> ES (same price scale)


FUTURES = {
    "NQ": FuturesSpec("NQ", 0.25, 20.0, "NQ"),
    "MNQ": FuturesSpec("MNQ", 0.25, 2.0, "NQ"),
    "ES": FuturesSpec("ES", 0.25, 50.0, "ES"),
    "MES": FuturesSpec("MES", 0.25, 5.0, "ES"),
}


@dataclass(frozen=True)
class OptionsSource:
    name: str               # NDX, QQQ, NQ_FOP, SPX, SPY, ES_FOP
    kind: SourceKind
    tracks: str             # full-size futures root this source maps onto
    vendor_symbol: str      # symbol used to request the chain
    tv_symbol: str          # TradingView symbol for live reference in Pine
    multiplier: float
    exercise: str
    default_method: str
    allowed_methods: tuple


SOURCES = {
    "NDX": OptionsSource("NDX", SourceKind.INDEX, "NQ", "NDX", "NASDAQ:NDX", 100, "european", "ratio", ("ratio", "offset")),
    "QQQ": OptionsSource("QQQ", SourceKind.ETF, "NQ", "QQQ", "NASDAQ:QQQ", 100, "american", "ratio", ("ratio",)),
    "NQ_FOP": OptionsSource("NQ_FOP", SourceKind.FUTURES, "NQ", "NQ", "CME_MINI:NQ1!", 20, "american", "identity", ("identity", "calendar_offset")),
    "SPX": OptionsSource("SPX", SourceKind.INDEX, "ES", "SPX", "SP:SPX", 100, "european", "ratio", ("ratio", "offset")),
    "SPY": OptionsSource("SPY", SourceKind.ETF, "ES", "SPY", "AMEX:SPY", 100, "american", "ratio", ("ratio",)),
    "ES_FOP": OptionsSource("ES_FOP", SourceKind.FUTURES, "ES", "ES", "CME_MINI:ES1!", 50, "american", "identity", ("identity", "calendar_offset")),
}


@dataclass
class MappingContext:
    market: str                 # NQ, MNQ, ES, MES
    source: str                 # key into SOURCES
    method: str
    futures_price: Optional[float]
    futures_time: Optional[datetime]
    source_price: Optional[float]
    source_time: Optional[datetime]
    max_skew_s: float = 60.0
    calendar_spread: Optional[float] = None   # charted contract minus option-underlying contract
    notes: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.market not in FUTURES:
            raise MappingError(f"unknown futures market {self.market!r}")
        if self.source not in SOURCES:
            raise MappingError(f"unknown options source {self.source!r}")
        src, fut = SOURCES[self.source], FUTURES[self.market]
        if src.tracks != fut.full_size_root:
            raise MappingError(f"{self.source} options track {src.tracks}, not {fut.full_size_root}: "
                               "cross-index mapping is not supported")
        if self.method not in src.allowed_methods:
            raise MappingError(f"method {self.method!r} not valid for {self.source} "
                               f"(allowed: {', '.join(src.allowed_methods)})")
        if self.method in ("ratio", "offset"):
            for name, v in (("futures_price", self.futures_price), ("source_price", self.source_price)):
                if v is None or v <= 0:
                    raise MappingError(f"{name} required for {self.method} mapping")
            if self.futures_time is None or self.source_time is None:
                raise MappingError("both reference prices need timestamps for basis mapping")
            skew = abs((self.futures_time - self.source_time).total_seconds())
            if skew > self.max_skew_s:
                raise MappingError(f"reference prices {skew:.0f}s apart (> {self.max_skew_s:.0f}s); "
                                   "basis would be stale - refusing to map")
        if self.method == "calendar_offset" and self.calendar_spread is None:
            raise MappingError("calendar_offset requires calendar_spread (charted minus option-underlying contract)")

    @property
    def factor(self) -> float:
        if self.method == "ratio":
            return self.futures_price / self.source_price
        return 1.0

    @property
    def offset(self) -> float:
        if self.method == "offset":
            return self.futures_price - self.source_price
        if self.method == "calendar_offset":
            return self.calendar_spread
        return 0.0

    def map_price(self, p: Optional[float]) -> Optional[float]:
        if p is None:
            return None
        return p * self.factor + self.offset

    def describe(self) -> dict:
        return {"market": self.market, "source": self.source, "source_kind": SOURCES[self.source].kind.value,
                "method": self.method, "factor": self.factor, "offset": self.offset,
                "futures_ref": self.futures_price, "source_ref": self.source_price,
                "futures_time": self.futures_time.isoformat() if self.futures_time else None,
                "source_time": self.source_time.isoformat() if self.source_time else None,
                "proxy": SOURCES[self.source].kind != SourceKind.FUTURES, "notes": self.notes}


def round_to_tick(p: float, tick: float) -> float:
    return round(round(p / tick) * tick, 10)


def distance(price: float, level: float, tick: float) -> dict:
    pts = level - price
    return {"points": pts, "ticks": pts / tick, "pct": pts / price * 100.0 if price else None}


def map_summary(summary: dict, ctx: MappingContext) -> dict:
    """Return a copy of a levels summary with every level price mapped to futures."""
    ctx.validate()
    tick = FUTURES[ctx.market].tick_size
    out = dict(summary)
    for key in ("zero_gamma", "call_wall", "put_wall", "max_positive", "max_negative", "abs_gamma"):
        lv = summary.get(key)
        if lv:
            out[key] = dict(lv, src_price=lv["price"], price=round_to_tick(ctx.map_price(lv["price"]), tick))
    out["concentrations"] = [dict(c, src_price=c["price"], price=round_to_tick(ctx.map_price(c["price"]), tick))
                             for c in summary.get("concentrations", [])]
    out["clusters"] = [dict(c, src_price=c["price"], price=round_to_tick(ctx.map_price(c["price"]), tick))
                       for c in summary.get("clusters", [])]
    out["zero_gamma_alternatives"] = [round_to_tick(ctx.map_price(x), tick)
                                      for x in summary.get("zero_gamma_alternatives", [])]
    em = summary.get("expected_move")
    if em:
        em = dict(em)
        for k in ("one_sigma_points", "straddle_mid_points"):
            if em.get(k) is not None:
                em[k + "_fut"] = em[k] * ctx.factor
        out["expected_move"] = em
    out["extras"] = map_extras(summary.get("extras") or {}, ctx, tick)
    out["mapping"] = ctx.describe()
    out["market"] = ctx.market
    out["tick_size"] = tick
    return out


def map_extras(ex: dict, ctx: MappingContext, tick: float) -> dict:
    """Map every price in the extras block (gexsys/extras.py); keep src_price beside each."""
    def lv(d):
        return dict(d, src_price=d["price"], price=round_to_tick(ctx.map_price(d["price"]), tick)) if d else d
    out = dict(ex)
    if ex.get("nearest"):
        n = dict(ex["nearest"])
        for k in ("zero_gamma", "call_wall", "put_wall"):
            n[k] = lv(n.get(k))
        out["nearest"] = n
    for k in ("vol_call", "vol_put", "oi_call", "oi_put"):
        out[k] = lv(ex.get(k))
    out["max_pain"] = [lv(m) for m in ex.get("max_pain") or []]
    em = ex.get("expected_move")
    if em:
        em = dict(em, anchor_fut=round_to_tick(ctx.map_price(em["anchor"]), tick))
        for k in ("daily_points", "weekly_points"):
            if em.get(k) is not None:
                em[k + "_fut"] = em[k] * ctx.factor
        out["expected_move"] = em
    if ex.get("profile"):
        out["profile"] = dict(ex["profile"], base_fut=ctx.map_price(ex["profile"]["base"]),
                              width_fut=ex["profile"]["width"] * ctx.factor)
    return out
