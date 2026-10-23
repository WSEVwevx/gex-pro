"""Deterministic synthetic chains for tests and demos.

Everything produced here is tagged Quality.SYNTHETIC and source='synthetic'.
It is NOT market data and the dashboard / Pine payload say so.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import marketcal, pricing
from ..mapping import SOURCES
from ..models import ChainSnapshot, OptionContract, OptionType, Quality
from .base import Provider

DEFAULT_SPOTS = {"NDX": 20000.0, "QQQ": 487.0, "SPX": 5800.0, "SPY": 579.0, "NQ_FOP": 20250.0, "ES_FOP": 5860.0}
DEFAULT_STEP = {"NDX": 50.0, "QQQ": 1.0, "SPX": 5.0, "SPY": 1.0, "NQ_FOP": 50.0, "ES_FOP": 5.0}


def make_chain(source_key: str = "SPX", spot: Optional[float] = None, asof: Optional[datetime] = None,
               dtes: tuple = (0, 1, 3, 7, 14, 30), n_strikes: int = 40, seed: int = 7,
               base_iv: float = 0.16, rate: float = 0.04) -> ChainSnapshot:
    src = SOURCES[source_key]
    spot = spot or DEFAULT_SPOTS[source_key]
    step = DEFAULT_STEP[source_key]
    asof = asof or datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)   # 11:00 ET
    rng = random.Random(seed)
    futures = src.kind.value == "FUT"
    q = rate if futures else 0.0
    atm = round(spot / step) * step
    contracts = []
    today = asof.astimezone(marketcal.NY).date()
    for dte in dtes:
        d = today + timedelta(days=dte)
        while not marketcal.is_trading_day(d):
            d += timedelta(days=1)
        root = {"SPX": "SPXW", "NDX": "NDXP"}.get(source_key, src.vendor_symbol)
        exp = marketcal.option_expiry_time(d, root)
        t = max((exp - asof).total_seconds() / (365 * 86400), pricing.MIN_T)
        for i in range(-n_strikes // 2, n_strikes // 2 + 1):
            k = atm + i * step
            m = math.log(k / spot)
            iv = max(0.05, base_iv - 0.35 * m + 0.8 * m * m)   # put skew + smile
            # OI: calls concentrated above spot, puts below, round strikes heavier
            round_bonus = 3.0 if (k / step) % 10 == 0 else (1.6 if (k / step) % 5 == 0 else 1.0)
            for typ in (OptionType.CALL, OptionType.PUT):
                centre = 0.02 if typ == OptionType.CALL else -0.03
                w = math.exp(-((m - centre) ** 2) / (2 * 0.02 ** 2))
                oi = int((200 + 6000 * w) * round_bonus * (1.0 + 0.3 * rng.random()) / (1 + dte / 10))
                g = pricing.model_gamma(spot, k, t, rate, q, iv, futures)
                price = pricing.bsm_price(spot, k, t, rate, q, iv, typ == OptionType.CALL)
                spread = max(0.05, price * 0.02)
                contracts.append(OptionContract(
                    symbol=f"{root}{d:%y%m%d}{typ.value}{int(round(k * 1000)):08d}", root=root,
                    underlying=src.vendor_symbol, option_type=typ, strike=k, expiration=exp,
                    multiplier=src.multiplier, open_interest=float(oi), volume=float(oi // 4),
                    bid=max(0.0, price - spread / 2), ask=price + spread / 2, last=price, last_time=asof,
                    iv=iv, gamma=g, delta=pricing.bsm_delta(spot, k, t, rate, q, iv, typ == OptionType.CALL),
                    quote_quality=Quality.SYNTHETIC, oi_quality=Quality.SYNTHETIC, greeks_quality=Quality.SYNTHETIC,
                    greeks_time=asof, exercise_style=src.exercise))
    return ChainSnapshot(underlying=src.vendor_symbol, source_kind=src.kind, spot=spot, spot_time=asof,
                         spot_quality=Quality.SYNTHETIC, contracts=contracts, source="synthetic", fetched_at=asof,
                         rate=rate, div_yield=0.0, warnings=["SYNTHETIC data - not market data"])


class SyntheticProvider(Provider):
    name = "synthetic"

    def __init__(self, seed: int = 7, spot: Optional[float] = None, live_clock: bool = True):
        self.seed, self.spot, self.live_clock = seed, spot, live_clock
        self._n = 0

    def fetch_snapshot(self, source_key: str, max_dte: float = 45, include_0dte: bool = True) -> ChainSnapshot:
        self._n += 1
        asof = datetime.now(timezone.utc) if self.live_clock else None
        spot = (self.spot or DEFAULT_SPOTS[source_key]) * (1 + 0.001 * math.sin(self._n))
        dtes = tuple(d for d in (0, 1, 3, 7, 14, 30) if d <= max_dte and (d > 0 or include_0dte))
        return make_chain(source_key, spot=spot, asof=asof, dtes=dtes, seed=self.seed + self._n)
