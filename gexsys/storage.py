"""Snapshot storage: one JSON document per calculation, grouped by market and day.

By default only *derived* summaries are stored.  Raw chains are stored only if
`store_raw=True`, because many vendor licences restrict redistribution and
retention of raw quotes - check yours before enabling it.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

from .models import ChainSnapshot, to_jsonable


class SnapshotStore:
    def __init__(self, root: str = "data/snapshots", store_raw: bool = False):
        self.root = Path(os.path.expandvars(root))   # allows %LOCALAPPDATA%/... (keeps churn out of OneDrive)
        self.store_raw = store_raw

    def _dir(self, market: str, asof: datetime) -> Path:
        d = self.root / market / asof.strftime("%Y%m%d")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, market: str, summary: dict, raw: Optional[ChainSnapshot] = None) -> Path:
        asof = datetime.fromisoformat(summary["asof"])
        d = self._dir(market, asof)
        stem = asof.strftime("%H%M%S_%f")
        path = d / f"{stem}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(to_jsonable(summary), separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)          # atomic on the same filesystem
        if raw is not None and self.store_raw:
            (d / f"{stem}.chain.json").write_text(json.dumps(to_jsonable(raw)), encoding="utf-8")
        return path

    def iter_summaries(self, market: str) -> Iterator[dict]:
        base = self.root / market
        if not base.exists():
            return
        for p in sorted(base.glob("*/*.json")):
            if p.name.endswith(".chain.json"):
                continue
            try:
                yield json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

    def prune(self, market: str, keep_days: int = 12) -> int:
        """Delete this market's day folders older than keep_days (the track record needs the last 10
        days of pre-open snapshots). Returns how many folders went."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime("%Y%m%d")
        gone = 0
        for day in (self.root / market).glob("????????"):
            if day.is_dir() and day.name.isdigit() and day.name < cutoff:
                shutil.rmtree(day, ignore_errors=True)
                gone += 1
        return gone

    def latest(self, market: str) -> Optional[dict]:
        last = None
        for s in self.iter_summaries(market):
            last = s
        return last
