"""The component contract, and the list of components GEX PRO runs.

A component is any object with:
  name                         short id, e.g. "gex"
  routes() -> {path: handler}  website endpoints it owns; handler(query) -> (status, body), where query
                               is urllib's parse_qs dict and body is a dict/list (sent as JSON) or a str
                               (sent as text). Two components may never claim the same path.
  start() / stop()             begin / end any background work (called by `serve`)
  build_static(data, state)    write its files for the hosted site into `data`; `state` is a folder
                               kept between hosted builds. Returns a dict of status rows (may be empty).

To add a feature: make a new package (independent of the others), give it a component with these
four parts, add it to `default_components` below, and give the website a page that reads its
endpoints (or data/*.json files on the hosted site).
"""
from __future__ import annotations

from typing import Protocol

from feeds.component import FeedsComponent
from gexsys.component import GexComponent


class Component(Protocol):
    name: str

    def routes(self) -> dict: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def build_static(self, data, state) -> dict: ...


def default_components(gex_configs) -> list:
    return [GexComponent(gex_configs), FeedsComponent()]
