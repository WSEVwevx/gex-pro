"""London Strategic Edge (LSE Data) client: local only, keyed, rate-limited, cached on disk.

Host https://download.londonstrategicedge.com, the key in the X-API-Key header (docs: londonstrategicedge.com/docs).
Endpoints used:
  /v3/options/chain?underlying=&type=&expiry=&strike=&strike_min=&strike_max=&min_dte=&max_dte=&limit=&offset=
      -> {underlying, underlying_price, underlying_at, contracts, returned, limit, offset, greeks_as_of, rows: [...]}
      rows: ticker, symbol, pair_id, underlying, contract_type, strike, expiry, dte, last_price, last_trade_at,
      volume_today, premium_today, iv, delta, gamma, theta, vega, greeks_underlying_price, greeks_at.
      limit 1-5000 (1000 when not given). No open interest. The Greeks are computed after each session from each
      contract's last trade (greeks_at) at the underlying price of that moment (greeks_underlying_price).
  /v3/preview?market=&symbol=&data=&timeframe=  the newest ten rows, not charged as rows: {columns, rows, ...}
  /v3/export   the same parameters with from= and to=; rows charged and capped (export(), never called by the app)
  /v3/usage    the plan, the markets the key opens, what it has used

Rules (rework workstream 3, CLAUDE.md "LSE data local only"):
  - the key comes only from %USERPROFILE%/.lse_key or $LSE_KEY; it is never printed, logged, put in a URL, saved
    or carried by an exception (every error names the HTTP status and LSE's error code only)
  - the client refuses to run on GitHub's servers (GITHUB_ACTIONS) and inside the hosted build or the archive writer
    (GEX_NO_LSE, set by gexpro build-site / archive): LSE values never reach the public site, the archive or the repo
  - a limiter is always on: at most `per_minute` calls a minute and `per_day` a day (counted on disk), plus an
    optional per-process `budget`
  - 429 -> wait the seconds LSE names (Retry-After, at most 60 s), once; 401/403 -> "unavailable: key refused",
    never retried; 5xx and network errors -> 2 retries, then unavailable
  - session chains are cached on disk (%LOCALAPPDATA%/gexsys/lse, never in git) and fetched until that session's
    Greeks land, then never again; the first time a session's Greeks are seen is logged (their landing time)
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .. import marketcal
from .base import AuthError, ProviderError, ProviderUnavailable, RateLimitError

log = logging.getLogger(__name__)
HOST = "https://download.londonstrategicedge.com"
CREDIT = "Data: London Strategic Edge"
PAGE = 5000
MAX_RETRY_AFTER = 60.0
REFETCH_S = 15 * 60          # a session whose Greeks have not landed is asked again at most every 15 minutes


class LocalOnly(ProviderError):
    """LSE data may not be fetched here (GitHub's servers, the hosted build, the archive writer)."""


class KeyMissing(AuthError):
    pass


def read_key() -> Optional[str]:
    """The key from $LSE_KEY, else %USERPROFILE%/.lse_key (first line), else None. Never logged."""
    k = os.environ.get("LSE_KEY", "").strip()
    if k:
        return k
    try:
        k = (Path.home() / ".lse_key").read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return k or None


def why_not_here() -> Optional[str]:
    if os.environ.get("GITHUB_ACTIONS"):
        return "LSE data is local only: not on GitHub's servers"
    if os.environ.get("GEX_NO_LSE"):
        return "LSE data is local only: not in the hosted build or the archive"
    return None


def default_cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "gexsys" / "lse"


def session_of(stamp: Optional[str]) -> Optional[date]:
    """The New York session date of an LSE time ('2026-11-25 20:58:19.448381162', UTC)."""
    if not stamp:
        return None
    try:
        t = datetime.fromisoformat(str(stamp)[:26].replace(" ", "T")).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return t.astimezone(marketcal.NY).date()


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


class Limiter:
    """At most per_minute calls in any 60 s and per_day calls a UTC day (the day count lives on disk, so restarts
    share it), and at most `budget` calls for this process when given. Over a limit: LimitReached, never a wait."""

    def __init__(self, per_minute: int = 30, per_day: int = 2000, budget: Optional[int] = None,
                 folder: Optional[Path] = None, clock: Callable[[], float] = time.time):
        self.per_minute, self.per_day, self.budget = per_minute, per_day, budget
        self.folder, self.clock = folder, clock
        self.recent: deque = deque()
        self.used = 0
        self._mem_day = 0                       # the day count without a folder (tests)

    def _day_file(self) -> Optional[Path]:
        d = datetime.fromtimestamp(self.clock(), timezone.utc).date()
        return self.folder / f"calls-{d.isoformat()}.json" if self.folder else None

    def today(self) -> int:
        f = self._day_file()
        try:
            return int(json.loads(f.read_text(encoding="utf-8"))["calls"]) if f else self._mem_day
        except (OSError, ValueError, KeyError, TypeError):
            return 0

    def take(self) -> None:
        now = self.clock()
        while self.recent and now - self.recent[0] >= 60:
            self.recent.popleft()
        if self.budget is not None and self.used >= self.budget:
            raise RateLimitError(f"unavailable: the LSE call budget of {self.budget} for this run is used up")
        if len(self.recent) >= self.per_minute:
            raise RateLimitError(f"unavailable: {self.per_minute} LSE calls in the last minute (the limit)",
                                 retry_after=60 - (now - self.recent[0]))
        n = self.today()
        if n >= self.per_day:
            raise RateLimitError(f"unavailable: {self.per_day} LSE calls today (the daily limit)")
        self.recent.append(now)
        self.used += 1
        f = self._day_file()
        if f:
            _atomic_write(f, {"calls": n + 1})
        else:
            self._mem_day = n + 1


class LseClient:
    def __init__(self, key: Optional[str] = None, opener: Callable = urllib.request.urlopen,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
                 cache_dir: Optional[str] = "default", per_minute: int = 30, per_day: int = 2000,
                 budget: Optional[int] = None, timeout: float = 30.0):
        self._key = key if key is not None else read_key()
        self.opener, self.clock, self.sleep, self.timeout = opener, clock, sleep, timeout
        self.cache = default_cache_dir() if cache_dir == "default" else Path(cache_dir) if cache_dir else None
        self.limiter = Limiter(per_minute, per_day, budget, self.cache, clock)
        self.last_error: Optional[str] = None
        self.last_ok: Optional[float] = None

    def __repr__(self) -> str:                      # never the key
        return f"LseClient(cache={self.cache}, key={'set' if self._key else 'missing'})"

    # ---------------------------------------------------------------- HTTP
    def _redact(self, text: str) -> str:
        return text.replace(self._key, "[key]") if self._key else text

    def _fail(self, exc: ProviderError) -> ProviderError:
        self.last_error = self._redact(str(exc))
        exc.args = (self.last_error,)
        return exc

    def get(self, path: str, **params) -> dict:
        """GET HOST+path?params as JSON. Errors carry the status and LSE's error code, never the key or headers."""
        why = why_not_here()
        if why:
            raise self._fail(LocalOnly(why))
        if not self._key:
            raise self._fail(KeyMissing("unavailable: no LSE key (set LSE_KEY or write it to %USERPROFILE%\\.lse_key)"))
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{HOST}{path}" + (f"?{q}" if q else "")
        waited = False
        for attempt in range(3):
            self.limiter.take()
            req = urllib.request.Request(url, headers={"X-API-Key": self._key, "Accept": "application/json",
                                                       "User-Agent": "GEX PRO (local)"})
            err: Optional[ProviderError] = None
            try:
                with self.opener(req, timeout=self.timeout) as r:
                    body = r.read()
                data = json.loads(body.decode("utf-8")) if body else {}
                self.last_ok, self.last_error = self.clock(), None
                return data
            except urllib.error.HTTPError as e:
                code = self._code(e)
                if e.code in (401, 403):
                    raise self._fail(AuthError(f"unavailable: key refused (HTTP {e.code}{code})")) from None
                if e.code == 429:
                    wait = self._retry_after(e)
                    if not waited and wait is not None and wait <= MAX_RETRY_AFTER:
                        waited = True
                        log.warning("LSE %s: 429, waiting %.0f s as asked", path, wait)
                        self.sleep(wait)
                        continue
                    raise self._fail(RateLimitError(f"unavailable: LSE rate limit (HTTP 429{code})", retry_after=wait)) from None
                if 400 <= e.code < 500:
                    raise self._fail(ProviderError(f"LSE refused the request (HTTP {e.code}{code})")) from None
                err = ProviderUnavailable(f"unavailable: LSE server error (HTTP {e.code}{code})")
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                err = ProviderUnavailable(f"unavailable: LSE did not answer ({type(e).__name__})")
            except ValueError:
                err = ProviderUnavailable("unavailable: LSE answered something that is not JSON")
            if attempt < 2:
                self.sleep(2.0 * (attempt + 1))
        raise self._fail(err) from None

    @staticmethod
    def _code(e: urllib.error.HTTPError) -> str:
        """LSE's own error code from the body (e.g. options-timeout), as ', <code>'; nothing else of the body."""
        try:
            d = json.loads(e.read().decode("utf-8"))
        except Exception:
            return ""
        c = d.get("code") or d.get("error") if isinstance(d, dict) else None
        return f", {c}" if isinstance(c, str) and len(c) <= 60 and c.replace("-", "").replace("_", "").isalnum() else ""

    @staticmethod
    def _retry_after(e: urllib.error.HTTPError) -> Optional[float]:
        try:
            v = (e.headers or {}).get("Retry-After")
            return max(0.0, float(v)) if v is not None else None
        except (TypeError, ValueError):
            return None

    # ---------------------------------------------------------------- endpoints
    def chain(self, root: str, *, type: Optional[str] = None, expiry: Optional[str] = None,
              strike_min: Optional[float] = None, strike_max: Optional[float] = None,
              min_dte: Optional[int] = None, max_dte: Optional[int] = None) -> dict:
        """Every page of one root's chain: {underlying, greeks_as_of, contracts, rows}."""
        rows, offset, head = [], 0, {}
        while True:
            d = self.get("/v3/options/chain", underlying=root, type=type, expiry=expiry, strike_min=strike_min,
                         strike_max=strike_max, min_dte=min_dte, max_dte=max_dte, limit=PAGE, offset=offset)
            if not head:
                head = {k: d.get(k) for k in ("underlying", "underlying_price", "underlying_at", "contracts", "greeks_as_of")}
            elif d.get("greeks_as_of") != head["greeks_as_of"]:
                raise self._fail(ProviderUnavailable("unavailable: the LSE Greeks changed day while the chain was paged"))
            page = d.get("rows") or []
            rows += page
            offset += len(page)
            if not page or len(page) < PAGE or offset >= (d.get("contracts") or 0):
                break
        return dict(head, rows=rows)

    def preview(self, market: str, symbol: str, timeframe: Optional[str] = None, data: Optional[str] = None) -> dict:
        return self.get("/v3/preview", market=market, symbol=symbol, data=data, timeframe=timeframe)

    def export(self, market: str, symbol: str, timeframe: str, start: str, end: str, data: Optional[str] = None,
               fmt: str = "json") -> dict:
        """History between two dates (rows are charged; the app never calls this on a schedule)."""
        return self.get("/v3/export", market=market, symbol=symbol, data=data, timeframe=timeframe,
                        **{"from": start, "to": end, "format": fmt})

    def usage(self) -> dict:
        return self.get("/v3/usage")

    # ---------------------------------------------------------------- session cache
    def _file(self, root: str, session: date) -> Optional[Path]:
        return self.cache / "chains" / f"{root}_{session.isoformat()}.json" if self.cache else None

    def cached(self, root: str, session: date) -> Optional[dict]:
        f = self._file(root, session)
        try:
            return json.loads(f.read_text(encoding="utf-8")) if f else None
        except (OSError, ValueError):
            return None

    def session_chain(self, root: str, session: date, **filters) -> Optional[dict]:
        """The chain whose Greeks are for `session`: from disk once landed (never fetched again); otherwise fetched
        (at most every 15 minutes) and returned only if its Greeks are that session's. None while they have not
        landed: the caller uses the newest landed session and names its date, never waits."""
        have = self.cached(root, session)
        if have and have.get("landed"):
            return have
        if have and self.clock() - have.get("fetched_at", 0) < REFETCH_S:
            return None
        got = self.chain(root, **filters)
        gs = session_of(got.get("greeks_as_of"))
        landed = gs == session
        rec = dict(got, root=root, session=session.isoformat(), fetched_at=self.clock(), landed=landed,
                   filters=filters)
        if gs and gs > session:
            landed = False                  # newer Greeks already: that session's chain is gone from this endpoint
            rec.update(landed=False, rows=[], note=f"the Greeks already moved on to {gs}")
        f = self._file(root, session)
        if f:
            _atomic_write(f, rec if landed else {k: v for k, v in rec.items() if k != "rows"})
            if landed:
                self._log_landing(root, session, got.get("greeks_as_of"))
        return rec if landed else None

    def _log_landing(self, root: str, session: date, greeks_as_of: Optional[str]) -> None:
        """The first time a session's Greeks were seen, per root: when the Greeks become usable before 09:30."""
        f = self.cache / "landing.json"
        try:
            seen = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            seen = {}
        k = f"{root} {session.isoformat()}"
        if k not in seen:
            seen[k] = {"first_seen": datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(),
                       "greeks_as_of": greeks_as_of}
            _atomic_write(f, seen)

    def newest_landed(self, root: str, before: Optional[date] = None) -> Optional[dict]:
        """The newest session chain on disk whose Greeks landed (before `before` when given)."""
        folder = self.cache / "chains" if self.cache else None
        if not folder or not folder.is_dir():
            return None
        best = None
        for f in folder.glob(f"{root}_*.json"):
            try:
                d = date.fromisoformat(f.stem.split("_", 1)[1])
            except ValueError:
                continue
            if (before is None or d < before) and (best is None or d > best[0]):
                rec = self.cached(root, d)
                if rec and rec.get("landed"):
                    best = (d, rec)
        return best[1] if best else None

    # ---------------------------------------------------------------- Data health
    def health_row(self, usage: Optional[dict] = None) -> dict:
        """One Data health row (gexpro/health.py): plan, calls today, last greeks_as_of, cache age, landing times."""
        landing = {}
        try:
            landing = json.loads((self.cache / "landing.json").read_text(encoding="utf-8")) if self.cache else {}
        except (OSError, ValueError):
            pass
        last = max(landing.values(), key=lambda v: v.get("greeks_as_of") or "", default={})
        plan = None
        if usage:
            plans = {v.get("plan") for v in (usage.get("history") or {}).values() if isinstance(v, dict)}
            plan = ", ".join(sorted(p for p in plans if p)) or None
        bits = [f"calls today {self.limiter.today()}/{self.limiter.per_day}"]
        if plan:
            bits.insert(0, f"plan {plan}")
        if last:
            bits.append(f"newest Greeks {last.get('greeks_as_of', '')[:16]} UTC, first seen {last.get('first_seen', '')[:16]} UTC")
        why = why_not_here()
        # no page reads LSE yet: the OCC + LSE chain (rework workstream 4) waits for the owner's approval of its math
        return {"name": "Option IVs (LSE)", "provider": "London Strategic Edge (local only)", "pages": [],
                "last_ok": datetime.fromtimestamp(self.last_ok, timezone.utc).isoformat() if self.last_ok else None,
                "error": why or (None if self._key else "unavailable: no LSE key") or self.last_error,
                "detail": "; ".join(bits), "note": "connected; no page uses it yet"}
