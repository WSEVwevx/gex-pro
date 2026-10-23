"""Local HTTP service: background refresh workers + JSON API + website.

One worker per config, keyed "<MARKET>-<PROVIDER>" (e.g. NQ-CBOE, ES-CBOE).

Endpoints (bound to 127.0.0.1 by default):
  GET /health                          per-worker status, last success, last error, data age
  GET /api/markets                     configured workers
  GET /api/all                         everything the website needs, one call
  GET /api/levels?key=NQ-CBOE          one worker's latest result (market=NQ picks the first NQ worker)
  GET /api/pine?key=NQ-CBOE[&which=published]   one worker's Pine payload (text/plain)
  GET /api/pine/all[?which=published]  ALL workers' payloads joined with "|" - one paste for every chart
  GET /api/indicator                   the TradingView script, read from disk on every request
  GET /                                website (dashboard/index.html)
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from . import marketcal, publish
from .alerts import AlertEngine
from .config import MarketConfig, make_provider
from .export import combine
from .models import to_jsonable
from .pipeline import run_once
from .providers.base import AuthError
from .storage import SnapshotStore

log = logging.getLogger("gexsys.service")
DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"


class NotifyGate:
    """Ensures one desktop notification per publish slot across all workers."""

    def __init__(self):
        self._lock = threading.Lock()
        self._done: set = set()

    def first(self, slot: datetime) -> bool:
        with self._lock:
            if slot in self._done:
                return False
            self._done.add(slot)
            return True


class MarketWorker(threading.Thread):
    def __init__(self, cfg: MarketConfig, gate: Optional[NotifyGate] = None):
        self.cfg = cfg
        self.provider = make_provider(cfg)
        self.label = getattr(self.provider, "label", cfg.provider.get("name", "?").upper())
        self.key = f"{cfg.market}-{self.label}"
        super().__init__(daemon=True, name=f"worker-{self.key}")
        self.store = SnapshotStore(cfg.storage.get("root", "data/snapshots"), cfg.storage.get("store_raw", False))
        self.alerts = AlertEngine(cfg.alerts)
        self.gate = gate or NotifyGate()
        self.result: Optional[dict] = None
        self.last_success: Optional[float] = None
        self.last_error: Optional[str] = None
        self.failures = 0
        self.next_run = 0.0
        self.published: Optional[dict] = None
        self.published_slot: Optional[datetime] = None
        self.notify_desktop = publish.notify_desktop
        self.send_webhook = publish.send_webhook
        self._stop = threading.Event()
        root = Path(os.path.expandvars(cfg.storage.get("root", "data/snapshots")))
        self._good_path = root / f"last_good_{self.key}.json"
        self._pub_path = root / f"published_{self.key}.json"
        self._restore_last_good()
        self._restore_published()

    def _restore_published(self) -> None:
        """Keep the last scheduled payload across restarts (and across hosted-site runs, which start fresh)."""
        try:
            p = json.loads(self._pub_path.read_text(encoding="utf-8"))
            slot = datetime.strptime(p["slot_et"], "%Y-%m-%d %H:%M").replace(tzinfo=marketcal.NY)
        except (OSError, ValueError, KeyError):
            return
        self.published, self.published_slot = p, slot

    def _save_published(self) -> None:
        try:
            self._pub_path.parent.mkdir(parents=True, exist_ok=True)
            self._pub_path.write_text(json.dumps(to_jsonable(self.published)), encoding="utf-8")
        except OSError as e:
            log.warning("could not save published payload for %s: %s", self.key, e)

    def _restore_last_good(self) -> None:
        """Start with the last usable result from a previous run (clearly marked), not an empty page."""
        try:
            r = json.loads(self._good_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        r["summary"].setdefault("warnings", []).append("restored from the previous run - waiting for a fresh refresh")
        self.result = r
        self.last_error = "showing the last good result from a previous run"

    def _save_last_good(self, r: dict) -> None:
        try:
            self._good_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._good_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(to_jsonable(r)), encoding="utf-8")
            os.replace(tmp, self._good_path)
        except OSError as e:
            log.warning("could not save last good result for %s: %s", self.key, e)

    def _accept(self, r: dict) -> bool:
        """Use a new result unless it is UNAVAILABLE while a usable one exists (free feeds blank out
        overnight).  The kept result's own timestamp shows its age; last_error explains why."""
        new_bad = r["summary"].get("status") == "UNAVAILABLE"
        have_good = self.result is not None and self.result["summary"].get("status") != "UNAVAILABLE"
        if new_bad and have_good:
            why = (r["summary"].get("warnings") or ["unusable data"])[-1]
            kept = self.result["summary"].get("asof", "")[:16].replace("T", " ")
            self.last_error = f"latest data unusable ({why}); keeping the result from {kept} UTC"
            return False
        self.result = r
        if not new_bad:
            self._save_last_good(r)
        return True

    def run(self) -> None:
        while not self._stop.is_set():
            self.step()
            self._stop.wait(max(1.0, self.next_run - time.time()))

    def _maybe_publish(self, now: datetime) -> None:
        slot = publish.due(self.published_slot, now, self.cfg.publish)
        if slot is None or not self.result or not self.result.get("pine"):
            return
        s = self.result["mapped"] or self.result["summary"]
        zg = (s.get("zero_gamma") or {}).get("price")
        info = {"slot_et": slot.strftime("%Y-%m-%d %H:%M"), "published_at": now.isoformat(),
                "regime": s.get("regime"), "zero_gamma": zg, "status": s.get("status"), "provider": self.label,
                "space": "futures" if self.result["mapped"] else "options-underlying"}
        self.published = dict(info, payload=self.result["pine"])
        self.published_slot = slot
        self._save_published()
        log.info("published %s payload for slot %s", self.key, info["slot_et"])
        pc = self.cfg.publish
        if pc.desktop_notify and self.gate.first(slot):
            self.notify_desktop(f"GEX PRO levels updated ({slot:%H:%M} ET)",
                                "Open http://127.0.0.1:8765, click 'Copy for TradingView', "
                                "paste into the indicator's Levels payload.")
        url = os.environ.get("GEX_PUBLISH_WEBHOOK_URL") or os.environ.get("GEX_ALERT_WEBHOOK_URL")
        if url and pc.webhook_format != "none":
            self.send_webhook(url, publish.webhook_body(pc.webhook_format, self.key, self.result["pine"], info))

    def step(self, now: Optional[datetime] = None) -> None:
        now = now or datetime.now(timezone.utc)
        try:
            r = run_once(self.cfg, self.provider, self.store, self.alerts)
            if self._accept(r):
                self.last_success, self.last_error, self.failures = time.time(), None, 0
            interval = marketcal.refresh_interval(now, self.cfg.refresh)
            self._maybe_publish(now)
        except AuthError as e:
            self.last_error, interval = f"AUTH: {e}", 3600      # do not hammer the provider with bad creds
            self.failures += 1
        except Exception as e:     # keep serving last good result; mark it stale via age
            log.exception("refresh failed for %s", self.key)
            self.failures += 1
            self.last_error = f"{type(e).__name__}: {e}"
            interval = min(900, 30 * 2 ** min(self.failures, 5))   # connection recovery backoff
        self.alerts.stale_check(self.key, self.last_success)
        nxt = publish.next_slot(now, self.cfg.publish)
        if nxt is not None:     # wake up for the next publish time even if the cadence is slower
            interval = min(interval, max(5.0, (nxt - now).total_seconds()))
        self.next_run = time.time() + interval

    def health(self) -> dict:
        age = None if self.last_success is None else time.time() - self.last_success
        status = "starting" if self.last_success is None and not self.last_error else (
            "down" if self.last_success is None else (
                "stale" if age > self.cfg.alerts.stale_after_s else ("degraded" if self.last_error else "ok")))
        summ = (self.result or {}).get("summary") or {}
        nxt = publish.next_slot(datetime.now(timezone.utc), self.cfg.publish)
        return {"key": self.key, "market": self.cfg.market, "source": self.cfg.source, "provider": self.label,
                "status": status, "calc_status": summ.get("status"), "age_s": age, "last_error": self.last_error,
                "consecutive_failures": self.failures,
                "session": marketcal.session_state(datetime.now(timezone.utc)),
                "next_run_in_s": max(0.0, self.next_run - time.time()),
                "published_slot_et": self.published["slot_et"] if self.published else None,
                "next_publish_et": nxt.strftime("%Y-%m-%d %H:%M") if nxt else None}

    def stop(self) -> None:
        self._stop.set()


def make_handler(workers: dict[str, MarketWorker], calendar=None, posts=None):
    if calendar is None:
        from .news import Calendar
        calendar = Calendar()
    if posts is None:
        from .posts import Posts
        posts = Posts()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.debug("http %s", fmt % args)

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(to_jsonable(obj)).encode(), "application/json")

        def _text(self, s: str):
            self._send(200, s.encode(), "text/plain; charset=utf-8")

        def _worker(self, q) -> Optional[MarketWorker]:
            if q.get("key"):
                return workers.get(q["key"][0].upper())
            m = (q.get("market") or [""])[0].upper()
            return next((w for w in workers.values() if not m or w.cfg.market == m), None)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            which = (q.get("which") or ["latest"])[0]
            if u.path == "/health":
                hs = [w.health() for w in workers.values()]
                ok = any(h["status"] in ("ok", "degraded") for h in hs)
                return self._json(200 if ok else 503, {"ok": ok, "workers": hs})
            if u.path == "/api/news":
                return self._json(200, calendar.get())
            if u.path == "/api/posts":
                return self._json(200, posts.get())
            if u.path == "/api/indicator":
                from .indicator import info
                return self._json(200, info())
            if u.path == "/api/markets":
                return self._json(200, [{"key": k, "market": w.cfg.market, "source": w.cfg.source,
                                         "provider": w.label, "description": w.cfg.description}
                                        for k, w in workers.items()])
            if u.path == "/api/all":
                return self._json(200, {"now": datetime.now(timezone.utc).isoformat(), "workers": [
                    {"key": k, "market": w.cfg.market, "provider": w.label, "source": w.cfg.source,
                     "description": w.cfg.description, "health": w.health(), "published": w.published,
                     "result": w.result} for k, w in workers.items()]})
            if u.path == "/api/pine/all":
                m = (q.get("market") or [""])[0].upper()
                ws = [w for w in workers.values() if not m or w.cfg.market == m]
                if which == "published":
                    return self._text(combine([w.published["payload"] for w in ws if w.published]))
                return self._text(combine([w.result["pine"] for w in ws if w.result]))
            if u.path in ("/api/levels", "/api/pine"):
                w = self._worker(q)
                if not w:
                    return self._json(404, {"error": "unknown key/market"})
                if not w.result:
                    return self._json(503, {"error": "no successful calculation yet", "health": w.health()})
                if u.path == "/api/pine":
                    if which == "published":
                        if not w.published:
                            return self._json(404, {"error": "nothing published yet", "health": w.health()})
                        return self._text(w.published["payload"])
                    return self._text(w.result["pine"])
                return self._json(200, dict(w.result, health=w.health(), published=w.published))
            if u.path in ("/", "/index.html"):
                f = DASHBOARD / "index.html"
                if f.exists():
                    return self._send(200, f.read_bytes(), "text/html; charset=utf-8")
            return self._json(404, {"error": "not found"})

    return Handler


class ExclusiveHTTPServer(ThreadingHTTPServer):
    """One server per port. Python's default (SO_REUSEADDR) lets a second copy bind the same port on
    Windows without any error, and the browser then silently keeps talking to the OLD copy."""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):                      # Windows
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve(configs: list[MarketConfig], host: str = "127.0.0.1", port: int = 8765) -> None:
    gate = NotifyGate()
    workers: dict[str, MarketWorker] = {}
    for c in configs:
        w = MarketWorker(c, gate)
        if w.key in workers:
            raise ValueError(f"duplicate worker {w.key} in configs")
        workers[w.key] = w
    try:
        httpd = ExclusiveHTTPServer((host, port), make_handler(workers))   # bind first: fail fast if port busy
    except OSError:
        print(f"\nGEX PRO is ALREADY RUNNING in another window, so this copy will not start.\n"
              f"Use that window, or close it and run START.bat again to pick up updates.\n"
              f"Website: http://{host}:{port}", flush=True)
        raise SystemExit(3)
    for w in workers.values():
        w.start()
    log.info("serving on http://%s:%d (workers: %s)", host, port, ", ".join(workers))
    print(f"GEX PRO running - open http://{host}:{port}  (Ctrl+C to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for w in workers.values():
            w.stop()
