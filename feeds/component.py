"""The feeds component: what the website's News page needs.

Same shape as every GEX PRO component (see gexpro/components.py):
  routes()                    /api/news (economic calendar), /api/posts (Truth Social)
  start() / stop()            nothing runs in the background: each feed fetches on request, cached
  build_static(data, state)   news.json and posts.json for the hosted site
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .forexfactory import Calendar
from .truthsocial import Posts


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, default=str), encoding="utf-8")


class FeedsComponent:
    name = "feeds"

    def __init__(self, calendar: Optional[Calendar] = None, posts: Optional[Posts] = None):
        self._calendar, self._posts = calendar, posts

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

    def routes(self) -> dict:
        return {"/api/news": lambda q: (200, self.calendar.get()),
                "/api/posts": lambda q: (200, self.posts.get())}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def build_static(self, data: Path, state: Path) -> dict:
        cal = self._calendar = self._calendar or Calendar(cache_path=state / "ff_calendar.json")
        posts = self._posts = self._posts or Posts(cache_path=state / "truth_posts.json")
        _write(data / "news.json", cal.get())
        _write(data / "posts.json", posts.get())
        return {}
