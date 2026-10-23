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

ETF options merged into the index chain (include_etf=True: SPY into SPX, QQQ into NDX)
* The ETF tracks the index at ratio r = index price / ETF price (~10 for SPY, ~41 for QQQ).
* Each ETF option becomes an index-equivalent contract: strike x r (snapped to the nearest
  listed index strike), open interest and volume / r.  BSM gamma scales as 1/r when price and
  strike both scale by r, so OI/r x gamma/r x multiplier x (r S)^2 equals the ETF option's own
  dollar gamma: GEX, walls, max pain and put/call ratios stay consistent in index contracts.
* IV is kept (the ETF's own); bid/ask are dropped because they are not in index units.
"""
from __future__ import annotations

import bisect
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import marketcal
from ..mapping import SOURCES
from ..models import ChainSnapshot, OptionContract, Quality
from ..normalize import parse_occ
from .base import Provider, ProviderError, RateLimiter, http_get_json

URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
SYMBOLS = {"SPX": "_SPX", "NDX": "_NDX", "SPY": "SPY", "QQQ": "QQQ"}
ETF_FOR = {"SPX": "SPY", "NDX": "QQQ"}
DELAY = timedelta(minutes=15)


def _f(x) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


class CboeProvider(Provider):
    name = "cboe"
    label = "CBOE"

    def __init__(self, requests_per_minute: float = 6.0, http=http_get_json, include_etf: bool = False):
        self._http = http
        self.limiter = RateLimiter(requests_per_minute)
        self.include_etf = include_etf

    def _chain(self, source_key: str, max_dte: float, include_0dte: bool) -> dict:
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
        return {"spot": spot, "spot_time": spot_time, "contracts": contracts, "bad": bad, "ts": ts,
                "prev_close": _f(data.get("prev_day_close"))}

    def fetch_snapshot(self, source_key: str, max_dte: float = 45, include_0dte: bool = True) -> ChainSnapshot:
        ch = self._chain(source_key, max_dte, include_0dte)
        src = SOURCES[source_key]
        spot, contracts = ch["spot"], ch["contracts"]
        warnings = ["Cboe free feed: quotes 15-min DELAYED, OI end-of-day"]
        if ch["bad"]:
            warnings.append(f"cboe: {ch['bad']} unparseable option symbols skipped")
        if not contracts:
            raise ProviderError(f"Cboe returned no usable {source_key} contracts within {max_dte} DTE")
        etf = ETF_FOR.get(source_key) if self.include_etf else None
        if etf and spot:
            try:
                ech = self._chain(etf, max_dte, include_0dte)
            except ProviderError as e:                   # the index chain alone is still valid
                warnings.append(f"cboe: {etf} options unavailable ({e}); levels from {source_key} only")
            else:
                if ech["spot"] and ech["contracts"]:
                    r = spot / ech["spot"]
                    contracts = contracts + merge_etf(contracts, ech["contracts"], r, source_key, src.multiplier)
                    warnings.append(f"includes {etf} options in {source_key} terms "
                                    f"({r:.2f} {etf} contracts = 1 {source_key} contract)")
        return ChainSnapshot(underlying=src.vendor_symbol, source_kind=src.kind, spot=spot,
                             spot_time=ch["spot_time"] if spot else None,
                             spot_quality=Quality.DELAYED if spot else Quality.MISSING, contracts=contracts,
                             source="cboe:delayed", fetched_at=datetime.now(timezone.utc), warnings=warnings,
                             prev_close=ch["prev_close"])


def merge_etf(index_contracts: list[OptionContract], etf_contracts: list[OptionContract], ratio: float,
              index_key: str, index_multiplier: float) -> list[OptionContract]:
    """ETF options -> index-equivalent contracts (see module notes). Strikes snap to listed index
    strikes; ETF strikes that land on the same index strike are added together."""
    strikes = sorted({c.strike for c in index_contracts})
    gaps = sorted(b - a for a, b in zip(strikes, strikes[1:]) if b > a)
    tol = 0.75 * (gaps[len(gaps) // 2] if gaps else 1.0)
    out: dict[tuple, OptionContract] = {}
    for c in etf_contracts:
        k = c.strike * ratio
        i = bisect.bisect_left(strikes, k)
        near = min((strikes[j] for j in (i - 1, i) if 0 <= j < len(strikes)), key=lambda s: abs(s - k), default=None)
        k = near if near is not None and abs(near - k) <= tol else round(k, 2)
        key = (c.root, c.option_type, k, c.expiration)
        oi = None if c.open_interest is None else c.open_interest / ratio
        vol = (c.volume or 0.0) / ratio
        if key in out:
            prev = out[key]
            out[key] = replace(prev, open_interest=(prev.open_interest or 0.0) + (oi or 0.0),
                               volume=(prev.volume or 0.0) + vol)
            continue
        out[key] = replace(c, symbol=f"{c.symbol}@{index_key}", strike=k, multiplier=index_multiplier,
                           open_interest=oi, volume=vol, bid=None, ask=None, last=None, gamma=None,
                           delta=None, greeks_quality=Quality.MISSING)
    return list(out.values())
