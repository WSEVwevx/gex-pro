"""Schwab Trader API market data: option chains (SPX/NDX/SPY/QQQ) and futures + index quotes.

Endpoints (base https://api.schwabapi.com, from the schwab-py source, 2026-10-21):
  GET /marketdata/v1/chains?symbol=$SPX&contractType=ALL&strikeCount=..&includeUnderlyingQuote=true
      &strategy=SINGLE&fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD
  GET /marketdata/v1/quotes?symbols=/ES,$SPX

Response shape (callExpDateMap / putExpDateMap keyed "YYYY-MM-DD:dte" then by strike, each a list of
contracts) follows the documented Schwab/TD Ameritrade layout. Every field is read defensively:
a missing or invalid value becomes "missing", never a guess.  NOT verified against a live account
in this build - see docs/SCHWAB_SETUP.md "first-run check".

Data quality
* Quotes: real time if the response says so (isDelayed / realtime flags); otherwise the label comes
  from SCHWAB_QUOTE_QUALITY (default DL - conservative) and a warning says it was not stated.
* volatility is in percent; values <= 0, NaN or the -999 placeholder become missing.
* open interest is end of day, like everywhere.
* futures_basis(): /ES or /NQ and the cash index from ONE quotes request, so the basis is
  time-matched when both are trading (the mapping refuses it if the trade times are >60 s apart).
"""
from __future__ import annotations

import math
import os
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from .. import marketcal
from ..mapping import FUTURES, SOURCES
from ..models import ChainSnapshot, OptionContract, OptionType, Quality
from ..normalize import parse_occ
from .base import AuthError, Provider, ProviderError, RateLimiter, http_get_json
from .schwab_auth import TokenStore

BASE = "https://api.schwabapi.com"
SYMBOLS = {"SPX": "$SPX", "NDX": "$NDX", "SPY": "SPY", "QQQ": "QQQ"}
FUT_SYMBOLS = {"ES": "/ES", "MES": "/ES", "NQ": "/NQ", "MNQ": "/NQ"}


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _ms(x) -> Optional[datetime]:
    v = _f(x)
    return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc) if v and v > 0 else None


class SchwabProvider(Provider):
    name = "schwab"
    label = "SCHWAB"

    def __init__(self, strike_count: int = 200, requests_per_minute: float = 100.0,
                 tokens: Optional[TokenStore] = None, http: Callable = http_get_json):
        self.strike_count = strike_count
        self.tokens = tokens or TokenStore()
        self.limiter = RateLimiter(requests_per_minute)
        self._http = http

    def _get(self, path: str, **params) -> dict:
        token = self.tokens.access_token()                       # raises AuthError when a login is needed
        url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
        return self._http(url, {"Authorization": f"Bearer {token}", "Accept": "application/json"}, limiter=self.limiter)

    def _quality(self, delayed_flag) -> tuple[Quality, Optional[str]]:
        if delayed_flag is True:
            return Quality.DELAYED, None
        if delayed_flag is False:
            return Quality.REALTIME, None
        q = Quality(os.environ.get("SCHWAB_QUOTE_QUALITY", "DL").upper())
        return q, f"Schwab did not state real-time vs delayed; labeled {q.value} from SCHWAB_QUOTE_QUALITY"

    def fetch_snapshot(self, source_key: str, max_dte: float = 45, include_0dte: bool = True) -> ChainSnapshot:
        if source_key not in SYMBOLS:
            raise ProviderError(f"Schwab adapter supports {sorted(SYMBOLS)}, not {source_key}")
        src = SOURCES[source_key]
        now = datetime.now(timezone.utc)
        today = now.astimezone(marketcal.NY).date()
        d = self._get("/marketdata/v1/chains", symbol=SYMBOLS[source_key], contractType="ALL",
                      strikeCount=self.strike_count, includeUnderlyingQuote="true", strategy="SINGLE",
                      fromDate=(today if include_0dte else today + timedelta(days=1)).isoformat(),
                      toDate=(today + timedelta(days=int(max_dte))).isoformat())
        if str(d.get("status", "SUCCESS")).upper() not in ("SUCCESS", ""):
            raise ProviderError(f"Schwab chain status {d.get('status')}")
        und = d.get("underlying") or {}
        spot = _f(und.get("last")) or _f(d.get("underlyingPrice")) or _f(und.get("mark"))
        spot_time = _ms(und.get("tradeTime")) or _ms(und.get("quoteTime")) or now
        quote_q, note = self._quality(d.get("isDelayed", und.get("delayed")))
        contracts, bad = [], 0
        for side, typ in (("callExpDateMap", OptionType.CALL), ("putExpDateMap", OptionType.PUT)):
            for exp_key, strikes in (d.get(side) or {}).items():
                try:
                    exp_d = date.fromisoformat(exp_key.split(":")[0])
                except ValueError:
                    bad += 1
                    continue
                for k_key, lst in (strikes or {}).items():
                    for o in lst or []:
                        c = self._contract(o, typ, exp_d, k_key, src, quote_q)
                        if c is None:
                            bad += 1
                        else:
                            contracts.append(c)
        if not contracts:
            raise ProviderError(f"Schwab returned no usable {source_key} contracts")
        warnings = [f"Schwab: quotes {quote_q.value}, OI end-of-day"]
        if note:
            warnings.append(note)
        if bad:
            warnings.append(f"schwab: {bad} unparseable contracts skipped")
        return ChainSnapshot(underlying=src.vendor_symbol, source_kind=src.kind, spot=spot, spot_time=spot_time,
                             spot_quality=quote_q if spot else Quality.MISSING, contracts=contracts,
                             source="schwab:trader-api", fetched_at=now, warnings=warnings,
                             prev_close=_f(und.get("close")),
                             rate=float(os.environ.get("GEX_RISK_FREE_RATE", "0.04")),
                             div_yield=float(os.environ.get(f"GEX_DIV_YIELD_{source_key}", "0.0")))

    def _contract(self, o: dict, typ: OptionType, exp_d: date, k_key: str, src, quote_q: Quality) -> Optional[OptionContract]:
        sym = str(o.get("symbol", ""))
        p = parse_occ(sym)
        strike = _f(o.get("strikePrice")) or _f(k_key)
        if not strike or strike <= 0:
            return None
        root = str(o.get("optionRoot") or (p["root"] if p else src.vendor_symbol))
        vol = _f(o.get("volatility"))
        iv = vol / 100.0 if vol is not None and 0 < vol < 500 else None
        gamma = _f(o.get("gamma"))
        gamma = gamma if gamma is not None and gamma >= 0 else None
        return OptionContract(
            symbol=sym or f"{root}-{exp_d}-{typ.value}-{strike}", root=root, underlying=src.vendor_symbol,
            option_type=typ, strike=strike, expiration=marketcal.option_expiry_time(exp_d, root),
            multiplier=_f(o.get("multiplier")) or src.multiplier, open_interest=_f(o.get("openInterest")),
            volume=_f(o.get("totalVolume")), bid=_f(o.get("bid")), ask=_f(o.get("ask")), last=_f(o.get("last")),
            last_time=_ms(o.get("tradeTimeInLong")), iv=iv, gamma=gamma, delta=_f(o.get("delta")),
            quote_quality=quote_q, oi_quality=Quality.EOD,
            greeks_quality=Quality.PROVIDER_CALC if gamma is not None else Quality.MISSING,
            greeks_time=_ms(o.get("quoteTimeInLong")), exercise_style=src.exercise)

    def futures_basis(self, market: str, source_key: str) -> Optional[tuple]:
        """(futures price, futures time, index price, index time, label) from one quotes request."""
        fsym, isym = FUT_SYMBOLS.get(FUTURES[market].full_size_root), SYMBOLS.get(source_key)
        if not fsym or not isym:
            return None
        d = self._get("/marketdata/v1/quotes", symbols=f"{fsym},{isym}")

        def pick(prefix):
            for k, v in d.items():
                if k == prefix or (prefix.startswith("/") and k.startswith(prefix)):
                    q = (v or {}).get("quote") or {}
                    px = _f(q.get("lastPrice")) or _f(q.get("mark"))
                    return px, _ms(q.get("tradeTime")) or _ms(q.get("quoteTime")), k
            return None, None, None
        fp, ft, fk = pick(fsym)
        sp, st, _ = pick(isym)
        if not fp or not sp or not ft or not st:
            return None
        return fp, ft, sp, st, f"Schwab quotes {fk} vs {isym}"


class FallbackProvider(Provider):
    """Primary source with automatic fallback (e.g. Schwab -> Cboe).  Every result says which
    source actually produced it; the reason for a fallback is added to the warnings."""

    def __init__(self, primary: Provider, fallback: Provider):
        self.primary, self.fallback = primary, fallback
        self.name, self.label = primary.name, primary.label
        self.last_label = primary.label
        self._used = primary

    def fetch_snapshot(self, source_key: str, max_dte: float = 45, include_0dte: bool = True) -> ChainSnapshot:
        try:
            snap = self.primary.fetch_snapshot(source_key, max_dte, include_0dte)
            self._used, self.last_label = self.primary, self.primary.label
            return snap
        except (AuthError, ProviderError, OSError) as e:
            snap = self.fallback.fetch_snapshot(source_key, max_dte, include_0dte)
            self._used, self.last_label = self.fallback, self.fallback.label
            snap.warnings.append(f"{self.primary.label} unavailable ({e}); using {self.fallback.label}")
            return snap

    def futures_basis(self, market: str, source_key: str) -> Optional[tuple]:
        fb = getattr(self._used, "futures_basis", None)
        if fb is None:
            return None
        try:
            return fb(market, source_key)
        except (AuthError, ProviderError, OSError):
            return None
