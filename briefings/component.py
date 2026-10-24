"""The briefings component.

Same shape as every GEX PRO component (see gexpro/components.py):
  routes()                    /api/briefings: the latest NY AM and Asia briefings, recent history, next times
  start() / stop()            a background check every minute that writes a briefing when one is due
  build_static(data, state)   briefings.json for the hosted site (history kept in state/briefings)

Inputs come from the app shell: context() -> data snapshot (see compose.py), is_trading_day(date),
and an optional notify(title, body) for a Windows notification when a briefing is written.

The local app also copies in, hourly, every briefing the public site has that it is missing (mirror()),
so the page has history even when this PC was off at briefing time. Briefings written here win.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import schedule
from .compose import compose

log = logging.getLogger("briefings")
KEEP = 40
MIRROR_URL = "https://wsevwevx.github.io/gex-pro/data/briefings.json"      # the public copy ($GEXPRO_BRIEFINGS_MIRROR)


def _default_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "gexsys" / "briefings"


class BriefingsComponent:
    name = "briefings"

    def __init__(self, context: Callable[[], dict], is_trading_day: Callable, notify: Optional[Callable] = None,
                 store_dir: Optional[Path] = None, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.context, self.is_trading_day, self.notify, self.clock = context, is_trading_day, notify, clock
        self.dir = Path(store_dir) if store_dir else _default_dir()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---------------------------------------------------------------- storage
    def _path(self, sid: str) -> Path:
        return self.dir / f"{sid}.json"

    def _load(self, sid: str) -> Optional[dict]:
        try:
            return json.loads(self._path(sid).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _save(self, sid: str, b: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path(sid).with_suffix(".tmp")
        tmp.write_text(json.dumps(b), encoding="utf-8")
        tmp.replace(self._path(sid))
        for old in sorted(self.dir.glob("*.json"))[:-KEEP]:
            old.unlink(missing_ok=True)

    def history(self) -> list[dict]:
        out = []
        for f in self.dir.glob("*.json"):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(out, key=lambda b: b.get("slot", ""), reverse=True)      # newest first, by slot time

    def mirror(self, url: Optional[str] = None, fetch: Optional[Callable[[str], bytes]] = None) -> list[str]:
        """Copy briefings from the public site that this app does not have. Returns the ids copied."""
        url = url or os.environ.get("GEXPRO_BRIEFINGS_MIRROR") or MIRROR_URL
        if not url or url == "off":
            return []
        def get(u):
            req = urllib.request.Request(u, headers={"User-Agent": "GEX PRO briefings"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read()
        try:
            remote = json.loads((fetch or get)(url)).get("by_id") or {}
        except Exception as e:
            log.warning("briefings mirror %s failed: %s", url, e)
            return []
        copied = []
        with self._lock:
            for sid, b in sorted(remote.items()):
                if not isinstance(b, dict) or not b.get("kind") or not b.get("slot") or self._path(sid).exists():
                    continue
                try:
                    if schedule.slot_id(b["kind"], datetime.fromisoformat(b["slot"])) != sid:
                        continue                                   # only well-formed briefings
                except (ValueError, TypeError):
                    continue
                self._save(sid, b)
                copied.append(sid)
        return copied

    # ---------------------------------------------------------------- writing
    def tick(self) -> list[str]:
        """Write every briefing that is due and not written yet. Returns the ids written."""
        written = []
        with self._lock:
            now = self.clock()
            for kind in schedule.KINDS:
                d = schedule.due(kind, now, self.is_trading_day)
                if not d:
                    continue
                slot, session = d
                sid = schedule.slot_id(kind, slot)
                if self._path(sid).exists():
                    continue
                ctx = self.context()
                if not any(m.get("price") and m.get("zero_gamma") is not None for m in ctx.get("markets", [])):
                    log.info("briefing %s waiting for GEX levels", sid)
                    continue
                morning = None
                if kind == "asia":
                    am = self._load(f"{slot.astimezone(schedule.NY):%Y-%m-%d}-nyam")
                    morning = {m["market"]: m for m in (am or {}).get("markets", [])}
                b = compose(kind, ctx, slot, session, morning)
                self._save(sid, b)
                written.append(sid)
                log.info("briefing %s written", sid)
                if self.notify:
                    try:
                        self.notify(f"GEX PRO {b['title']}", b["headline"][:200])
                    except Exception:                     # a notification problem never blocks the briefing
                        log.exception("briefing notification failed")
        return written

    def payload(self) -> dict:
        hist = self.history()
        latest = {k: next((b for b in hist if b.get("kind") == k), None) for k in schedule.KINDS}
        now = self.clock()
        nxt = {k: (lambda s: s.isoformat() if s else None)(schedule.next_slot(k, now, self.is_trading_day)) for k in schedule.KINDS}
        return {"latest": latest, "next": nxt,
                "history": [{"id": schedule.slot_id(b["kind"], datetime.fromisoformat(b["slot"])), "kind": b["kind"],
                             "title": b["title"], "session": b["session"], "slot": b["slot"]} for b in hist],
                "by_id": {schedule.slot_id(b["kind"], datetime.fromisoformat(b["slot"])): b for b in hist[:20]}}

    # ---------------------------------------------------------------- component contract
    def routes(self) -> dict:
        def get(q):
            self.tick()                                    # catch up on request too (cheap when nothing is due)
            return 200, self.payload()
        return {"/api/briefings": get}

    def start(self) -> None:
        def loop():
            last_mirror = 0.0
            while not self._stop.is_set():
                try:
                    if datetime.now(timezone.utc).timestamp() - last_mirror > 3600:
                        last_mirror = datetime.now(timezone.utc).timestamp()
                        self.mirror()
                    self.tick()
                except Exception:
                    log.exception("briefing check failed")
                self._stop.wait(60)
        self._thread = threading.Thread(target=loop, daemon=True, name="briefings")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def build_static(self, data: Path, state: Path) -> dict:
        self.dir = state / "briefings"
        self.tick()
        data.mkdir(parents=True, exist_ok=True)
        (data / "briefings.json").write_text(json.dumps(self.payload()), encoding="utf-8")
        return {}
