"""The GEX component: the market workers and everything the website asks them for.

Same shape as every GEX PRO component (see gexpro/components.py):
  routes()                    /health, /api/markets, /api/all, /api/levels, /api/pine, /api/pine/all,
                              /api/indicator (the TradingView script, read from disk on every request)
  start() / stop()            one background refresh thread per market
  build_static(data, state)   all.json, pine-*.txt and indicator.json for the hosted site

Endpoints, by example:
  /api/levels?key=NQ-CBOE                    one worker's latest result (market=NQ picks the first NQ worker)
  /api/pine?key=NQ-CBOE[&which=published]    one worker's Pine payload (text)
  /api/pine/all[?which=published&market=NQ]  payloads joined with "|": one paste for every chart
"""
from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from .config import MarketConfig
from .export import combine
from .indicator import info as indicator_info
from .models import to_jsonable
from .service import MarketWorker, NotifyGate


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _prune(root: Path, keep_days: int) -> None:
    """Drop snapshot day folders older than keep_days so the hosted site's cached state stays small."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime("%Y%m%d")
    for day in root.glob("*/????????"):
        if day.is_dir() and day.name.isdigit() and day.name < cutoff:
            shutil.rmtree(day, ignore_errors=True)


def _all(workers: Iterable[MarketWorker], **extra) -> dict:
    return to_jsonable(dict(now=datetime.now(timezone.utc).isoformat(), **extra, workers=[
        {"key": w.key, "market": w.cfg.market, "provider": w.label, "source": w.cfg.source,
         "description": w.cfg.description, "health": w.health(), "published": w.published, "result": w.result}
        for w in workers]))


class GexComponent:
    name = "gex"

    def __init__(self, configs: Iterable[MarketConfig] = (), gate: Optional[NotifyGate] = None):
        self.configs = list(configs)
        self.gate = gate or NotifyGate()
        self.workers: dict[str, MarketWorker] = {}

    @classmethod
    def from_workers(cls, workers: dict[str, MarketWorker]) -> "GexComponent":
        c = cls()
        c.workers = dict(workers)
        return c

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if not self.workers:
            for c in self.configs:
                w = MarketWorker(c, self.gate)
                if w.key in self.workers:
                    raise ValueError(f"duplicate worker {w.key} in configs")
                self.workers[w.key] = w
        for w in self.workers.values():
            w.start()

    def stop(self) -> None:
        for w in self.workers.values():
            w.stop()

    # ---------------------------------------------------------------- website endpoints
    def routes(self) -> dict:
        return {"/health": self._health, "/api/markets": self._markets, "/api/all": lambda q: (200, _all(self.workers.values())),
                "/api/pine/all": self._pine_all, "/api/levels": self._levels, "/api/pine": self._pine,
                "/api/indicator": lambda q: (200, indicator_info())}

    def _worker(self, q) -> Optional[MarketWorker]:
        if q.get("key"):
            return self.workers.get(q["key"][0].upper())
        m = (q.get("market") or [""])[0].upper()
        return next((w for w in self.workers.values() if not m or w.cfg.market == m), None)

    def _health(self, q):
        hs = [w.health() for w in self.workers.values()]
        ok = any(h["status"] in ("ok", "degraded") for h in hs)
        return (200 if ok else 503), {"ok": ok, "workers": hs}

    def _markets(self, q):
        return 200, [{"key": k, "market": w.cfg.market, "source": w.cfg.source, "provider": w.label,
                      "description": w.cfg.description} for k, w in self.workers.items()]

    def _pine_all(self, q):
        m = (q.get("market") or [""])[0].upper()
        ws = [w for w in self.workers.values() if not m or w.cfg.market == m]
        if (q.get("which") or ["latest"])[0] == "published":
            return 200, combine([w.published["payload"] for w in ws if w.published])
        return 200, combine([w.result["pine"] for w in ws if w.result])

    def _levels(self, q):
        w = self._worker(q)
        if not w:
            return 404, {"error": "unknown key/market"}
        if not w.result:
            return 503, {"error": "no successful calculation yet", "health": w.health()}
        return 200, dict(w.result, health=w.health(), published=w.published)

    def _pine(self, q):
        w = self._worker(q)
        if not w:
            return 404, {"error": "unknown key/market"}
        if (q.get("which") or ["latest"])[0] == "published":
            if not w.published:
                return 404, {"error": "nothing published yet", "health": w.health()}
            return 200, w.published["payload"]
        if not w.result:
            return 503, {"error": "no successful calculation yet", "health": w.health()}
        return 200, w.result["pine"]

    # ---------------------------------------------------------------- hosted site
    def build_static(self, data: Path, state: Path, keep_days: int = 5) -> dict:
        """One refresh of every market (like START.bat), written as files. `state` keeps the last good
        result, the scheduled payload and recent history between runs."""
        snaps = state / "snapshots"
        workers = []
        for c in self.configs:
            c = replace(c, storage=dict(c.storage, root=str(snaps)), publish=replace(c.publish, desktop_notify=False))
            w = MarketWorker(c)
            w.notify_desktop = lambda *a, **k: False
            w.step()
            workers.append(w)
        _prune(snaps, keep_days)
        self.workers = {w.key: w for w in workers}          # so the app can read this build's results
        _write(data / "all.json", json.dumps(_all(workers, static=True)))
        _write(data / "indicator.json", json.dumps(indicator_info()))
        for which, pick in (("latest", lambda w: w.result and w.result.get("pine")),
                            ("published", lambda w: w.published and w.published.get("payload"))):
            _write(data / f"pine-{which}.txt", combine([p for p in map(pick, workers) if p]))
            for m in sorted({w.cfg.market for w in workers}):
                _write(data / f"pine-{which}-{m}.txt",
                       combine([p for p in map(pick, [w for w in workers if w.cfg.market == m]) if p]))
        return {w.key: (w.health()["status"], (w.result or {}).get("summary", {}).get("status")) for w in workers}
