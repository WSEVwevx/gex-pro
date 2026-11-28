"""The smile estimate's own track record: a separate series, on this PC only (rework workstream 8).

Plans frozen from the OCC chain with the previous session's per-strike smile (snapshots whose chain is "occ+lse", see
gexsys/providers/occ.py), graded exactly as the main record, but kept apart:
  - its own folder (%LOCALAPPDATA%/gexsys/trackrecord-smile), never mixed with the main record or its Cboe-era grades;
  - no public copy: never mirrored from or to the hosted site, never built into it (the series rests on London
    Strategic Edge data, which stays on this PC);
  - its own endpoint, /api/trackrecord-smile; no TradingView pastes (the paste stays on hold: study occ_lse_accuracy
    could not check levels against a full chain).
Unlocked by the owner on 2026-11-28 after study occ_lse_accuracy v2 part A ("better", n = 10)."""
from __future__ import annotations

import os
from pathlib import Path

from .component import TrackRecordComponent
from .score import summarize

CREDIT = "Data: London Strategic Edge"     # = gexsys.providers.lse.CREDIT (tests/test_smile_series.py); local only
SINCE = "2026-11-28"          # the owner's word; sessions before it were never planned from the smile


def _default_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "gexsys" / "trackrecord-smile"


class SmileTrackRecord(TrackRecordComponent):
    name = "trackrecord_smile"

    def __init__(self, *a, store_dir=None, **k):
        super().__init__(*a, store_dir=store_dir or _default_dir(), **k)

    def routes(self) -> dict:
        def get(q):
            self.tick()
            return 200, self.payload()
        return {"/api/trackrecord-smile": get}

    def mirror(self, url=None, fetch=None) -> list[str]:
        return []                                    # no public copy exists, by design

    def build_static(self, data, state) -> dict:
        return {}                                    # never part of the hosted site

    def backtest(self) -> dict:
        return {}                                    # the historical backtest is the main record's; not repeated here

    def sources(self) -> list:
        return []                                    # same price source as the main record, which has the row

    def _started(self):
        return max(super()._started() or SINCE, SINCE)

    def payload(self) -> dict:
        ss = self.sessions()
        graded = [s for s in ss if s.get("status") == "graded"]
        stats = {m: summarize([s for s in graded if s["market"] == m]) for m in sorted({s["market"] for s in ss})}
        stats["ALL"] = summarize(graded)
        return {"now": self.clock().isoformat(), "started": self._started(), "series": "occ+lse", "credit": CREDIT,
                "label": f"estimate: OCC open interest + the previous session's smile ({CREDIT})",
                "stats": stats, "sessions": ss}
