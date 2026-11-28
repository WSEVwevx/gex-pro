"""The morning save: the free, raw inputs of the OCC estimate, saved by GitHub before each open (owner, 2026-11-28).

Why: OCC's series-search shows today's open interest only (no date, no history), so a morning nobody fetched is lost
for good. With this save, the PC no longer has to be awake before 09:30 ET: it rebuilds a missed morning from these
exact bytes (the catch-up, W2 of docs/prompts/private-app.md), adding the previous session's smile from LSE locally.

What (the URLs gexsys/providers/occ.py fetches, byte for byte, nothing parsed or changed):
  occ_{NDX|SPX|QQQ|SPY}            OCC series-search (open interest, end of day)
  yvol_{VIX1D|VIX9D|VIX|VIX3M|VXN} Yahoo daily chart, 1 month (the VIX-family closes)
  price_{NDX|SPX|QQQ|SPY}          Yahoo chart meta (price, previous close)
Free and keyless; no LSE call and no LSE value here, ever (its licence: no LSE data on GitHub).

When: GitHub runs it every 30 minutes on weekday mornings; it saves only on trading days, from 05:00 ET until the open
(gexsys/marketcal.py: holidays, DST), and does nothing at any other time.

Where: the repository's `raw` branch, days/YYYY-MM-DD/HHMMSSZ/ (the UTC fetch time): one {name}.txt per input and a
manifest.json (fetch time, URL, HTTP status, size, SHA-256 of every file). Timestamped by git and append-only, as
the archive: a run only adds its own new folder; it never changes or removes a file the branch has.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from gexsys import marketcal
from gexsys.providers import occ

log = logging.getLogger("gexpro.rawsave")

BRANCH = "raw"
WINDOW = timedelta(hours=4, minutes=30)          # 05:00 ET to the open: OCC's new file is up by then on normal days
RULES = 1                                        # bump when what is saved changes; written into every manifest


def inputs() -> dict[str, str]:
    """{name: URL}: exactly the URLs the OCC provider asks for (gexsys/providers/occ.py), so a replay matches it."""
    q = urllib.parse.quote
    out = {f"occ_{s}": occ.OCC_URL.format(sym=s) for s in ("NDX", "SPX", "QQQ", "SPY")}
    out.update({f"yvol_{n}": occ.VOL_URL.format(sym=q(v)) for n, v in occ.VOL_SYM.items()})
    out.update({f"price_{s}": occ.PRICE_URL.format(sym=q(y)) for s, y in occ.YAHOO_SYM.items()})
    return out


def due(now: datetime) -> Optional[date]:
    """The session this run saves for: today (ET) when it is a trading day and now is in [open - WINDOW, open)."""
    d = now.astimezone(marketcal.NY).date()
    if not marketcal.is_trading_day(d):
        return None
    opens = marketcal.rth_open_dt(d)
    return d if opens - WINDOW <= now < opens else None


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=occ.UA), timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def fetch(now: datetime, get: Callable[[str], tuple[int, bytes]] = _get) -> dict[str, bytes]:
    """{path in the branch: bytes} for one run: every input that answered 200 with a body, and the manifest naming
    all of them, the failed ones with their status (so a gap is never silent)."""
    d = due(now)
    if d is None:
        return {}
    folder = f"days/{d.isoformat()}/{now.astimezone(timezone.utc):%H%M%S}Z"
    files, man = {}, {"rules": RULES, "session": d.isoformat(), "fetched_at": now.astimezone(timezone.utc).isoformat(),
                      "files": {}}
    for name, url in inputs().items():
        try:
            status, body = get(url)
        except (OSError, ValueError, http.client.HTTPException) as e:      # one bad input never loses the others
            status, body, err = 0, b"", f"{type(e).__name__}: {e}"[:200]
        else:
            err = None if status == 200 and body else f"HTTP {status}" + (", empty" if status == 200 else "")
        entry = {"url": url, "status": status}
        if err:
            entry["error"] = err
        else:
            files[f"{folder}/{name}.txt"] = body
            entry.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        man["files"][name] = entry
    files[f"{folder}/manifest.json"] = (json.dumps(man, indent=1, sort_keys=True) + "\n").encode()
    return files


def _git(*a: str, inp: Optional[bytes] = None, env: Optional[dict] = None) -> str:
    from .archive import _git as g
    return g(*a, inp=inp, env=env)


WHO = {"GIT_AUTHOR_NAME": "github-actions[bot]", "GIT_COMMITTER_NAME": "github-actions[bot]",
       "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
       "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com"}


def push(files: dict[str, bytes], message: str, tries: int = 3) -> None:
    """Add `files` to the branch as one commit on top of its tip (git plumbing, no checkout). Fails if a path exists
    already (append-only). A push that loses a race to another run is retried on the new tip."""
    for attempt in range(tries):
        tip = None
        if _git("ls-remote", "--heads", "origin", BRANCH).strip():
            _git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", BRANCH)
            tip = _git("rev-parse", "FETCH_HEAD").strip()
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            if tip:
                _git("read-tree", tip, env=env)
                clash = [p for p in files if _git("ls-tree", "--name-only", tip, p).strip()]
                if clash:
                    raise RuntimeError(f"{clash[0]} already exists: the raw branch is append-only")
            for path, b in sorted(files.items()):
                blob = _git("hash-object", "-w", "--stdin", inp=b).strip()
                _git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
            tree = _git("write-tree", env=env).strip()
            c = _git("commit-tree", tree, *(["-p", tip] if tip else []), "-m", message, env=WHO).strip()
        try:
            _git("push", "-q", "origin", f"{c}:refs/heads/{BRANCH}")      # fast-forward only: history never rewritten
            return
        except RuntimeError:
            if attempt == tries - 1:
                raise
            log.info("rawsave: the branch moved during the push; retrying on its new tip")


def run(now: Optional[datetime] = None, get: Callable[[str], tuple[int, bytes]] = _get, do_push: bool = True) -> dict:
    """One run: fetch when due, push. Returns {session, saved, failed}; nothing at all outside the window."""
    os.environ["GEX_NO_LSE"] = "1"            # this runs on GitHub: LSE stays off (gexsys/providers/lse.py refuses)
    now = now or datetime.now(timezone.utc)
    files = fetch(now, get)
    if not files:
        return {"session": None, "saved": [], "failed": []}
    man = json.loads(next(b for p, b in files.items() if p.endswith("/manifest.json")))
    saved = sorted(n for n, e in man["files"].items() if "error" not in e)
    failed = sorted(f"{n} ({e['error']})" for n, e in man["files"].items() if "error" in e)
    if do_push:
        push(files, f"Morning save {man['session']} {man['fetched_at'][11:19]}Z ({len(saved)} of {len(man['files'])})")
    return {"session": man["session"], "saved": saved, "failed": failed}
