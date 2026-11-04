"""The feeds component: what the website's News page, ticker and Screener need.

Same shape as every GEX PRO component (see gexpro/components.py):
  routes()                    /api/news (economic calendar), /api/posts (Truth Social), /api/quotes (ticker), /api/screener (NQ / ES drivers),
                              /api/screener/chart?symbol=NVDA (one driver's chart bars)
  start() / stop()            one warm-up of the Screener's slow data; otherwise each feed fetches on request, cached
  build_static(data, state)   news.json, posts.json, quotes.json, screener.json and screener-charts.json
                              for the hosted site
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

from .forexfactory import Calendar
from .quotes import Quotes
from .drivers import Drivers
from .positioning import Positioning
from .truthsocial import Posts


def _state_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "gexsys"


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, default=str), encoding="utf-8")


class FeedsComponent:
    name = "feeds"

    def __init__(self, calendar: Optional[Calendar] = None, posts: Optional[Posts] = None, quotes: Optional[Quotes] = None,
                 screener: Optional[Drivers] = None, positioning: Optional[Positioning] = None):
        self._calendar, self._posts, self._quotes, self._screener = calendar, posts, quotes, screener
        self._positioning = positioning

    # created on first use, so building the hosted site never touches the local caches
    @property
    def calendar(self) -> Calendar:
        if self._calendar is None:
            self._calendar = Calendar()
        return self._calendar

    @property
    def posts(self) -> Posts:
        if self._posts is None:
            self._posts = Posts()
        return self._posts

    @property
    def quotes(self) -> Quotes:
        if self._quotes is None:
            self._quotes = Quotes()
        return self._quotes

    @property
    def screener(self) -> Drivers:
        if self._screener is None:
            self._screener = Drivers(cache_path=_state_dir() / "drivers.json")
        return self._screener

    @property
    def positioning(self) -> Positioning:
        if self._positioning is None:
            self._positioning = Positioning(cache_path=_state_dir() / "positioning.json")
        return self._positioning

    def routes(self) -> dict:
        return {"/api/news": lambda q: (200, self.calendar.get()),
                "/api/posts": lambda q: (200, self.posts.get()),
                "/api/quotes": lambda q: (200, self.quotes.get()),
                "/api/screener": lambda q: (200, self.screener.get()),
                "/api/positioning": lambda q: (200, self.positioning.get()),
                "/api/screener/chart": self._chart}

    def sources(self) -> list:
        """One row per outside source for the Data health page (see gexpro/health.py)."""
        # peek, never fetch: checking health must not trigger (or wait on) the network
        first = lambda page: {"last_ok": None, "error": None, "note": f"checked the first time the {page} loads"}
        cal, posts, quotes, pos = self.calendar.peek(), self.posts.peek(), self.quotes.peek(), self.positioning.peek()
        rows = [{"name": "Economic calendar", "provider": "ForexFactory", "pages": ["News", "Levels"], "fresh_h": 3,
                 **({"last_ok": cal.get("fetched_at"), "error": cal.get("error")} if cal else first("News page"))},
                {"name": "Posts", "provider": (posts or {}).get("source") or "Truth Social", "pages": ["News", "Briefings"], "fresh_h": 2,
                 **({"last_ok": posts.get("fetched_at"), "error": posts.get("error"),
                     "note": "Truth Social did not answer, so the backup archive is in use"
                     if posts.get("source") and posts["source"] != "Truth Social" else None} if posts else first("News page"))}]
        if quotes is None:
            rows.append({"name": "Ticker quotes", "provider": "Yahoo Finance", "pages": ["Top ticker"], **first("page")})
        else:
            qs = quotes.get("quotes") or []
            q_bad = sum(bool(q.get("stale")) for q in qs)
            rows.append({"name": "Ticker quotes", "provider": "Yahoo Finance", "pages": ["Top ticker"], "last_ok": quotes.get("ok_at"),
                         "error": "every quote failed on the last try" if not qs or q_bad == len(qs) else None,
                         "note": f"{q_bad} of {len(qs)} quotes failed on the last try" if 0 < q_bad < len(qs) else None, "fresh_h": 1})
        scr = self.screener.peek()
        if scr is None:
            rows.append({"name": "Screener prices", "provider": "Yahoo Finance", "pages": ["Screener", "Briefings"],
                         "last_ok": None, "error": None, "note": "first load in progress (about 30 seconds after start)"})
        else:
            st = scr.get("stocks") or []
            bad = sum(bool(s.get("stale")) for s in st)
            rows.append({"name": "Screener prices", "provider": "Yahoo Finance", "pages": ["Screener", "Briefings"],
                         "last_ok": scr.get("fetched") if st and bad < len(st) else None,
                         "error": "no stock prices came back" if not st or bad == len(st) else None,
                         "note": f"{bad} of {len(st)} stocks failed on the last try" if 0 < bad < len(st) else None, "fresh_h": 1})
            src = scr.get("weights_source") or ""
            backup = "fallback" in src                 # the copy bundled with the app: old by design, so not "late"
            rows.append({"name": "Index weights", "provider": "slickcharts.com", "pages": ["Screener", "Weekly recap"],
                         "last_ok": scr.get("weights_asof"), "error": None if src else "no index weights", "fresh_h": None if backup else 36,
                         "note": "slickcharts did not answer, so the copy saved with the app is in use" if backup else None})
        if pos is None:
            rows.append({"name": "Big trader positioning", "provider": "CFTC", "pages": ["Bias"], **first("Bias page")})
        else:
            # the OLDEST market's report: one contract that stops updating must not hide behind the other
            dates = [m.get("asof") or "" for m in (pos.get("markets") or {}).values()]
            rows.append({"name": "Big trader positioning", "provider": "CFTC", "pages": ["Bias"], "last_ok": min(dates) if dates and all(dates) else None,
                         "error": pos.get("error") or (None if len(dates) == 2 else "a market's report is missing"), "fresh_h": 11 * 24,
                         "detail": "weekly report: Tuesday's positions, published Friday"})
        return rows

    def _chart(self, q):
        c = self.screener.charts((q.get("symbol") or [""])[0].upper())
        return (200, c) if c else (404, {"error": "not a stock on the screener"})

    def start(self) -> None:
        # the first Screener load fetches weights, earnings and 3-month volumes (~30 s): do it now, not on first open
        threading.Thread(target=self.screener.get, name="drivers-warmup", daemon=True).start()

    def stop(self) -> None:
        pass

    def build_static(self, data: Path, state: Path) -> dict:
        cal = self._calendar = self._calendar or Calendar(cache_path=state / "ff_calendar.json")
        posts = self._posts = self._posts or Posts(cache_path=state / "truth_posts.json")
        _write(data / "news.json", cal.get())
        _write(data / "posts.json", posts.get())
        _write(data / "quotes.json", self.quotes.get())
        self._screener = self._screener or Drivers(cache_path=state / "drivers.json")
        _write(data / "screener.json", self.screener.get())
        _write(data / "screener-charts.json", self.screener.charts())
        self._positioning = self._positioning or Positioning(cache_path=state / "positioning.json")
        _write(data / "positioning.json", self.positioning.get())
        return {}
