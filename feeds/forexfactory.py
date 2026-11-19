"""Economic calendar from ForexFactory's public weekly export (the feed behind its calendar export).

  GET https://nfs.faireconomy.media/ff_calendar_thisweek.json
  -> [{"title", "country", "date": ISO with ET offset, "impact": High|Medium|Low|Holiday,
       "forecast", "previous"}, ...]          (checked 2026-10-21; no "actual" values in this feed)

The feed asks for light use, so it is fetched at most every `ttl_s` (default 30 min) and the last good
copy is kept in memory and on disk (%LOCALAPPDATA%/gexsys/ff_calendar.json). Personal use.

keep_copy(): the hosted build also saves each new fetch, unchanged, under its fetch time, so the history archive can
keep the copy that was current before each 09:30 (what was listed before the open; the feed has no history).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("feeds.forexfactory")
FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
IMPACTS = ("High", "Medium", "Low", "Holiday")
KEEP_DAYS = 7                                    # = gexpro.archive.LOOKBACK_DAYS: long enough for any due day


def _cache_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "gexsys" / "ff_calendar.json"


def normalize_events(raw) -> list[dict]:
    """Keep well-formed events, sorted by time; never invent fields."""
    out = []
    for e in raw if isinstance(raw, list) else []:
        try:
            t = datetime.fromisoformat(str(e["date"]))
            if t.tzinfo is None:
                continue
        except (KeyError, ValueError):
            continue
        impact = str(e.get("impact", ""))
        out.append({"title": str(e.get("title", "")).strip(), "country": str(e.get("country", "")).strip(),
                    "time": t.astimezone(timezone.utc).isoformat(), "impact": impact if impact in IMPACTS else "Low",
                    "forecast": str(e.get("forecast") or ""), "previous": str(e.get("previous") or "")})
    return sorted(out, key=lambda x: x["time"])


def keep_copy(data: dict, folder: Path, now: Optional[datetime] = None) -> Optional[Path]:
    """Save a fetched copy as folder/YYYYMMDD/HHMMSS_us.json (UTC, from fetched_at), once; drop folders older than
    KEEP_DAYS. Nothing is saved without a fetch time (no copy yet)."""
    if not data.get("fetched_at") or not data.get("events"):
        return None
    t = datetime.fromisoformat(data["fetched_at"]).astimezone(timezone.utc)
    f = folder / t.strftime("%Y%m%d") / t.strftime("%H%M%S_%f.json")
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"fetched_at": data["fetched_at"], "events": data["events"]}), encoding="utf-8")
    old = ((now or datetime.now(timezone.utc)) - timedelta(days=KEEP_DAYS)).strftime("%Y%m%d")
    for d in folder.iterdir():
        if d.is_dir() and d.name < old:
            for x in d.glob("*.json"):
                x.unlink()
            d.rmdir()
    return f


class Calendar:
    def __init__(self, ttl_s: float = 1800.0, opener: Callable = urllib.request.urlopen,
                 clock: Callable[[], float] = time.time, cache_path: Optional[Path] = None):
        self.ttl_s, self.opener, self.clock = ttl_s, opener, clock
        self.cache_path = cache_path or _cache_path()
        self._lock = threading.Lock()
        self._data: Optional[dict] = None
        self._last_try = -1e18
        try:
            self._data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    def get(self) -> dict:
        with self._lock:
            if self.clock() - self._last_try >= self.ttl_s or self._data is None and self.clock() - self._last_try >= 60:
                self._last_try = self.clock()
                self._refresh()
            return dict(self._data or {"events": [], "fetched_at": None},
                        source="ForexFactory calendar (faireconomy.media weekly export)")

    def peek(self) -> Optional[dict]:
        """The last copy without fetching (None before the first load)."""
        return dict(self._data) if self._data else None

    def _refresh(self) -> None:
        req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0 (gexsys personal use)",
                                                        "Accept": "application/json"})
        try:
            with self.opener(req, timeout=20) as r:
                events = normalize_events(json.loads(r.read().decode("utf-8")))
        except (urllib.error.URLError, OSError, ValueError) as e:     # 429 / network / bad JSON: keep last copy
            log.warning("calendar refresh failed: %s", e)
            if self._data is not None:
                self._data["error"] = f"latest refresh failed ({e}); showing the copy from {self._data.get('fetched_at')}"
            else:
                self._data = {"events": [], "fetched_at": None, "error": f"calendar unavailable ({e})"}
            return
        if not events:
            log.warning("calendar feed returned no usable events; keeping the previous copy")
            return
        self._data = {"events": events, "fetched_at": datetime.now(timezone.utc).isoformat()}
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            pass
