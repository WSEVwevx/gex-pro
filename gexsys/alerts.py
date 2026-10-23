"""Service-side alerts for events Pine cannot observe (Pine only sees a pasted
snapshot, so recalculation shifts, regime changes between snapshots and data
staleness are detected here).

Delivery: structured log line always; optional JSON POST to GEX_ALERT_WEBHOOK_URL.
Alerts can be delayed, missed, duplicated, or triggered by changing data.  They
are informational and never place orders.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger("gexsys.alerts")


@dataclass
class AlertConfig:
    level_shift_ticks: float = 20.0
    cooldown_s: float = 900.0
    stale_after_s: float = 1800.0
    webhook_url: Optional[str] = None


@dataclass
class AlertEngine:
    cfg: AlertConfig = field(default_factory=AlertConfig)
    clock: Callable[[], float] = time.time
    sender: Optional[Callable[[str, dict], None]] = None
    _last: dict = field(default_factory=dict)

    def evaluate(self, market: str, prev: Optional[dict], cur: dict, tick: float) -> list[dict]:
        events = []
        if cur.get("status") == "UNAVAILABLE":
            events.append({"type": "data_unavailable", "detail": "; ".join(cur.get("warnings", [])[-3:])})
        if prev:
            if prev.get("regime") != cur.get("regime") and cur.get("regime") not in (None, "UNAVAILABLE"):
                events.append({"type": "regime_change", "from": prev.get("regime"), "to": cur.get("regime")})
            for key in ("zero_gamma", "call_wall", "put_wall"):
                a, b = (prev.get(key) or {}).get("price"), (cur.get(key) or {}).get("price")
                if a is not None and b is not None and abs(b - a) / tick >= self.cfg.level_shift_ticks:
                    events.append({"type": "level_shift", "level": key, "from": a, "to": b,
                                   "ticks": (b - a) / tick})
                elif (a is None) != (b is None):
                    events.append({"type": "level_appeared" if b is not None else "level_vanished", "level": key})
        return [e for e in events if self._fire(market, e)]

    def stale_check(self, market: str, last_success_epoch: Optional[float]) -> list[dict]:
        if last_success_epoch is None:
            return []
        age = self.clock() - last_success_epoch
        if age > self.cfg.stale_after_s:
            e = {"type": "data_stale", "age_s": round(age)}
            return [e] if self._fire(market, e) else []
        return []

    def _fire(self, market: str, e: dict) -> bool:
        key = (market, e["type"], e.get("level"))
        now = self.clock()
        if now - self._last.get(key, -1e18) < self.cfg.cooldown_s:
            return False
        self._last[key] = now
        e = dict(e, market=market, ts=now)
        log.warning("ALERT %s", json.dumps(e))
        url = self.cfg.webhook_url or os.environ.get("GEX_ALERT_WEBHOOK_URL")
        if self.sender:
            self.sender(url or "", e)
        elif url:
            try:
                req = urllib.request.Request(url, data=json.dumps(e).encode(), method="POST",
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5).close()
            except OSError as ex:     # alert delivery must never break the pipeline
                log.error("webhook delivery failed: %s", ex)
        return True
