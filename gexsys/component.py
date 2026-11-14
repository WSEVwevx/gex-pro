"""The GEX component: the market workers and everything the website asks them for.

Same shape as every GEX PRO component (see gexpro/components.py):
  routes()                    /health, /api/markets, /api/all, /api/levels, /api/pine, /api/pine/all,
                              /api/indicator (the TradingView script, read from disk on every request),
  start() / stop()            one background refresh thread per market
                              /api/heatmap?market=NQ&tf=5m (candles + GEX history for the heatmap page)
                              /api/bias-history?market=NQ (the session's levels minute by minute, for the Bias replay)
  build_static(data, state)   all.json, pine-*.txt, indicator.json, heatmap-{NQ,ES}-{1m,5m,15m}.json and
                              bias-history-{NQ,ES}.json for the hosted site

Endpoints, by example:
  /api/levels?key=NQ-CBOE                    one worker's latest result (market=NQ picks the first NQ worker)
  /api/pine?key=NQ-CBOE[&which=published]    one worker's Pine payload (text)
  /api/pine/all[?which=published&market=NQ]  payloads joined with "|": one paste for every chart
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from . import heatmap, marketcal, timeline
from .config import MarketConfig
from .export import combine
from .heatmap import RANGE, HeatmapCache, build as build_heatmap
from .indicator import info as indicator_info
from .models import to_jsonable
from .service import MarketWorker, NotifyGate

log = logging.getLogger("gexsys.component")


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


def _calendar(now: datetime) -> dict:
    """This year's and next year's market holidays and 13:00 closes, for the page's session clock."""
    y = now.astimezone(marketcal.NY).year
    days = lambda fn: sorted(d.isoformat() for yr in (y, y + 1) for d in fn(yr))
    hol = [d for yr in (y, y + 1) for d in marketcal.nyse_holidays(yr)]
    return {"holidays": days(marketcal.nyse_holidays), "early_closes": days(marketcal.early_closes),
            # holidays when the futures still trade until 13:00, and evenings with no session (before New Year's Day...)
            "globex_mornings": sorted(d.isoformat() for d in hol if marketcal.globex_morning(d)),
            "no_evening": sorted((d - timedelta(days=1)).isoformat() for d in hol if not marketcal.globex_morning(d))}


def _all(workers: Iterable[MarketWorker], **extra) -> dict:
    now = datetime.now(timezone.utc)
    return to_jsonable(dict(now=now.isoformat(), calendar=_calendar(now), **extra, workers=[
        {"key": w.key, "market": w.cfg.market, "provider": w.label, "source": w.cfg.source,
         "description": w.cfg.description, "health": w.health(), "published": w.published, "result": w.result}
        for w in workers]))


class GexComponent:
    name = "gex"

    def __init__(self, configs: Iterable[MarketConfig] = (), gate: Optional[NotifyGate] = None):
        self.configs = list(configs)
        self.gate = gate or NotifyGate()
        self.workers: dict[str, MarketWorker] = {}
        self.heat = HeatmapCache()
        self._bars: dict = {}                  # market -> (fetched, 1-minute candles) for the Bias replay, 60 s

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
                "/api/indicator": lambda q: (200, indicator_info()), "/api/heatmap": self._heatmap,
                "/api/bias-history": self._bias_history}

    def _bias_history(self, q):
        w = self._worker(q)
        if not w:
            return 404, {"error": "unknown market"}
        m = w.cfg.market
        got = self._bars.get(m)
        if not got or time.time() - got[0] > 60:
            try:
                got = self._bars[m] = (time.time(), heatmap.fetch_candles(m, "1m"))
            except Exception as e:                     # no price line; snapshots saved with their mapping still replay
                log.warning("bias replay candles %s: %s", m, e)
                got = got or (0.0, [])
        return 200, timeline.build(w.store.root / w.key, m, w.cfg.method, got[1])

    def _heatmap(self, q):
        w = self._worker(q)
        tf = (q.get("tf") or ["5m"])[0]
        if not w or tf not in RANGE:
            return 404, {"error": "unknown market or timeframe"}
        return 200, self.heat.get(w, tf)

    def sources(self) -> list:
        """One row per outside source for the Data health page (see gexpro/health.py)."""
        rows = []
        for w in self.workers.values():
            h = w.health()
            ok = datetime.fromtimestamp(w.last_success, timezone.utc).isoformat() if w.last_success else None
            calc = h.get("calc_status")
            rows.append({"name": f"{w.cfg.market} options chain", "provider": f"{w.label} ({w.cfg.source}, 15-min delayed)",
                         "pages": ["Levels", "Live table", "Heatmap", "Bias", "TradingView paste"], "last_ok": ok,
                         "error": w.last_error if w.failures else None, "fresh_h": 2,
                         "note": "first refresh in progress" if not ok and not w.failures
                         else f"the last calculation was {calc}" if calc and calc != "OK" else None})
            # the hourly paste: late when it is more than 90 minutes old while the futures trade
            pub = w.published or {}
            trading = marketcal.session_state(datetime.now(timezone.utc)) in ("RTH", "ETH")
            rows.append({"name": f"{w.cfg.market} TradingView paste", "provider": "GEX PRO (hourly, from the options chain)",
                         "pages": ["Copy for TradingView", "Indicator"], "last_ok": pub.get("published_at"),
                         "error": None, "fresh_h": 1.5 if trading else None,
                         "detail": f"the paste on the site is the {pub['slot_et']} ET one" if pub.get("slot_et") else None})
        for m in dict.fromkeys(w.cfg.market for w in self.workers.values()):
            s = self.heat.status.get(m) or {}
            rows.append({"name": f"{m} futures candles", "provider": "Yahoo Finance", "pages": ["Heatmap"],
                         "last_ok": s.get("ok"), "error": s.get("error"), "fresh_h": 2,
                         "note": None if s else "checked the first time the Heatmap opens"})
        return rows

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
    def build_static(self, data: Path, state: Path, keep_days: int = 7) -> dict:
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
        for w in workers:
            bars: list = []
            for tf in RANGE:
                try:
                    candles = heatmap.fetch_candles(w.cfg.market, tf)
                    hm = build_heatmap(w, tf, candles=candles)
                    self.heat.note(w.cfg.market)
                    if tf == "1m":
                        bars = candles                        # the replay's price: the same bars, untrimmed
                except Exception as e:                        # candles unavailable: the GEX history alone
                    log.warning("heatmap %s %s: %s", w.key, tf, e)
                    self.heat.note(w.cfg.market, f"{type(e).__name__}: {e}")
                    hm = build_heatmap(w, tf, candles=[])
                _write(data / f"heatmap-{w.cfg.market}-{tf}.json", json.dumps(hm, separators=(",", ":")))
            tl = timeline.build(w.store.root / w.key, w.cfg.market, w.cfg.method, bars)
            _write(data / f"bias-history-{w.cfg.market}.json", json.dumps(tl, separators=(",", ":")))
        for which, pick in (("latest", lambda w: w.result and w.result.get("pine")),
                            ("published", lambda w: w.published and w.published.get("payload"))):
            _write(data / f"pine-{which}.txt", combine([p for p in map(pick, workers) if p]))
            for m in sorted({w.cfg.market for w in workers}):
                _write(data / f"pine-{which}-{m}.txt",
                       combine([p for p in map(pick, [w for w in workers if w.cfg.market == m]) if p]))
        return {w.key: (w.health()["status"], (w.result or {}).get("summary", {}).get("status")) for w in workers}
