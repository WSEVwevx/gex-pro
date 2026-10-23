"""Cboe free delayed options feed (the JSON behind cboe.com's delayed quote pages).

  GET https://cdn.cboe.com/api/global/delayed_quotes/options/{_SPX|_NDX|SPY|QQQ}.json

Verified 2026-10-21 against live responses: one request returns the whole chain
(all expirations) with bid/ask, volume, open_interest, iv, delta, gamma, ...,
plus data.current_price for the underlying.  Top-level `timestamp` is UTC.

Data-quality handling
* Quotes are 15-minute delayed -> DELAYED.  The reference price is stamped
  timestamp - 15 min to reflect the delay.
* open_interest -> EOD.
* Cboe's gamma is rounded to 4 decimals (NDX gamma ~0.0004 loses >10% precision),
  so configs for this provider set engine.recompute_greeks = "always": gamma is
  recomputed from Cboe's IV (tagged CALC).  iv == 0 is treated as missing.
* Unofficial endpoint (no API contract, may change) intended for personal use;
  see docs/DATA_PROVIDERS.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import marketcal
from ..mapping import SOURCES
from ..models import ChainSnapshot, OptionContract, Quality
from ..normalize import parse_occ
from .base import Provider, ProviderError, RateLimiter, http_get_json

URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
SYMBOLS = {"SPX": "_SPX", "NDX": "_NDX", "SPY": "SPY", "QQQ": "QQQ"}
DELAY = timedelta(minutes=15)


def _f(x) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


class CboeProvider(Provider):
    name = "cboe"
    label = "CBOE"

    def __init__(self, requests_per_minute: float = 6.0, http=http_get_json):
        self._http = http
        self.limiter = RateLimiter(requests_per_minute)

    def fetch_snapshot(self, source_key: str, max_dte: float = 45, include_0dte: bool = True) -> ChainSnapshot:
        if source_key not in SYMBOLS:
            raise ProviderError(f"Cboe free feed adapter supports {sorted(SYMBOLS)}, not {source_key}")
        src = SOURCES[source_key]
        d = self._http(URL.format(sym=SYMBOLS[source_key]),
                       {"User-Agent": "Mozilla/5.0 (gexsys personal use)", "Accept": "application/json"},
                       limiter=self.limiter)
        data = d.get("data") or {}
        try:
            ts = datetime.strptime(d["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError) as e:
            raise ProviderError("Cboe response missing/invalid timestamp") from e
        spot = _f(data.get("current_price"))
        # the underlying's own last trade time (ET) is the honest timestamp for current_price;
        # fall back to snapshot time minus the 15-minute delay
        spot_time = ts - DELAY
        if data.get("last_trade_time"):
            try:
                spot_time = min(spot_time, datetime.fromisoformat(data["last_trade_time"]).replace(tzinfo=marketcal.NY))
            except ValueError:
                pass
        today = ts.astimezone(marketcal.NY).date()
        contracts, bad = [], 0
        for o in data.get("options") or []:
            p = parse_occ(str(o.get("option", "")))
            if p is None:
                bad += 1
                continue
            dte = (p["expiration"] - today).days
            if dte < 0 or dte > max_dte or (dte == 0 and not include_0dte):
                continue
            iv = _f(o.get("iv"))
            gamma = _f(o.get("gamma"))
            lt = o.get("last_trade_time")
            last_time = None
            if lt:
                try:
                    last_time = datetime.fromisoformat(lt).replace(tzinfo=marketcal.NY)
                except ValueError:
                    pass
            contracts.append(OptionContract(
                symbol=o["option"], root=p["root"], underlying=src.vendor_symbol, option_type=p["type"],
                strike=p["strike"], expiration=marketcal.option_expiry_time(p["expiration"], p["root"]),
                multiplier=src.multiplier, open_interest=_f(o.get("open_interest")), volume=_f(o.get("volume")),
                bid=_f(o.get("bid")), ask=_f(o.get("ask")), last=_f(o.get("last_trade_price")), last_time=last_time,
                iv=iv if iv and iv > 0 else None, gamma=gamma, delta=_f(o.get("delta")),
                quote_quality=Quality.DELAYED, oi_quality=Quality.EOD,
                greeks_quality=Quality.PROVIDER_CALC if gamma is not None else Quality.MISSING,
                greeks_time=ts - DELAY, exercise_style=src.exercise))
        warnings = ["Cboe free feed: quotes 15-min DELAYED, OI end-of-day"]
        if bad:
            warnings.append(f"cboe: {bad} unparseable option symbols skipped")
        if not contracts:
            raise ProviderError(f"Cboe returned no usable {source_key} contracts within {max_dte} DTE")
        return ChainSnapshot(underlying=src.vendor_symbol, source_kind=src.kind, spot=spot,
                             spot_time=spot_time if spot else None,
                             spot_quality=Quality.DELAYED if spot else Quality.MISSING, contracts=contracts,
                             source="cboe:delayed", fetched_at=datetime.now(timezone.utc), warnings=warnings,
                             prev_close=_f(data.get("prev_day_close")))
