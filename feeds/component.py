"""The feeds component: what the website's News page, ticker and Screener need.

Same shape as every GEX PRO component (see gexpro/components.py):
  routes()                    /api/news (economic calendar), /api/posts (Truth Social), /api/quotes (ticker), /api/screener
  start() / stop()            nothing runs in the background: each feed fetches on request, cached
  build_static(data, state)   news.json, posts.json, quotes.json and screener.json for the hosted site
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .forexfactory import Calendar
from .quotes import Quotes
from .screener import Screener
from .truthsocial import Posts


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, default=str), encoding="utf-8")


class FeedsComponent:
    name = "feeds"

    def __init__(self, calendar: Optional[Calendar] = None, posts: Optional[Posts] = None, quotes: Optional[Quotes] = None,
                 screener: Optional[Screener] = None):
        self._calendar, self._posts, self._quotes, self._screener = calendar, posts, quotes, screener

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
    def screener(self) -> Screener:
        if self._screener is None:
            self._screener = Screener()
        return self._screener

    def routes(self) -> dict:
        return {"/api/news": lambda q: (200, self.calendar.get()),
                "/api/posts": lambda q: (200, self.posts.get()),
                "/api/quotes": lambda q: (200, self.quotes.get()),
                "/api/screener": lambda q: (200, self.screener.get())}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def build_static(self, data: Path, state: Path) -> dict:
        cal = self._calendar = self._calendar or Calendar(cache_path=state / "ff_calendar.json")
        posts = self._posts = self._posts or Posts(cache_path=state / "truth_posts.json")
        _write(data / "news.json", cal.get())
        _write(data / "posts.json", posts.get())
        _write(data / "quotes.json", self.quotes.get())
        _write(data / "screener.json", self.screener.get())
        return {}
