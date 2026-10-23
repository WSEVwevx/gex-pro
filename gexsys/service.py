"""GEX market workers: background refresh, keep-last-good, and the hourly TradingView paste.

One worker per config, keyed "<MARKET>-<PROVIDER>" (e.g. NQ-CBOE, ES-CBOE). The website endpoints that
read them are in gexsys/component.py; the web server itself is the app shell's (gexpro/server.py).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import marketcal, publish
from .alerts import AlertEngine
from .config import MarketConfig, make_provider
from .models import to_jsonable
from .pipeline import run_once
from .providers.base import AuthError
from .storage import SnapshotStore

log = logging.getLogger("gexsys.service")


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
        self._timeline_path = root / f"timeline_{self.key}.jsonl"
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
            self._append_timeline(r)
        return True

    TIMELINE_KEEP = 4000                  # about two weeks of 5-minute refreshes

    def _append_timeline(self, r: dict) -> None:
        """One compact line per good result (chart prices: futures when mapped), for the timeline view."""
        s = r["summary"]
        L = r.get("mapped") or s
        p = lambda v: v.get("price") if isinstance(v, dict) else v
        row = {"t": s.get("asof"), "ref": L.get("futures_equiv_of_ref") or s.get("ref_price"), "zg": p(L.get("zero_gamma")),
               "cw": p(L.get("call_wall")), "pw": p(L.get("put_wall")), "ag": p(L.get("abs_gamma")),
               "net": s.get("net"), "regime": s.get("regime")}
        try:
            self._timeline_path.parent.mkdir(parents=True, exist_ok=True)
            with self._timeline_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            if self._timeline_path.stat().st_size > 1_500_000:          # trim now and then
                lines = self._timeline_path.read_text(encoding="utf-8").splitlines()[-self.TIMELINE_KEEP:]
                self._timeline_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as e:
            log.warning("could not append timeline for %s: %s", self.key, e)

    def timeline(self, hours: float = 120) -> list[dict]:
        """Rows from the last `hours`, oldest first."""
        try:
            lines = self._timeline_path.read_text(encoding="utf-8").splitlines()[-self.TIMELINE_KEEP:]
        except OSError:
            return []
        cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
        out = []
        for ln in lines:
            try:
                row = json.loads(ln)
                if datetime.fromisoformat(row["t"]).timestamp() >= cutoff:
                    out.append(row)
            except (ValueError, KeyError, TypeError):
                continue
        return out

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
