"""The options chain: OCC open interest + one implied vol per expiry from the VIX-family daily closes + Yahoo prices.

Sources (all free, no key; proven from GitHub's servers by tools/probe_sources.py):
  OCC   GET https://marketdata.theocc.com/series-search?symbolType=U&symbol={NDX|SPX|QQQ|SPY}
        tab-separated: product, -, year, month, day, strike integer, strike decimals (thousandths), "C P",
        call OI, put OI, position limit. End-of-day open interest across all exchanges; the file carries no date.
  Vols  GET https://query1.finance.yahoo.com/v8/finance/chart/{^VIX1D|^VIX9D|^VIX|^VIX3M|^VXN}?range=1mo&interval=1d
        daily bars; each bar is dated in the exchange's own time zone (meta.exchangeTimezoneName: ^VIX is dated in
        Chicago, the others in New York). Close in percent; a bar with no close (not final yet) is skipped.
  Price GET https://query1.finance.yahoo.com/v8/finance/chart/{^NDX|^GSPC|QQQ|SPY}?range=1d&interval=1d (chart meta)

The vol date is the last completed cash session by gexsys/marketcal.py (a close counts 30 minutes after the bell,
once the VIX family has printed its final value), never the newest row of a file: a holiday row (^VIX carries one
for Thanksgiving) or a partial bar for today is ignored. A series with no close that day uses its close of the
trading day before, named in a warning; older closes are not used.

Implied vol (no per-strike quotes, so no skew):
  SPX: total variance w(d) = (VIX_d / 100)^2 x d at d = 1, 9, 30, 93 days (VIX1D, VIX9D, VIX, VIX3M), linear in w
       between points; flat beyond the ends. iv(T) = sqrt(w(T) / T).
  NDX: the SPX curve x VXN / iv_SPX(30 days) (VXN is the 30-day NDX index; there is no shorter one).
  ETF options (QQQ, SPY) take their index's vol.
Each contract gets that vol; the engine computes gamma from it.

With a London Strategic Edge key, on this PC only (never on GitHub, in the hosted build or the archive), each contract
instead gets the previous session's smile (gexsys/smile.py: per-contract IVs from LSE, fitted in time-scaled
moneyness): source "occ+lse", provider "OCCLSE" (its own snapshot folder). Roots: NDX + NDXP, SPX + SPXW, and QQQ /
SPY for the merged ETF options. When LSE has no usable session (refused, not landed for two sessions, too few
points) the VIX-family curve is used, and the snapshot's warnings say why. Gamma per strike is therefore an estimate: the
2026-11-19 comparison with a full per-strike chain (all-expiry walls and zero gamma within 0.06 expected moves; ranks
2-3, Ab1 and the 0DTE flip far off) is why the pipeline keeps only the first-ranked near-dated levels from this source.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from .. import marketcal
from .. import smile as SM
from ..mapping import SOURCES
from ..models import ChainSnapshot, OptionContract, OptionType, Quality
from .base import AuthError, ProviderError, ProviderUnavailable
from .common import ETF_FOR, ETF_RATIO, STANDARD_ROOTS, dividend_yield, merge_etf, risk_free_rate

OCC_URL = "https://marketdata.theocc.com/series-search?symbolType=U&symbol={sym}"
VOL_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1mo&interval=1d"
VOL_SYM = {"VIX1D": "^VIX1D", "VIX9D": "^VIX9D", "VIX": "^VIX", "VIX3M": "^VIX3M", "VXN": "^VXN"}
PRICE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=1d"
YAHOO_SYM = {"NDX": "^NDX", "SPX": "^GSPC", "QQQ": "QQQ", "SPY": "SPY"}
UA = {"User-Agent": "Mozilla/5.0 (GEX PRO)"}
CURVE = (("VIX1D", 1), ("VIX9D", 9), ("VIX", 30), ("VIX3M", 93))
SMILE_ROOTS = {"NDX": ("NDX", "NDXP"), "SPX": ("SPX", "SPXW"), "QQQ": ("QQQ",), "SPY": ("SPY",)}
STRIKE_BAND = 0.25          # LSE rows asked for: strikes within 25% of the price (the 45-day chain lives inside it)
CACHE_S = 3600          # open interest and the vol closes change once a day: fetch each at most hourly
VOL_SETTLE = timedelta(minutes=30)   # the VIX family prints its final value 15 min after the cash close


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


def daily_closes(text: str) -> dict[date, float]:
    """{bar date: close as a decimal} from Yahoo's daily chart JSON, dated in the exchange's time zone. Bars with no
    usable close are left out; an unreadable answer gives {} (the series then counts as missing)."""
    try:
        r = json.loads(text)["chart"]["result"][0]
        tz = ZoneInfo(r["meta"].get("exchangeTimezoneName") or "America/New_York")
        stamps, closes = r.get("timestamp") or [], r["indicators"]["quote"][0].get("close") or []
    except (ValueError, KeyError, IndexError, TypeError, LookupError):
        return {}
    out = {}
    for t, c in zip(stamps, closes):
        if isinstance(t, (int, float)) and isinstance(c, (int, float)) and math.isfinite(c) and c > 0:
            # published to two decimals; Yahoo carries them as float32 (28.290000915527344): 4 places undo that
            out[datetime.fromtimestamp(t, tz).date()] = round(c, 4) / 100.0
    return out


def vol_date(now: datetime) -> date:
    """The session whose VIX-family closes the curve uses: the last completed cash session (marketcal)."""
    return marketcal.last_close(now - VOL_SETTLE).astimezone(marketcal.NY).date()


def pick_close(history: dict[date, float], vd: date) -> Optional[tuple[date, float]]:
    """The close on vd, else on the trading day before it; nothing older (a week-old vol is not today's)."""
    for d in (vd, marketcal.previous_trading_day(vd)):
        if d in history:
            return d, history[d]
    return None


def vol_curve(closes: dict[str, tuple[date, float]]) -> list[tuple[float, float]]:
    """[(days, vol)] from the curve indices that have a close."""
    pts = [(float(days), closes[n][1]) for n, days in CURVE if n in closes]
    if not pts:
        raise ProviderUnavailable("no VIX-family close available")
    return pts


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


def vxn_scale(closes: dict[str, tuple[date, float]], hist: dict[str, dict[date, float]],
              pts: list[tuple[float, float]], vd: date) -> tuple[float, date]:
    """NDX vol / S&P vol, both from one session: VXN / VIX on vd, else on the session before; with no VIX on either,
    VXN over the curve at 30 days when every curve close is from VXN's session. A VXN from one session over a VIX from
    another would scale every NDX vol by the two days' difference (verifier, 2026-11-28: +19% on the early close of
    Nov 27), so that is refused. Returns (scale, the session it is from)."""
    vxn, vix = hist.get("VXN", {}), hist.get("VIX", {})
    for d in (vd, marketcal.previous_trading_day(vd)):
        if d in vxn and d in vix:
            return vxn[d] / vix[d], d
    d = closes["VXN"][0]
    if "VIX" not in closes and all(c[0] == d for n, c in closes.items()):
        return closes["VXN"][1] / curve_iv(pts, 30), d
    raise ProviderUnavailable(f"no VXN and VIX close from one session ({vd:%b %d} or the one before) to scale the vol curve to NDX")


class OccProvider:
    name = "occ"
    label = "OCC"

    def __init__(self, cache_dir: Optional[str] = None, opener: Callable = urllib.request.urlopen,
                 clock: Callable[[], float] = time.time, lse=None):
        self.cache = Path(cache_dir) if cache_dir else None
        self.opener, self.clock = opener, clock
        self.vol_date: Optional[date] = None
        self.lse = lse                      # gexsys.providers.lse.LseClient, local only (gexsys/config.py decides)
        if lse is not None:
            self.label = "OCCLSE"           # its own snapshot folder: studies and grades always tell the two apart
        self.smile_info: dict = {}

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

    def _contracts(self, sym: str, key: str, mult: float, ivs: Callable[[datetime, float], Optional[float]], now: datetime,
                   max_dte: float, include_0dte: bool) -> list[OptionContract]:
        roots = STANDARD_ROOTS.get(sym)
        today = now.astimezone(marketcal.NY).date()
        out = []
        text = self._get(OCC_URL.format(sym=sym), f"occ_{sym}")
        # a whole answer starts with OCC's title and ends with a line break: a cut-off download (feed fuzz E1, 2026-11-28)
        # moved zero gamma and the walls without a word, so it is refused instead
        if not text.lstrip().startswith(f"Series Search Results for {sym}") or not text.endswith("\n"):
            raise ProviderUnavailable(f"the OCC {sym} file is incomplete or not a series list")
        for prod, ed, k, c_oi, p_oi in parse_series(text):
            if roots and prod not in roots:
                continue
            dte = (ed - today).days
            if dte < 0 or dte > max_dte or (dte == 0 and not include_0dte):
                continue
            exp = marketcal.option_expiry_time(ed, prod)
            if exp <= now:
                continue
            iv = ivs(exp, k)
            for typ, oi in ((OptionType.CALL, c_oi), (OptionType.PUT, p_oi)):
                if oi == 0:
                    continue            # negative or NaN open interest goes on to normalize, which counts and flags it
                out.append(OptionContract(
                    symbol=f"{prod}{ed:%y%m%d}{typ.value}{int(round(k * 1000)):08d}", root=prod, underlying=key,
                    option_type=typ, strike=k, expiration=exp, multiplier=mult, open_interest=oi, iv=iv,
                    quote_quality=Quality.MISSING, oi_quality=Quality.EOD, greeks_quality=Quality.MISSING,
                    exercise_style="european" if sym in ("NDX", "SPX") else "american"))
        return out

    def _curve_on(self, source_key: str, hist: dict, d: date) -> Optional[Callable[[float], float]]:
        """Session d's index vol curve (IV at T years) as fetch_snapshot builds it; None when a close is missing."""
        closes = {}
        for n, h in hist.items():
            got = pick_close(h, d)
            if got and got[0] == d:
                closes[n] = got
        if not any(n in closes for n, _ in CURVE) or (source_key == "NDX" and "VXN" not in closes):
            return None
        pts = vol_curve(closes)
        scale = vxn_scale(closes, hist, pts, d)[0] if source_key == "NDX" else 1.0
        return lambda t: scale * curve_iv(pts, t * 365.0)

    def _lse_rows(self, root: str, vd: date, prev: date, s0: float, max_dte: float) -> tuple[Optional[date], list]:
        """(the session, its rows) for one root: the vol date's Greeks if landed, else the session before's from disk."""
        filters = dict(min_dte=1, max_dte=int(max_dte) + 1, strike_min=int(s0 * (1 - STRIKE_BAND)),
                       strike_max=int(s0 * (1 + STRIKE_BAND)) + 1)
        rec = self.lse.session_chain(root, vd, **filters)
        if rec:
            return vd, rec.get("rows") or []
        rec = self.lse.cached(root, prev)
        if rec and rec.get("landed"):
            return prev, rec.get("rows") or []
        return None, []

    def _smiles(self, source_key: str, etf: str, spot: float, now: datetime, vd: date, curve: Callable,
                hist: dict, max_dte: float) -> tuple[dict, list]:
        """({underlying: smile.Surface}, warnings). Empty (the VIX-family curve is used) when LSE has nothing usable."""
        self.smile_info = {}
        prev = marketcal.previous_trading_day(vd)
        try:
            eq_px = self._price(etf)["price"]
        except ProviderError:
            eq_px = None
        out, why, used, stats = {}, [], {}, []
        for und, s0 in ((source_key, spot), (etf, eq_px)):
            if s0 is None:
                continue
            got = {}
            try:
                for root in SMILE_ROOTS[und]:
                    got[root] = self._lse_rows(root, vd, prev, s0, max_dte)
            except ProviderError as e:
                why.append(f"{und}: {e}")
                continue
            sessions = {p for p, _ in got.values() if p}
            if not sessions:
                why.append(f"{und}: no LSE Greeks for {vd:%b %d} or {prev:%b %d} yet")
                continue
            p = max(sessions)                                   # one session per underlying: one level, one anchor
            missing = [root for root, (pp, _) in got.items() if pp != p]
            o, c = marketcal.rth_open_dt(p), marketcal.rth_close_dt(p)
            r, q = risk_free_rate(), dividend_yield(und)
            groups: dict = {}
            for root, (pp, rows) in got.items():
                if pp != p:
                    continue
                for row in rows:
                    try:
                        exp = marketcal.option_expiry_time(date.fromisoformat(str(row.get("expiry"))[:10]), root)
                    except ValueError:
                        continue
                    groups.setdefault(exp, []).append(row)
            fits, thin = {}, 0
            for exp, rows in groups.items():
                f, _ = SM.fit(exp, SM.points(rows, exp, o, c, r, q), curve(exp))
                if f:
                    fits[exp] = f
                else:
                    thin += 1
            if not fits:
                why.append(f"{und}: no expiry of {p:%b %d} had enough traded strikes for a smile")
                continue
            anchor = (lambda t: 1.0)
            if p != vd:
                old, new = self._curve_on(source_key, hist, p), self._curve_on(source_key, hist, vd)
                if not (old and new):
                    why.append(f"{und}: the {p:%b %d} smile could not be moved to the {vd:%b %d} vol level "
                               f"(a VIX-family close is missing)")
                    continue
                anchor = (lambda t, old=old, new=new: new(t) / old(t))
            out[und] = SM.Surface(fits, r, q, anchor)
            used[und] = p
            rms = sorted(f.rms for f in fits.values())
            stats.append(f"{und} {len(fits)} of {len(groups)} expiries fitted (median miss {rms[len(rms) // 2]:.2f} vol pts)"
                         + (f", {thin} interpolated" if thin else "") + (f"; {', '.join(missing)} not landed" if missing else ""))
            self.smile_info.setdefault("fits", {})[und] = [f.info() for f in sorted(fits.values(), key=lambda f: f.expiry)]
        warns = []
        if source_key in out:
            p = used[source_key]
            from .lse import CREDIT
            self.smile_info.update(session=p.isoformat(), credit=CREDIT)
            warns.append(f"smile: {CREDIT}, implied vols of the {p:%b %d} session: " + "; ".join(stats)
                         + "; 0DTE left out (no validated one-day smile)")
            if p != vd:
                warns.append(f"smile: LSE's Greeks for {vd:%b %d} have not landed; the {p:%b %d} smile is moved to the "
                             f"{vd:%b %d} vol level by the VIX-family curve")
        if why:
            warns.append(("smile: " if source_key in out else "smile unavailable, the VIX-family curve is used: ") + "; ".join(why))
        return out, warns

    def fetch_snapshot(self, source_key: str, max_dte: float = 45, include_0dte: bool = True) -> ChainSnapshot:
        if source_key not in ("NDX", "SPX"):
            raise ProviderError(f"the OCC chain covers NDX and SPX, not {source_key}")
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        vd = vol_date(now)
        closes, hist = {}, {}
        for n in [c for c, _ in CURVE] + (["VXN"] if source_key == "NDX" else []):
            hist[n] = daily_closes(self._get(VOL_URL.format(sym=urllib.parse.quote(VOL_SYM[n])), f"yvol_{n}"))
            got = pick_close(hist[n], vd)
            if got:
                closes[n] = got
        if not any(n in closes for n, _ in CURVE):
            raise ProviderUnavailable(f"no VIX-family close for {vd:%b %d} or the session before")
        pts = vol_curve(closes)
        scale, late_scale = 1.0, None
        if source_key == "NDX":
            if "VXN" not in closes:
                raise ProviderUnavailable(f"no VXN close for {vd:%b %d} or the session before to scale the vol curve to NDX")
            scale, sd = vxn_scale(closes, hist, pts, vd)
            if sd != vd:
                late_scale = f"occ: the NDX scale is VXN / VIX of {sd:%b %d}, the last session with both"
        self.vol_date, self._hist = vd, hist
        curve = lambda exp: scale * curve_iv(pts, (exp - now).total_seconds() / 86400)
        ivs = lambda exp, k: curve(exp)
        src = SOURCES[source_key]
        spot_q = self._price(source_key)
        spot = spot_q["price"]
        etf = ETF_FOR[source_key]
        sm, sm_warn = self._smiles(source_key, etf, spot, now, vd, curve, hist, max_dte) if self.lse is not None else ({}, [])
        today = now.astimezone(marketcal.NY).date()
        if source_key in sm:
            # 0DTE: no IV, so the engine leaves it out (one-day vol is not yesterday's two-day vol; gexsys/smile.py)
            ivs = lambda exp, k: None if exp.astimezone(marketcal.NY).date() == today else sm[source_key].iv(exp, k, spot, now)
        contracts = self._contracts(source_key, source_key, src.multiplier, ivs, now, max_dte, include_0dte)
        if not contracts:
            raise ProviderUnavailable(f"OCC returned no usable {source_key} series within {max_dte} days")
        warnings = ([f"estimate: OCC open interest (end of day) with each strike's implied vol from the "
                     f"{self.smile_info.get('session', '')} session's smile"] if source_key in sm else
                    [f"estimate: OCC open interest (end of day) with one implied vol per expiry "
                     f"from the {vd:%b %d} VIX-family closes{' scaled by VXN' if source_key == 'NDX' else ''} (no skew)"]) + sm_warn
        late = [f"{n} ({d:%b %d})" for n, (d, _) in closes.items() if d != vd]
        if late:
            warnings.append(f"occ: no {vd:%b %d} close yet for {', '.join(late)}: the session before is used")
        if late_scale:
            warnings.append(late_scale)
        missing = [n for n, _ in CURVE if n not in closes]
        if missing:
            warnings.append(f"occ: no {vd:%b %d} close for {', '.join(missing)}; the vol curve interpolates across it")
        try:
            eq = self._price(etf)
            r = spot / eq["price"]
            lo, hi = ETF_RATIO[source_key]
            if not lo <= r <= hi:
                raise ProviderUnavailable(f"price ratio {r:.2f} outside {lo:g}-{hi:g}")
            eivs = ivs
            if source_key in sm:
                es = sm.get(etf, sm[source_key])             # QQQ / SPY's own smile, else the index's at the same x
                eivs = lambda exp, k: None if exp.astimezone(marketcal.NY).date() == today else es.iv(exp, k, eq["price"], now)
            ec = self._contracts(etf, etf, 100, eivs, now, max_dte, include_0dte)
            contracts = contracts + merge_etf(contracts, ec, r, source_key, src.multiplier, etf_spot=eq["price"],
                                              asof=eq["time"], etf_q=dividend_yield(etf))
            warnings.append(f"includes {etf} options in {source_key} terms ({r:.2f} {etf} contracts = 1 {source_key} contract)")
        except ProviderError as e:
            warnings.append(f"occ: {etf} options not used ({e}); levels from {source_key} only")
        return ChainSnapshot(underlying=src.vendor_symbol, source_kind=src.kind, spot=spot,
                             spot_time=spot_q["time"], spot_quality=Quality.DELAYED,
                             contracts=contracts, source="occ+lse" if source_key in sm else "occ+vix", fetched_at=now,
                             warnings=warnings,
                             prev_close=spot_q["prev"], rate=risk_free_rate(), div_yield=dividend_yield(source_key),
                             vol_points=[(d, scale * v) for d, v in pts])
