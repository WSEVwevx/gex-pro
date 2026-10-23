"""Databento adapter: true CME ES / NQ options on futures (dataset GLBX.MDP3).

Needs a Databento account with CME data (the Standard plan includes live and recent history) and
the key in DATABENTO_API_KEY. Uses Databento's documented HTTP API (no extra packages):
  POST https://hist.databento.com/v0/timeseries.get_range   (HTTP basic auth: key as user name)
  GET  https://hist.databento.com/v0/metadata.get_dataset_range

What is fetched, and how often (each piece is cached so a refresh stays small):
  definition  every option series on ES/NQ futures: quarterly, end-of-month, Friday weeklies and the
              Mon-Thu dailies. Each is its own CME product ("parent"), e.g. ES, EW, EW1-EW4, E1A-E5D;
              ES.OPT alone covers quarterlies only.                         cached per UTC day
  statistics  open interest (stat 9, published once a day by CME) and settlement prices (stat 3)
                                                                            cached 2 h
  bbo-1m      latest bid/ask per option and future, last few minutes        every refresh
  ohlcv-1h    today's traded volume per option, from the 18:00 ET session open   every refresh

Greeks: CME sends none, so IV comes from each option's own price with Black-76:
  live mid when the option has a fresh two-sided quote, otherwise the official settlement price
  against its future's settlement. Gamma is then computed by the engine at the live futures price.
Options on a different futures month than the chart's (e.g. ESZ6 options during the roll to ESH7)
are shifted by the calendar spread, so every level is in the chart contract's prices.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from .. import marketcal, pricing
from ..mapping import SOURCES
from ..models import ChainSnapshot, OptionContract, OptionType, Quality
from .base import AuthError, Provider, ProviderError, ProviderUnavailable, _backoff

log = logging.getLogger("gexsys.databento")
BASE = "https://hist.databento.com/v0"
DATASET = "GLBX.MDP3"
MAX_SYMBOLS = 2000                          # Databento's per-request symbol limit
I64_MAX, I32_MAX = 9223372036854775807, 2147483647
STAT_SETTLE, STAT_OI = 3, 9

# CME product codes for every option series on the E-mini futures (quarterly, end-of-month,
# Friday weeklies, and Monday-Thursday dailies: E{week}{A=Mon,B=Tue,C=Wed,D=Thu}).
PARENTS = {
    "ES": ["ES", "EW", "EW1", "EW2", "EW3", "EW4"] + [f"E{w}{d}" for w in range(1, 6) for d in "ABCD"],
    "NQ": ["NQ", "QNE", "QN1", "QN2", "QN3", "QN4"] + [f"Q{w}{d}" for w in range(1, 6) for d in "ABCD"],
}


def _num(x) -> Optional[float]:
    """CSV number -> float; blanks and Databento's 'not set' sentinels -> None."""
    if x is None or str(x).strip() == "":
        return None
    try:
        v = float(x)
    except ValueError:
        return None
    if not math.isfinite(v) or abs(v) >= I32_MAX:
        return None
    return v


def _price(x) -> Optional[float]:
    v = _num(x)
    if v is None and x not in (None, "") and str(x).lstrip("-").isdigit():    # raw fixed-point (1e-9)
        n = int(x)
        return None if abs(n) >= I64_MAX else n / 1e9
    return v


def _qty(x) -> Optional[float]:
    v = _num(x)
    return v if v is not None and v >= 0 else None


def _ts(x) -> Optional[datetime]:
    """ISO (pretty_ts) or nanoseconds since epoch -> aware datetime."""
    if x is None or str(x).strip() == "":
        return None
    s = str(x).strip()
    if s.isdigit():
        n = int(s)
        return None if n >= I64_MAX or n == 0 else datetime.fromtimestamp(n / 1e9, timezone.utc)
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$", s)
    if not m:
        return None
    frac = (m.group(2) or "")[:7]                                    # Python takes 6 digits
    tz = m.group(3) or "Z"
    return datetime.fromisoformat(m.group(1) + frac + ("+00:00" if tz == "Z" else tz))


def _chunks(xs: list, n: int = MAX_SYMBOLS):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def session_start(now: datetime) -> datetime:
    """Start of the current CME Globex session: 18:00 ET on the previous trading evening."""
    et = now.astimezone(marketcal.NY)
    d = et.date() if et.hour >= 18 else et.date() - timedelta(days=1)
    while d.weekday() in (4, 5):                                     # no session opens Fri/Sat evening
        d -= timedelta(days=1)
    return datetime.combine(d, datetime.min.time(), marketcal.NY).replace(hour=18)


class DatabentoProvider(Provider):
    name = "databento"
    label = "DATABENTO"

    def __init__(self, api_key: Optional[str] = None, parents: Optional[list] = None, strike_window: float = 0.08,
                 quote_window_min: float = 10.0, max_contracts: int = 8000,
                 post: Optional[Callable[[str, dict], str]] = None, get_json: Optional[Callable[[str], dict]] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc), rate: Optional[float] = None):
        self.api_key = api_key if api_key is not None else os.environ.get("DATABENTO_API_KEY", "")
        self.parents = parents
        self.strike_window, self.quote_window_min, self.max_contracts = strike_window, quote_window_min, max_contracts
        self._post, self._get = post or self._http_post, get_json or self._http_get
        self.clock = clock
        self.rate = rate if rate is not None else float(os.environ.get("GEX_RISK_FREE_RATE", "0.04"))
        self._defs: dict = {}       # (root, utc date) -> (options rows, futures rows, warnings)
        self._stats: dict = {}      # (root, utc date) -> (fetched monotonic, ids, oi, settle)
        self._bad_parents: set = set()

    # ---------------------------------------------------------------- HTTP
    def _auth(self) -> dict:
        if not self.api_key or "replace" in self.api_key.lower():
            raise AuthError("DATABENTO_API_KEY is not set - run DATABENTO_SETUP.bat")
        tok = base64.b64encode(f"{self.api_key}:".encode()).decode()
        return {"Authorization": f"Basic {tok}", "User-Agent": "gexsys", "Accept": "*/*"}

    def _request(self, req: urllib.request.Request) -> bytes:
        last: Exception = ProviderUnavailable("no attempt")
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                if e.code in (401, 403):
                    raise AuthError(f"Databento HTTP {e.code}: {detail}") from e
                if e.code == 429 or e.code >= 500:
                    last = ProviderUnavailable(f"Databento HTTP {e.code}: {detail}")
                else:
                    raise ProviderError(f"Databento HTTP {e.code}: {detail}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = ProviderUnavailable(f"Databento network error: {e}")
            time.sleep(_backoff(attempt, 1.0, 20.0))
        raise last

    def _http_post(self, url: str, data: dict) -> str:
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={**self._auth(), "Content-Type": "application/x-www-form-urlencoded"})
        return self._request(req).decode("utf-8")

    def _http_get(self, url: str) -> dict:
        return json.loads(self._request(urllib.request.Request(url, headers=self._auth())).decode("utf-8"))

    def _range(self, schema: str, symbols: list, stype_in: str, start: datetime, end: datetime) -> list[dict]:
        rows: list[dict] = []
        for part in _chunks([str(s) for s in symbols]):
            text = self._post(f"{BASE}/timeseries.get_range", {
                "dataset": DATASET, "schema": schema, "symbols": ",".join(part), "stype_in": stype_in,
                "start": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "end": end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "encoding": "csv", "compression": "none", "pretty_px": "true", "pretty_ts": "true",
                "map_symbols": "true"})
            rows.extend(csv.DictReader(io.StringIO(text)))
        return rows

    def available_end(self) -> datetime:
        d = self._get(f"{BASE}/metadata.get_dataset_range?dataset={DATASET}")
        end = _ts(d.get("end") or d.get("end_date"))
        if end is None:
            raise ProviderError(f"Databento dataset range has no end: {str(d)[:200]}")
        return end

    # ---------------------------------------------------------------- reference data
    def _definitions(self, root: str, end: datetime) -> tuple[list[dict], list[dict], list[str]]:
        key = (root, end.date())
        if key in self._defs:
            return self._defs[key]
        parents = [p for p in (self.parents or PARENTS[root]) if p not in self._bad_parents]
        symbols = [f"{p}.OPT" for p in parents] + [f"{root}.FUT"]
        start = end - timedelta(hours=26)
        try:
            rows = self._range("definition", symbols, "parent", start, end)
        except ProviderError as e:
            if isinstance(e, AuthError) or "symbol" not in str(e).lower():
                raise
            rows = []                                  # one bad product code fails the whole request:
            for s in symbols:                          # try each and remember the ones that don't exist
                try:
                    rows.extend(self._range("definition", [s], "parent", start, end))
                except ProviderError as e2:
                    if isinstance(e2, AuthError):
                        raise
                    self._bad_parents.add(s.split(".")[0])
        latest: dict[str, dict] = {}
        for r in rows:
            iid = r.get("instrument_id")
            if iid and (iid not in latest or (r.get("ts_recv") or "") >= (latest[iid].get("ts_recv") or "")):
                latest[iid] = r
        rx = re.compile(rf"^{root}[FGHJKMNQUVXZ]\d{{1,2}}$")
        opts, futs = [], []
        for r in latest.values():
            if (r.get("security_update_action") or "A").upper().startswith("D"):
                continue
            cls = (r.get("instrument_class") or "").upper()
            if cls in ("C", "P") and rx.match((r.get("underlying") or "").strip()):
                opts.append(r)
            elif cls == "F" and rx.match((r.get("raw_symbol") or "").strip()):
                futs.append(r)
        warns = []
        if self._bad_parents:
            warns.append(f"databento: option series not found and skipped: {', '.join(sorted(self._bad_parents))}")
        self._defs = {key: (opts, futs, warns)}        # keep only today's (ids can change between days)
        return self._defs[key]

    def _statistics(self, root: str, ids: list[str], end: datetime) -> tuple[dict, dict]:
        """Open interest and settlement per instrument_id; fetches only ids not already cached (2 h)."""
        key = (root, end.date())
        c = self._stats.get(key)
        if not c or time.monotonic() - c["t"] > 7200:
            c = {"t": time.monotonic(), "have": set(), "oi": {}, "settle": {}}
            self._stats = {key: c}
        missing = [i for i in dict.fromkeys(ids) if i not in c["have"]]
        if missing:
            self._parse_stats(self._range("statistics", missing, "instrument_id", end - timedelta(hours=30), end),
                              c["oi"], c["settle"])
            c["have"].update(missing)
        return c["oi"], c["settle"]

    @staticmethod
    def _parse_stats(rows: list[dict], oi: dict, settle: dict) -> None:
        rows.sort(key=lambda r: r.get("ts_recv") or "")
        for r in rows:
            st, iid = _num(r.get("stat_type")), r.get("instrument_id")
            ref = _ts(r.get("ts_ref")) or _ts(r.get("ts_event"))
            action = int(_num(r.get("update_action")) or 1)
            if st == STAT_OI:
                q = _qty(r.get("quantity"))
                if action == 2:                                       # deleted: drop that session's value
                    if iid in oi and oi[iid][0] == ref:
                        del oi[iid]
                elif q is not None and (iid not in oi or ref is None or oi[iid][0] is None or ref >= oi[iid][0]):
                    oi[iid] = (ref, q)
            elif st == STAT_SETTLE:
                p = _price(r.get("price"))
                if action == 2:
                    if iid in settle and settle[iid][0] == ref:
                        del settle[iid]
                elif p is not None and p > 0 and (iid not in settle or ref is None or settle[iid][0] is None
                                                  or ref >= settle[iid][0]):
                    settle[iid] = (ref, p)

    # ---------------------------------------------------------------- snapshot
    def fetch_snapshot(self, source_key: str, max_dte: float = 45, include_0dte: bool = True) -> ChainSnapshot:
        src = SOURCES[source_key]
        if src.kind.value != "FUT":
            raise ProviderError("the databento provider is for CME futures options: use source NQ_FOP or ES_FOP")
        root = src.vendor_symbol
        now = self.clock()
        end = min(now, self.available_end())
        warnings: list[str] = []
        if (now - end).total_seconds() > 1800:
            warnings.append(f"databento: newest available data is from {end:%Y-%m-%d %H:%M} UTC "
                            "(intraday data may not be included in your plan)")

        opts, futs, w = self._definitions(root, end)
        warnings += w
        if not opts:
            raise ProviderError(f"databento: no {root} option definitions found")
        front = marketcal.front_contract(root, end.astimezone(marketcal.NY).date())
        fut_by_sym = {f["raw_symbol"].strip(): f for f in futs}
        if front not in fut_by_sym:
            raise ProviderError(f"databento: front future {front} not in definitions")

        # live quotes for the futures the options settle into
        und_syms = sorted({o["underlying"].strip() for o in opts} & set(fut_by_sym))
        fut_ids = [fut_by_sym[s]["instrument_id"] for s in und_syms]
        qstart = end - timedelta(minutes=self.quote_window_min)
        fq = self._quotes(fut_ids, qstart, end)
        _, fsettle = self._statistics(root, fut_ids, end)
        fut_px: dict[str, tuple] = {}
        for s in und_syms:
            iid = fut_by_sym[s]["instrument_id"]
            if iid in fq:
                fut_px[s] = (fq[iid][0], fq[iid][1])
            elif iid in fsettle:
                fut_px[s] = (fsettle[iid][1], fsettle[iid][0])
        if front not in fut_px:
            raise ProviderError(f"databento: no price for {front}")
        spot, spot_time = fut_px[front]

        # candidate options: listed, not expired, inside the DTE and strike windows
        cands = []
        for o in opts:
            u = o["underlying"].strip()
            exp, k = _ts(o.get("expiration")), _price(o.get("strike_price"))
            if u not in fut_px or exp is None or k is None or k <= 0 or exp <= end:
                continue
            if (exp - end).total_seconds() / 86400 > max_dte:
                continue
            if exp.astimezone(marketcal.NY).date() == end.astimezone(marketcal.NY).date() and not include_0dte:
                continue
            if abs(k / fut_px[u][0] - 1) > self.strike_window:
                continue
            cands.append((abs(k / fut_px[u][0] - 1), o))
        cands.sort(key=lambda x: x[0])
        if len(cands) > self.max_contracts:
            warnings.append(f"databento: kept the {self.max_contracts} strikes nearest the money of {len(cands)}")
            cands = cands[:self.max_contracts]
        cands = [o for _, o in cands]

        ids = [o["instrument_id"] for o in cands] + fut_ids
        oi, settle = self._statistics(root, ids, end)
        live = [o["instrument_id"] for o in cands if o["instrument_id"] in oi and oi[o["instrument_id"]][1] > 0]
        quotes = self._quotes(live, qstart, end)
        volume = self._volume(live, session_start(end), end)

        contracts, n_live, n_settle = [], 0, 0
        for o in cands:
            iid = o["instrument_id"]
            if iid not in oi:
                continue
            u = o["underlying"].strip()
            f_own, _ = fut_px[u]
            exp, k = _ts(o["expiration"]), _price(o["strike_price"])
            is_call = o["instrument_class"].upper() == "C"
            t_now = max((exp - end).total_seconds(), 60) / (365.0 * 86400)
            bid = ask = qt = None
            iv = None
            if iid in quotes:
                mid, qt, bid, ask = quotes[iid]
                if mid and ask - bid <= max(0.25 * mid, 2.0):
                    iv = pricing.implied_vol(mid, f_own, k, t_now, self.rate, self.rate, is_call)
            if iv is not None:
                n_live += 1
            elif iid in settle:
                fs = fsettle_for(u, fut_by_sym, fsettle)
                ref, px = settle[iid]
                if fs and ref:
                    t_set = max((exp - ref).total_seconds(), 3600) / (365.0 * 86400)
                    iv = pricing.implied_vol(px, fs, k, t_set, self.rate, self.rate, is_call)
                    n_settle += 1 if iv else 0
            shift = spot - f_own                       # calendar spread into the chart contract's prices
            asset = (o.get("asset") or root).strip()
            contracts.append(OptionContract(
                symbol=o.get("raw_symbol", "").strip(), root=asset, underlying=u,
                option_type=OptionType.CALL if is_call else OptionType.PUT, strike=k + shift, expiration=exp,
                multiplier=float(src.multiplier), open_interest=oi[iid][1], volume=volume.get(iid, 0.0),
                bid=bid, ask=ask, last_time=qt, iv=iv, gamma=None,
                quote_quality=self._q(qt, now) if qt else Quality.MISSING, oi_quality=Quality.EOD,
                greeks_quality=Quality.MISSING, exercise_style="american" if asset == root else "european"))
        shifted = sorted({c.underlying for c in contracts if c.underlying != front})
        if shifted:
            warnings.append(f"databento: options on {', '.join(shifted)} shifted by the calendar spread to {front} prices")
        warnings.append(f"databento: IV from live quotes for {n_live} options, from settlement for {n_settle}; "
                        f"open interest is CME's end-of-day figure")
        prev = fsettle.get(fut_by_sym[front]["instrument_id"])
        return ChainSnapshot(underlying=front, source_kind=src.kind, spot=spot, spot_time=spot_time,
                             spot_quality=self._q(spot_time, now), contracts=contracts, source="databento",
                             fetched_at=now, rate=self.rate, div_yield=0.0, warnings=warnings,
                             prev_close=prev[1] if prev else None)

    @staticmethod
    def _q(t: Optional[datetime], ref: datetime) -> Quality:
        return Quality.REALTIME if t and (ref - t).total_seconds() <= 180 else Quality.DELAYED

    def _quotes(self, ids: list[str], start: datetime, end: datetime) -> dict:
        """instrument_id -> (mid, time, bid, ask) from the newest two-sided 1-minute BBO."""
        out: dict = {}
        if not ids:
            return out
        for r in self._range("bbo-1m", ids, "instrument_id", start, end):
            b, a, t = _price(r.get("bid_px_00")), _price(r.get("ask_px_00")), _ts(r.get("ts_recv") or r.get("ts_event"))
            if b is None or a is None or b <= 0 or a < b or t is None:
                continue
            iid = r.get("instrument_id")
            if iid not in out or t >= out[iid][1]:
                out[iid] = (0.5 * (a + b), t, b, a)
        return out

    def _volume(self, ids: list[str], start: datetime, end: datetime) -> dict:
        out: dict = {}
        if not ids or end <= start:
            return out
        for r in self._range("ohlcv-1h", ids, "instrument_id", start, end):
            v = _qty(r.get("volume"))
            if v:
                out[r.get("instrument_id")] = out.get(r.get("instrument_id"), 0.0) + v
        return out


def fsettle_for(sym: str, fut_by_sym: dict, fsettle: dict) -> Optional[float]:
    f = fut_by_sym.get(sym)
    s = fsettle.get(f["instrument_id"]) if f else None
    return s[1] if s else None
