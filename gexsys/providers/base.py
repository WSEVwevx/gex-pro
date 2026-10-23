"""Provider interface plus shared HTTP plumbing: rate limiting, retries with
exponential backoff + jitter, Retry-After handling and error classification."""
from __future__ import annotations

import json
import logging
import random
import threading
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Callable, Optional

from ..models import ChainSnapshot

log = logging.getLogger(__name__)


class ProviderError(Exception):
    pass


class AuthError(ProviderError):
    """Credentials missing/invalid or entitlement absent - never retried."""


class RateLimitError(ProviderError):
    def __init__(self, msg: str, retry_after: Optional[float] = None):
        super().__init__(msg)
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    """Network failure / 5xx after all retries."""


class RateLimiter:
    """Simple thread-safe minimum-interval limiter (requests per minute)."""

    def __init__(self, per_minute: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.interval = 60.0 / per_minute if per_minute > 0 else 0.0
        self._next = 0.0
        self._lock = threading.Lock()
        self._clock, self._sleep = clock, sleep

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            self._sleep(delay)


def http_get_json(url: str, headers: dict, *, timeout: float = 15.0, retries: int = 4,
                  backoff_base: float = 1.0, max_backoff: float = 30.0,
                  sleep: Callable[[float], None] = time.sleep,
                  opener: Callable = urllib.request.urlopen,
                  limiter: Optional[RateLimiter] = None) -> dict:
    """GET JSON with classification:
    401/403 -> AuthError (no retry); 429 -> retry honouring Retry-After, then RateLimitError;
    5xx / network errors -> retry with backoff, then ProviderUnavailable."""
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        if limiter:
            limiter.wait()
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with opener(req, timeout=timeout) as resp:
                body = resp.read()
            return json.loads(body.decode("utf-8")) if body else {}
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise AuthError(f"HTTP {e.code} from provider - check credentials/entitlements") from e
            if e.code == 429:
                ra = _retry_after(e)
                last_exc = RateLimitError("HTTP 429 rate limited", ra)
                delay = ra if ra is not None else _backoff(attempt, backoff_base, max_backoff)
            elif 500 <= e.code < 600:
                last_exc = ProviderUnavailable(f"HTTP {e.code} from provider")
                delay = _backoff(attempt, backoff_base, max_backoff)
            else:
                raise ProviderError(f"HTTP {e.code} from provider for {url.split('?')[0]}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_exc = ProviderUnavailable(f"network error: {e}")
            delay = _backoff(attempt, backoff_base, max_backoff)
        except json.JSONDecodeError as e:
            raise ProviderError(f"provider returned invalid JSON: {e}") from e
        if attempt < retries:
            log.warning("provider request failed (%s); retry %d/%d in %.1fs", last_exc, attempt + 1, retries, delay)
            sleep(delay)
    assert last_exc is not None
    raise last_exc


def _retry_after(e: urllib.error.HTTPError) -> Optional[float]:
    try:
        v = e.headers.get("Retry-After") if e.headers else None
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _backoff(attempt: int, base: float, cap: float) -> float:
    return min(cap, base * (2 ** attempt)) * (0.5 + random.random() / 2)


class Provider(ABC):
    name: str = "base"

    @abstractmethod
    def fetch_snapshot(self, source_key: str, max_dte: float, include_0dte: bool) -> ChainSnapshot:
        """Return a ChainSnapshot for the options source (e.g. 'SPX', 'NDX', 'QQQ')."""
