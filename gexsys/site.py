"""Static website build: the same dashboard as the local service, as plain files any free host can serve.

  python -m gexsys build-site --out _site --state .state

Runs every market once (exactly like one refresh of START.bat), then writes
  index.html                        the dashboard, switched to static mode
  data/all.json, news.json, posts.json   what /api/all, /api/news and /api/posts return locally
  data/pine-latest[-NQ|-ES].txt     the newest TradingView payload
  data/pine-published[-NQ|-ES].txt  the payload from the last scheduled slot (09:45, 11:45, 13:45, 15:30 ET)

`--state` keeps what must survive between runs (last good result, scheduled payload, snapshot history
for "zero gamma moved", news/posts caches). The GitHub workflow caches that folder between runs.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import MarketConfig
from .export import combine
from .models import to_jsonable
from .news import Calendar
from .posts import Posts
from .service import DASHBOARD, MarketWorker

STATIC_FLAG = "<script>window.GEX_STATIC = true;</script>"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _prune(root: Path, keep_days: int) -> None:
    """Drop snapshot day folders older than keep_days so the cached state stays small."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime("%Y%m%d")
    for day in root.glob("*/????????"):
        if day.is_dir() and day.name.isdigit() and day.name < cutoff:
            shutil.rmtree(day, ignore_errors=True)


def build(configs: list[MarketConfig], out: str | Path, state: str | Path, keep_days: int = 5) -> dict:
    out, state = Path(out), Path(state)
    snaps = state / "snapshots"
    workers = []
    for c in configs:
        c = replace(c, storage=dict(c.storage, root=str(snaps)), publish=replace(c.publish, desktop_notify=False))
        w = MarketWorker(c)
        w.notify_desktop = lambda *a, **k: False
        w.step()
        workers.append(w)
    _prune(snaps, keep_days)

    data = out / "data"
    now = datetime.now(timezone.utc).isoformat()
    _write(data / "all.json", json.dumps(to_jsonable({"now": now, "static": True, "workers": [
        {"key": w.key, "market": w.cfg.market, "provider": w.label, "source": w.cfg.source,
         "description": w.cfg.description, "health": w.health(), "published": w.published, "result": w.result}
        for w in workers]})))
    _write(data / "news.json", json.dumps(to_jsonable(Calendar(cache_path=state / "ff_calendar.json").get())))
    _write(data / "posts.json", json.dumps(to_jsonable(Posts(cache_path=state / "truth_posts.json").get())))
    for which, pick in (("latest", lambda w: w.result and w.result.get("pine")),
                        ("published", lambda w: w.published and w.published.get("payload"))):
        _write(data / f"pine-{which}.txt", combine([p for p in map(pick, workers) if p]))
        for m in sorted({w.cfg.market for w in workers}):
            _write(data / f"pine-{which}-{m}.txt", combine([p for p in map(pick, [w for w in workers if w.cfg.market == m]) if p]))

    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    _write(out / "index.html", html.replace("<script>", STATIC_FLAG + "\n<script>", 1))
    _write(out / ".nojekyll", "")
    return {w.key: (w.health()["status"], (w.result or {}).get("summary", {}).get("status")) for w in workers}
