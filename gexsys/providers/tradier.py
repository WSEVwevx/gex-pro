"""Tradier market-data adapter (SPX/SPXW, NDX/NDXP, SPY, QQQ).

Endpoints used (docs.tradier.com, Brokerage API > Markets):
  GET /v1/markets/quotes?symbols=SPX
  GET /v1/markets/options/expirations?symbol=SPX&includeAllRoots=true
  GET /v1/markets/options/chains?symbol=SPX&expiration=YYYY-MM-DD&greeks=true

Data-quality handling
* Tradier's response does not state whether a quote is real-time or delayed; that
  depends on account type and exchange entitlements.  The user must declare it with
  TRADIER_QUOTE_QUALITY (RT|DL).  Sandbox is always treated as delayed.
* open_interest is always tagged EOD (OCC publishes OI once per day).
* Greeks/IV are documented as supplied by ORATS -> tagged PROVIDER_CALC with the
  vendor's updated_at timestamp.  updated_at carries no zone; it is interpreted as
  America/New_York (assumption, see docs/DATA_PROVIDERS.md).
* Tradier does not offer CME futures options; use the CSV adapter for ES/NQ options.

Verified against documentation only - NOT against live responses (no credentials).
"""
from __future__ import annotations

import os
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

from .. import marketcal
from ..mapping import SOURCES
from ..models import ChainSnapshot, OptionContract, OptionType, Quality
from .base import AuthError, Provider, ProviderError, RateLimiter, http_get_json

PROD = "https://api.tradier.com/v1"
SANDBOX = "https://sandbox.tradier.com/v1"


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _f(x) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _ms(x) -> Optional[datetime]:
    v = _f(x)
    return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc) if v and v > 0 else None


class TradierProvider(Provider):
    name = "tradier"

    def __init__(self, token: Optional[str] = None, base_url: Optional[str] = None,
                 quote_quality: Optional[str] = None, requests_per_minute: float = 60.0, http=http_get_json):
        self.token = token if token is not None else os.environ.get("TRADIER_TOKEN", "")
        self.base = (base_url or os.environ.get("TRADIER_BASE_URL") or PROD).rstrip("/")
        qq = (quote_quality or os.environ.get("TRADIER_QUOTE_QUALITY") or "DL").upper()
        if qq not in ("RT", "DL"):
            raise ValueError("TRADIER_QUOTE_QUALITY must be RT or DL")
        self.quote_quality = Quality.DELAYED if "sandbox" in self.base else Quality(qq)
        self.limiter = RateLimiter(requests_per_minute)
        self._http = http

    def _get(self, path: str, **params) -> dict:
        if not self.token:
            raise AuthError("TRADIER_TOKEN is not set - see docs/DATA_PROVIDERS.md")
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        return self._http(url, {"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
                          limiter=self.limiter)

    def quote(self, symbol: str) -> tuple[Optional[float], Optional[datetime]]:
        data = self._get("/markets/quotes", symbols=symbol)
        q = _as_list((data.get("quotes") or {}).get("quote"))
        if not q:
            raise ProviderError(f"no quote returned for {symbol}")
        q = q[0]
        price = _f(q.get("last"))
        if price is None and _f(q.get("bid")) and _f(q.get("ask")):
            price = 0.5 * (_f(q["bid"]) + _f(q["ask"]))
        return price, _ms(q.get("trade_date"))

    def expirations(self, symbol: str) -> list[str]:
        data = self._get("/markets/options/expirations", symbol=symbol, includeAllRoots="true")
        return [str(d) for d in _as_list((data.get("expirations") or {}).get("date"))]

    def fetch_snapshot(self, source_key: str, max_dte: float, include_0dte: bool) -> ChainSnapshot:
        src = SOURCES[source_key]
        if src.kind.value == "FUT":
            raise ProviderError("Tradier does not provide CME futures options; use the csv provider")
        now = datetime.now(timezone.utc)
        spot, spot_time = self.quote(src.vendor_symbol)
        today = now.astimezone(marketcal.NY).date()
        dates = []
        for d in self.expirations(src.vendor_symbol):
            dd = datetime.strptime(d, "%Y-%m-%d").date()
            dte = (dd - today).days
            if dte < 0 or dte > max_dte or (dte == 0 and not include_0dte):
                continue
            dates.append(d)
        contracts: list[OptionContract] = []
        for d in dates:
            data = self._get("/markets/options/chains", symbol=src.vendor_symbol, expiration=d, greeks="true")
            for o in _as_list((data.get("options") or {}).get("option")):
                c = self._contract(o, src)
                if c is not None:
                    contracts.append(c)
        warnings = []
        if self.quote_quality == Quality.DELAYED:
            warnings.append("quotes declared DELAYED (TRADIER_QUOTE_QUALITY / sandbox)")
        return ChainSnapshot(underlying=src.vendor_symbol, source_kind=src.kind, spot=spot, spot_time=spot_time,
                             spot_quality=self.quote_quality if spot is not None else Quality.MISSING,
                             contracts=contracts, source=f"tradier:{'sandbox' if 'sandbox' in self.base else 'prod'}",
                             fetched_at=now, warnings=warnings,
                             div_yield=float(os.environ.get(f"GEX_DIV_YIELD_{source_key}", "0.0")),
                             rate=float(os.environ.get("GEX_RISK_FREE_RATE", "0.04")))

    def _contract(self, o: dict, src) -> Optional[OptionContract]:
        try:
            root = o.get("root_symbol") or src.vendor_symbol
            exp_date = datetime.strptime(o["expiration_date"], "%Y-%m-%d").date()
            g = o.get("greeks") or {}
            gt = None
            if g.get("updated_at"):
                try:
                    gt = datetime.strptime(g["updated_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=marketcal.NY)
                except ValueError:
                    gt = None
            gamma, iv = _f(g.get("gamma")), _f(g.get("mid_iv")) or _f(g.get("smv_vol"))
            return OptionContract(
                symbol=o["symbol"], root=root, underlying=o.get("underlying") or src.vendor_symbol,
                option_type=OptionType.CALL if o["option_type"] == "call" else OptionType.PUT,
                strike=float(o["strike"]), expiration=marketcal.option_expiry_time(exp_date, root),
                multiplier=float(o.get("contract_size") or src.multiplier),
                open_interest=_f(o.get("open_interest")), volume=_f(o.get("volume")),
                bid=_f(o.get("bid")), ask=_f(o.get("ask")), last=_f(o.get("last")), last_time=_ms(o.get("trade_date")),
                iv=iv if iv and iv > 0 else None, gamma=gamma, delta=_f(g.get("delta")),
                quote_quality=self.quote_quality, oi_quality=Quality.EOD,
                greeks_quality=Quality.PROVIDER_CALC if gamma is not None else Quality.MISSING,
                greeks_time=gt, exercise_style=src.exercise,
            )
        except (KeyError, ValueError, TypeError):
            return None
