"""Core typed data model.

Every value that reaches a calculation carries an explicit data-quality tag so
that delayed, end-of-day, estimated, synthetic, and missing data can never be
silently substituted for one another.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class OptionType(str, Enum):
    CALL = "C"
    PUT = "P"


class Quality(str, Enum):
    """Provenance / freshness category of a value."""

    REALTIME = "RT"          # real-time quote from an entitled feed
    DELAYED = "DL"           # exchange-delayed quote (typically 10-20 min)
    EOD = "EOD"              # end-of-day value (open interest is always this)
    PROVIDER_CALC = "PROV"   # Greek/IV computed by the data vendor
    MODEL_CALC = "CALC"      # Greek/IV computed by this system
    MANUAL = "MAN"           # entered by the user
    SYNTHETIC = "SYN"        # generated test data - never real market data
    STALE = "STALE"          # older than the configured freshness limit
    MISSING = "NA"           # not available


class SourceKind(str, Enum):
    """What instrument's options produced the chain."""

    INDEX = "INDEX"      # SPX, NDX (European, cash settled)
    ETF = "ETF"          # SPY, QQQ (American, physically settled)
    FUTURES = "FUT"      # ES / NQ options on futures (American or European by series)


@dataclass
class OptionContract:
    symbol: str                    # vendor / OCC contract identifier
    root: str                      # option root, e.g. SPXW, NDXP, QQQ
    underlying: str                # SPX, NDX, QQQ, SPY, ESZ6 ...
    option_type: OptionType
    strike: float
    expiration: datetime           # timezone-aware expiry *time* (settlement reference)
    multiplier: float
    open_interest: Optional[float] = None
    volume: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    last_time: Optional[datetime] = None
    iv: Optional[float] = None     # annualised decimal volatility
    gamma: Optional[float] = None  # d(delta)/dS per 1.0 unit of underlying, per 1 option unit
    delta: Optional[float] = None
    quote_quality: Quality = Quality.MISSING
    oi_quality: Quality = Quality.EOD
    greeks_quality: Quality = Quality.MISSING
    greeks_time: Optional[datetime] = None
    exercise_style: str = "european"   # european | american
    group_strike: Optional[float] = None   # strike used to GROUP levels when it differs from the exact
                                           # strike (ETF options converted to index terms); math uses `strike`

    @property
    def level_strike(self) -> float:
        return self.strike if self.group_strike is None else self.group_strike

    @property
    def mid(self) -> Optional[float]:
        if self.bid is None or self.ask is None or self.ask <= 0 or self.bid < 0 or self.ask < self.bid:
            return None
        return 0.5 * (self.bid + self.ask)

    def key(self) -> tuple:
        return (self.root, self.option_type.value, round(self.strike, 6), self.expiration.isoformat())


@dataclass
class ChainSnapshot:
    underlying: str
    source_kind: SourceKind
    spot: Optional[float]
    spot_time: Optional[datetime]
    spot_quality: Quality
    contracts: list[OptionContract]
    source: str                    # provider name, e.g. "cboe", "csv:file", "synthetic"
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    rate: float = 0.04             # continuously compounded risk-free rate assumption
    div_yield: float = 0.0         # continuous dividend yield assumption (0 for futures options)
    warnings: list[str] = field(default_factory=list)
    prev_close: Optional[float] = None   # underlying's previous session close (anchors expected-move bands)

    def expirations(self) -> list[datetime]:
        return sorted({c.expiration for c in self.contracts})


def to_jsonable(obj):
    """Recursively convert dataclasses / enums / datetimes into JSON-safe values."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return None
    return obj
