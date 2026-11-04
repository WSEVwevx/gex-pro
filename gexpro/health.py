"""The Data health page: every outside source, when it last worked and whether its last try failed.

Each component may have sources() -> [row]; a row is
  {"name", "provider", "pages": [...], "last_ok": ISO time or date or None, "error": str or None,
   "note": str or None (works, but on a backup or partly), "fresh_h": hours it may go without news, "detail"}.
This module only collects the rows and gives each a status; the website shows them.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("gexpro.health")
# worst first, for the summary
ORDER = ["down", "failing", "late", "partial", "waiting", "ok"]


def _when(s: Optional[str]) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)      # a bare date (a weekly report) counts from midnight UTC


def status(row: dict, now: datetime) -> str:
    """down: never worked and failing | failing: last try failed, older copy shown | late: no news for longer
    than expected | partial: works, on a backup or partly | waiting: not checked yet | ok."""
    ok = _when(row.get("last_ok"))
    if row.get("error"):
        return "failing" if ok else "down"
    if not ok:
        return "waiting"
    if row.get("fresh_h") and (now - ok).total_seconds() > row["fresh_h"] * 3600:
        return "late"
    return "partial" if row.get("note") else "ok"


def collect(components, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    rows = []
    for c in components:
        fn = getattr(c, "sources", None)
        if fn is None:
            continue
        try:
            got = fn()
        except Exception as e:                      # a broken check is itself news, never a blank page
            log.exception("sources of %s failed", c.name)
            got = [{"name": c.name, "provider": "", "pages": [], "last_ok": None, "error": f"could not check: {type(e).__name__}: {e}"}]
        for r in got:
            ok = _when(r.get("last_ok"))
            rows.append(dict(r, status=status(r, now), age_h=None if ok is None else max(0.0, round((now - ok).total_seconds() / 3600, 2))))
    worst = min((ORDER.index(r["status"]) for r in rows), default=len(ORDER) - 1)
    return {"now": now.isoformat(), "worst": ORDER[worst], "sources": rows}


class HealthComponent:
    """Serves /api/sources; on the hosted site writes data/sources.json after every other component built."""
    name = "health"

    def __init__(self, components):
        self.components = components

    def routes(self) -> dict:
        return {"/api/sources": lambda q: (200, collect(self.components))}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def build_static(self, data: Path, state: Path) -> dict:
        out = collect(self.components)
        data.mkdir(parents=True, exist_ok=True)
        (data / "sources.json").write_text(json.dumps(out), encoding="utf-8")
        return {"sources": out["worst"]}
