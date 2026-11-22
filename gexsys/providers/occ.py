"""Backup chain for when Cboe refuses us: OCC open interest + one implied vol per expiry from Cboe's VIX-family
daily closes + Yahoo prices. Used only by FallbackProvider, only after Cboe answers 401/403 (Cboe began refusing
automated requests on 2026-11-19; nothing here works around that).

Sources (all free, no key; proven from GitHub's servers by tools/probe_sources.py):
  OCC   GET https://marketdata.theocc.com/series-search?symbolType=U&symbol={NDX|SPX|QQQ|SPY}
        tab-separated: product, -, year, month, day, strike integer, strike decimals (thousandths), "C P",
        call OI, put OI, position limit. End-of-day open interest across all exchanges; the file carries no date.
  Vols  GET https://cdn.cboe.com/api/global/us_indices/daily_prices/{VIX1D|VIX9D|VIX|VIX3M|VXN}_History.csv
        DATE,OPEN,HIGH,LOW,CLOSE (percent); the index's daily close.
  Price GET https://query1.finance.yahoo.com/v8/finance/chart/{^NDX|^GSPC|QQQ|SPY}?range=1d&interval=1d (chart meta)

Implied vol (no per-strike quotes, so no skew):
  SPX: total variance w(d) = (VIX_d / 100)^2 x d at d = 1, 9, 30, 93 days (VIX1D, VIX9D, VIX, VIX3M; only points
       dated like the newest one), linear in w between points; flat beyond the ends. iv(T) = sqrt(w(T) / T).
  NDX: the SPX curve x VXN / iv_SPX(30 days) (VXN is the 30-day NDX index; there is no shorter one).
  ETF options (QQQ, SPY) take their index's vol.
Each contract gets that vol; the engine computes gamma from it. Gamma per strike is therefore an estimate: the
2026-11-19 comparison (all-expiry walls and zero gamma within 0.06 expected moves of Cboe's; ranks 2-3, Ab1 and the
0DTE flip far off) is why the pipeline keeps only the first-ranked near-dated levels from this source.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .. import marketcal
from ..mapping import SOURCES
from ..models import ChainSnapshot, OptionContract, OptionType, Quality
from .base import AuthError, ProviderError, ProviderUnavailable
from .cboe import ETF_FOR, ETF_RATIO, STANDARD_ROOTS, dividend_yield, merge_etf, risk_free_rate

OCC_URL = "https://marketdata.theocc.com/series-search?symbolType=U&symbol={sym}"
VOL_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{name}_History.csv"
PRICE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=1d"
YAHOO_SYM = {"NDX": "^NDX", "SPX": "^GSPC", "QQQ": "QQQ", "SPY": "SPY"}
UA = {"User-Agent": "Mozilla/5.0 (GEX PRO)"}
CURVE = (("VIX1D", 1), ("VIX9D", 9), ("VIX", 30), ("VIX3M", 93))
CACHE_S = 3600          # open interest and the vol closes change once a day: fetch each at most hourly
RETRY_PRIMARY_S = 900   # while Cboe refuses, ask it again every 15 min (the worker's own refusal back-off), not every refresh


def parse_series(text: str) -> list[tuple[str, date, float, float, float]]:
    """(product, expiry, strike, call OI, put OI) from OCC's series-search text; other lines are skipped."""
    out = []
    for line in text.splitlines():
        f = [x.strip() for x in line.split("\t")]
        if len(f) < 10 or not (f[2].isdigit() and f[3].isdigit() and f[4].isdigit() and f[5].isdigit() and f[6].isdigit()):
            continue
        try:
            exp = date(int(f[2]), int(f[3]), int(f[4]))
            out.append((f[0], exp, int(f[5]) + int(f[6]) / 1000.0, float(f[8] or 0), float(f[9] or 0)))
        except ValueError:
            continue
    return out


def last_close(text: str) -> Optional[tuple[date, float]]:
    """The newest (date, close as a decimal) in a Cboe daily_prices CSV."""
    best = None
    for r in csv.reader(io.StringIO(text)):
        if len(r) < 5:
            continue
        try:
            d = datetime.strptime(r[0].strip(), "%m/%d/%Y").date()
            v = float(r[4])
        except ValueError:
            continue
        if v > 0 and (best is None or d > best[0]):
            best = (d, v / 100.0)
    return best


def vol_curve(closes: dict[str, tuple[date, float]]) -> tuple[list[tuple[float, float]], date]:
    """[(days, vol)] from the curve indices dated like the newest one, and that date."""
    have = {n: closes[n] for n, _ in CURVE if n in closes}
    if not have:
        raise ProviderUnavailable("no VIX-family close available")
    newest = max(d for d, _ in have.values())
    pts = [(float(days), have[n][1]) for n, days in CURVE if n in have and have[n][0] == newest]
    return pts, newest


def curve_iv(pts: list[tuple[float, float]], days: float) -> float:
    """Vol for `days`, linear in total variance between the points, flat beyond the ends."""
    days = max(days, 1e-9)
    if days <= pts[0][0]:
        return pts[0][1]
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        if days <= d1:
            w0, w1 = v0 * v0 * d0, v1 * v1 * d1
            return math.sqrt((w0 + (w1 - w0) * (days - d0) / (d1 - d0)) / days)
    return pts[-1][1]


class OccProvider:
    name = "occ"
    label = "OCC"

    def __init__(self, cache_dir: Optional[str] = None, opener: Callable = urllib.request.urlopen,
                 clock: Callable[[], float] = time.time):
        self.cache = Path(cache_dir) if cache_dir else None
        self.opener, self.clock = opener, clock
        self.vol_date: Optional[date] = None

    def _get(self, url: str, key: str) -> str:
        """Text from url, from the cache when fetched within CACHE_S; 401/403 -> AuthError, else ProviderUnavailable."""
        f = self.cache / f"{key}.txt" if self.cache else None
        if f and f.exists() and self.clock() - f.stat().st_mtime < CACHE_S:
            return f.read_text(encoding="utf-8")
        try:
            with self.opener(urllib.request.Request(url, headers=UA), timeout=30) as r:
                text = r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise AuthError(f"HTTP {e.code}: {url.split('/')[2]} refused the request") from e
            raise ProviderUnavailable(f"HTTP {e.code} from {url.split('/')[2]}") from e
        except (OSError, ValueError) as e:
            raise ProviderUnavailable(f"{url.split('/')[2]}: {e}") from e
        if f:
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                tmp = f.with_suffix(".tmp")
                tmp.write_text(text, encoding="utf-8")
                os.replace(tmp, f)
            except OSError:
                pass
        return text

    def _price(self, sym: str) -> dict:
        """{price, prev, time} from Yahoo's chart meta (gexsys may not import feeds, so it reads the three fields here)."""
        try:
            with self.opener(urllib.request.Request(PRICE_URL.format(sym=urllib.parse.quote(YAHOO_SYM[sym])), headers=UA), timeout=15) as r:
                m = json.loads(r.read())["chart"]["result"][0]["meta"]
            price, prev = float(m["regularMarketPrice"]), float(m["chartPreviousClose"])
            t = datetime.fromtimestamp(int(m.get("regularMarketTime") or 0), timezone.utc)
        except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
            raise ProviderUnavailable(f"no Yahoo price for {YAHOO_SYM[sym]}: {e}") from e
        if not (math.isfinite(price) and math.isfinite(prev)) or price <= 0 or prev <= 0:
            raise ProviderUnavailable(f"no Yahoo price for {YAHOO_SYM[sym]}")
        return {"price": price, "prev": prev, "time": t}

    def _contracts(self, sym: str, key: str, mult: float, ivs: Callable[[datetime], float], now: datetime,
                   max_dte: float, include_0dte: bool) -> list[OptionContract]:
        roots = STANDARD_ROOTS.get(sym)
        today = now.astimezone(marketcal.NY).date()
        out = []
        for prod, ed, k, c_oi, p_oi in parse_series(self._get(OCC_URL.format(sym=sym), f"occ_{sym}")):
            if roots and prod not in roots:
                continue
            dte = (ed - today).days
            if dte < 0 or dte > max_dte or (dte == 0 and not include_0dte):
                continue
            exp = marketcal.option_expiry_time(ed, prod)
            if exp <= now:
                continue
            iv = ivs(exp)
            for typ, oi in ((OptionType.CALL, c_oi), (OptionType.PUT, p_oi)):
                if oi <= 0:
                    continue
                out.append(OptionContract(
                    symbol=f"{prod}{ed:%y%m%d}{typ.value}{int(round(k * 1000)):08d}", root=prod, underlying=key,
                    option_type=typ, strike=k, expiration=exp, multiplier=mult, open_interest=oi, iv=iv,
                    quote_quality=Quality.MISSING, oi_quality=Quality.EOD, greeks_quality=Quality.MISSING,
                    exercise_style="european" if sym in ("NDX", "SPX") else "american"))
        return out

    def fetch_snapshot(self, source_key: str, max_dte: float = 45, include_0dte: bool = True) -> ChainSnapshot:
        if source_key not in ("NDX", "SPX"):
            raise ProviderError(f"the OCC backup covers NDX and SPX, not {source_key}")
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        closes = {}
        for n in [c for c, _ in CURVE] + (["VXN"] if source_key == "NDX" else []):
            got = last_close(self._get(VOL_URL.format(name=n), f"vol_{n}"))
            if got:
                closes[n] = got
        pts, vd = vol_curve(closes)
        scale = 1.0
        if source_key == "NDX":
            if "VXN" not in closes or closes["VXN"][0] != vd:
                raise ProviderUnavailable(f"no VXN close for {vd} to scale the vol curve to NDX")
            scale = closes["VXN"][1] / curve_iv(pts, 30)
        self.vol_date = vd
        ivs = lambda exp: scale * curve_iv(pts, (exp - now).total_seconds() / 86400)
        src = SOURCES[source_key]
        spot_q = self._price(source_key)
        spot = spot_q["price"]
        contracts = self._contracts(source_key, source_key, src.multiplier, ivs, now, max_dte, include_0dte)
        if not contracts:
            raise ProviderUnavailable(f"OCC returned no usable {source_key} series within {max_dte} days")
        warnings = [f"BACKUP ESTIMATE: Cboe refused; OCC open interest (end of day) with one implied vol per expiry "
                    f"from the {vd:%b %d} VIX-family closes{' scaled by VXN' if source_key == 'NDX' else ''} (no skew)"]
        missing = [n for n, _ in CURVE if n not in closes or closes[n][0] != vd]
        if missing:
            warnings.append(f"occ: no {vd:%b %d} close for {', '.join(missing)}; the vol curve interpolates across it")
        etf = ETF_FOR[source_key]
        try:
            eq = self._price(etf)
            r = spot / eq["price"]
            lo, hi = ETF_RATIO[source_key]
            if not lo <= r <= hi:
                raise ProviderUnavailable(f"price ratio {r:.2f} outside {lo:g}-{hi:g}")
            ec = self._contracts(etf, etf, 100, ivs, now, max_dte, include_0dte)
            contracts = contracts + merge_etf(contracts, ec, r, source_key, src.multiplier, etf_spot=eq["price"],
                                              asof=eq["time"], etf_q=dividend_yield(etf))
            warnings.append(f"includes {etf} options in {source_key} terms ({r:.2f} {etf} contracts = 1 {source_key} contract)")
        except ProviderError as e:
            warnings.append(f"occ: {etf} options not used ({e}); levels from {source_key} only")
        return ChainSnapshot(underlying=src.vendor_symbol, source_kind=src.kind, spot=spot,
                             spot_time=spot_q["time"], spot_quality=Quality.DELAYED,
                             contracts=contracts, source="occ+vix", fetched_at=now, warnings=warnings,
                             prev_close=spot_q["prev"], rate=risk_free_rate(), div_yield=dividend_yield(source_key),
                             vol_points=[(d, scale * v) for d, v in pts])


class FallbackProvider:
    """Cboe first; OCC only when Cboe refuses (401/403). Keeps Cboe's name and label (the worker's key and history
    folder stay the same); `last_label` names what the last result came from, so a backup result is saved and
    labelled as OCC, never as Cboe."""

    def __init__(self, primary, backup):
        self.primary, self.backup = primary, backup
        self.name, self.label = primary.name, primary.label
        self.include_etf = getattr(primary, "include_etf", False)
        self.last_label: Optional[str] = None
        self.refusal: Optional[str] = None          # Cboe's refusal while the backup is in use
        self.backup_ok: Optional[float] = None      # when the backup last gave a usable chain
        self.backup_error: Optional[str] = None
        self.primary_ok: Optional[float] = None     # when Cboe itself last answered
        self.refused_at = 0.0                       # when Cboe last answered with a refusal

    def fetch_snapshot(self, *a, **k) -> ChainSnapshot:
        now = time.time()
        ask = not (self.refusal and now - self.refused_at < RETRY_PRIMARY_S)   # refused recently: don't ask on every refresh
        try:
            if not ask:
                raise AuthError(self.refusal)
            snap = self.primary.fetch_snapshot(*a, **k)
        except AuthError as e:
            if ask:
                self.refused_at = now
            self.refusal = str(e)
            try:
                snap = self.backup.fetch_snapshot(*a, **k)
            except ProviderError as e2:
                self.backup_error, self.last_label = str(e2), None
                raise ProviderUnavailable(f"Cboe refused ({e}); the OCC backup failed too ({e2})") from e2
            self.last_label, self.backup_ok, self.backup_error = self.backup.label, time.time(), None
            return snap
        self.last_label, self.refusal, self.primary_ok = None, None, now
        return snap
