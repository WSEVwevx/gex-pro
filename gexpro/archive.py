"""The history archive: free options-chain history does not exist, so GEX PRO keeps its own, from 2026-11-18 on.

Written once a day by the hosted build (python -m gexpro archive, .github/workflows/website.yml) to the repository's
`archive` branch: public, timestamped by git, append-only. One folder per trading day, days/YYYY-MM-DD/:

  {M}-open.json      the saved snapshot the plan uses: the last usable one in the 30 hours before 09:30 ET
  {M}-midday.json    the usable one nearest 12:00 ET (within 30 minutes; ties: the earlier one)
  {M}-close.json     the last usable one at or before the close (within 60 minutes; early closes from marketcal)
  {M}-candidates.json  every snapshot seen for that day, so the choice can be re-derived by anyone
  calendar.json      the ForexFactory weekly calendar as last fetched before 09:30 ET (in the 30 hours before), unchanged:
                     what was listed before the open (from 2026-11-19; the feed has no history of its own)
  {sym}-1m.json      1-minute bars [unix s, open, high, low, close, volume]: NQ=F and ES=F for the whole Globex day
                     (18:00 ET after the previous trading day to 17:00 ET), ^NDX and ^GSPC for the cash session; futures files
                     also name the contract each stretch of bars belongs to and flag roll weeks
  manifest.json      SHA-256 and size of every file, the rules version, what is missing and why

M is NQ or ES. A snapshot is the engine's saved summary, byte for byte: levels, ranked levels, expected move, regime,
GEX profile (abs_by_strike, by_expiry), the 09:30 futures mapping (futures_map) and the chain's own time (asof).
"Usable" is the plan's own rule (gexpro/context.py pre_open): not UNAVAILABLE, not a backup estimate, and has a daily expected move.

A day is written after 17:15 ET once all its parts are in, or with its gaps named after GIVE_UP_DAYS (snapshots are
kept 7 days in the build's state, 1-minute bars about 30 days by Yahoo). Existing days are never rewritten: this
module only adds days the branch does not have, and tools/stress/lookahead_audit.py (A1, A2) fails if any archive
file changed after it was written or no longer matches its manifest.
"""
from __future__ import annotations

import hashlib
import json
import logging
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from gexsys import marketcal

log = logging.getLogger("gexpro.archive")
NY = marketcal.NY
RULES_VERSION = 3                              # 2 (from 2026-11-19): Yahoo's live-quote row is no longer kept as a bar
                                               # 3: calendar.json added (a missing copy is named, never waited for)
FIRST_DAY = date(2026, 11, 18)                 # the archive starts here; earlier days are not recoverable
PRE_OPEN_WINDOW = timedelta(hours=30)          # = gexpro.context.PRE_OPEN_WINDOW (tested)
MIDDAY = time(12, 0)
MIDDAY_WINDOW = timedelta(minutes=30)
CLOSE_WINDOW = timedelta(minutes=60)
WRITE_AFTER = time(17, 15)                     # the futures day ends 17:00 ET; Yahoo's last bars are in by then
GIVE_UP_DAYS = 3                               # after this, a day is written with its gaps named
LOOKBACK_DAYS = 7                              # the build's state keeps 7 days of snapshots
LATE_AFTER = time(18, 0)                       # Data health: a trading day still missing at 18:00 ET is an error
MARKETS = {"NQ": {"futures": "NQ=F", "index": "^NDX"}, "ES": {"futures": "ES=F", "index": "^GSPC"}}
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&period1={p1}&period2={p2}&includePrePost=true"
UA = {"User-Agent": "Mozilla/5.0 (GEX PRO archive)"}


def file_name(sym: str) -> str:
    """NQ=F -> NQF-1m.json, ^NDX -> NDX-1m.json (no characters that need quoting in a URL or a shell)."""
    return "".join(ch for ch in sym if ch.isalnum()) + "-1m.json"


# ---------------------------------------------------------------- which snapshots
def candidates(folder: Path, d: date) -> list[dict]:
    """Every saved snapshot whose chain time could matter for d: [open - 30 h, close], oldest first.
    Snapshot files sit in UTC-day folders named by their asof (YYYYMMDD/HHMMSS_us.json)."""
    lo, hi = marketcal.rth_open_dt(d) - PRE_OPEN_WINDOW, marketcal.rth_close_dt(d)
    out = []
    day = lo.astimezone(timezone.utc).date()
    while day <= hi.astimezone(timezone.utc).date():
        for f in sorted((folder / day.strftime("%Y%m%d")).glob("*.json")):
            if f.name.endswith(".chain.json"):
                continue
            try:
                s = json.loads(f.read_text(encoding="utf-8"))
                t = datetime.fromisoformat(s["asof"])
            except (OSError, ValueError, KeyError):
                continue
            if lo <= t <= hi:
                em = ((s.get("extras") or {}).get("expected_move") or {}).get("daily_points")
                out.append({"file": f"{f.parent.name}/{f.name}", "asof": t.isoformat(), "status": s.get("status"),
                            "usable": bool(s.get("status") != "UNAVAILABLE" and not s.get("backup") and em)})
        day += timedelta(days=1)
    return sorted(out, key=lambda c: c["asof"])


def choose(cands: list[dict], d: date) -> dict:
    """{"open" | "midday" | "close": candidate or None} by the rules in the module docstring."""
    o, c = marketcal.rth_open_dt(d), marketcal.rth_close_dt(d)
    noon = datetime.combine(d, MIDDAY, NY)
    ok = [(datetime.fromisoformat(x["asof"]), x) for x in cands if x["usable"]]
    pre = [x for t, x in ok if o - PRE_OPEN_WINDOW <= t < o]
    mid = sorted(((abs(t - noon), t, x) for t, x in ok if o <= t <= c and abs(t - noon) <= MIDDAY_WINDOW), key=lambda r: r[:2])
    end = [x for t, x in ok if c - CLOSE_WINDOW <= t <= c]
    return {"open": pre[-1] if pre else None, "midday": mid[0][2] if mid else None, "close": end[-1] if end else None}


def calendar_copy(folder: Path, d: date) -> Optional[tuple[str, str]]:
    """(file, fetched_at) of the last calendar copy fetched in [09:30 - 30 h, 09:30) ET (feeds.forexfactory.keep_copy)."""
    o = marketcal.rth_open_dt(d)
    best = None
    day = (o - PRE_OPEN_WINDOW).astimezone(timezone.utc).date()
    while day <= o.astimezone(timezone.utc).date():
        for f in sorted((folder / day.strftime("%Y%m%d")).glob("*.json")):
            try:
                t = datetime.fromisoformat(json.loads(f.read_text(encoding="utf-8"))["fetched_at"])
            except (OSError, ValueError, KeyError):
                continue
            if o - PRE_OPEN_WINDOW <= t < o and (best is None or t > best[2]):
                best = (f"{f.parent.name}/{f.name}", t.isoformat(), t)
        day += timedelta(days=1)
    return best[:2] if best else None


WHY = {"open": "no usable snapshot in the 30 hours before 09:30 ET", "midday": "no usable snapshot within 30 minutes of 12:00 ET",
       "close": "no usable snapshot in the hour before the close"}


# ---------------------------------------------------------------- 1-minute bars
def parse_bars(raw: bytes) -> list[list]:
    """[[unix s, open, high, low, close, volume], ...]: whole minutes only. Bars without a price are left out, and so
    is Yahoo's live-quote row, which it appends off the minute (e.g. 16:59:59 ET, flat, volume 0: archived in
    2026-11-18's futures files under rules version 1)."""
    r = json.loads(raw)["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(r.get("timestamp") or []):
        o, h, lo, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, lo, c) or min(o, h, lo, c) <= 0 or int(t) % 60:
            continue
        out.append([int(t), round(o, 2), round(h, 2), round(lo, 2), round(c, 2), int(q["volume"][i] or 0)])
    return out


def futures_window(d: date) -> tuple[datetime, datetime]:
    """d's Globex day (marketcal.globex_day): every futures bar since the previous trading day's file ended."""
    return marketcal.globex_day(d)


def contract_segments(root: str, bars: list[list]) -> list[dict]:
    """Which quarterly contract each stretch of a continuous series (NQ=F) shows: Yahoo switches at the quarterly
    expiry's 09:30 ET settlement and does not back-adjust, so the price jumps there without the market moving."""
    segs: list[dict] = []
    for b in bars:
        k = marketcal.continuous_contract(root, datetime.fromtimestamp(b[0], timezone.utc))
        if segs and segs[-1]["contract"] == k:
            segs[-1]["to"] = b[0]
        else:
            segs.append({"contract": k, "from": b[0], "to": b[0]})
    return segs


def roll_week(d: date) -> bool:
    """The 8 days before a quarterly expiry (the conventional roll date to the expiry, inclusive)."""
    return marketcal.roll_week(d)


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
        return r.read()


def fetch_bars(sym: str, lo: datetime, hi: datetime, get: Callable[[str], bytes] = _get) -> list[list]:
    url = YAHOO.format(sym=urllib.request.quote(sym, safe=""), p1=int(lo.timestamp()), p2=int(hi.timestamp()))
    return [b for b in parse_bars(get(url)) if lo.timestamp() <= b[0] < hi.timestamp()]


def bar_record(m: str, sym: str, d: date, lo: datetime, hi: datetime, bars: list[list]) -> dict:
    """One {sym}-1m.json file: the bars of [lo, hi) and, for futures, their contracts and the roll-week flag."""
    rec = {"symbol": sym, "session": d.isoformat(), "from": int(lo.timestamp()), "to": int(hi.timestamp()),
           "source": "Yahoo Finance chart API, 1-minute", "fields": ["t", "open", "high", "low", "close", "volume"], "bars": bars}
    if sym.endswith("=F"):
        rec["contracts"] = contract_segments(m, bars)
        rec["roll_week"] = roll_week(d)
        rec["contract_switch"] = len(rec["contracts"]) > 1
    return rec


# ---------------------------------------------------------------- one day
def _json(x) -> bytes:
    return (json.dumps(x, separators=(",", ":"), sort_keys=True) + "\n").encode()


def build_day(d: date, folders: dict[str, Path], now: datetime, get: Callable[[str], bytes] = _get,
              commit: Optional[str] = None, calendar: Optional[Path] = None) -> tuple[Optional[dict[str, bytes]], list[str]]:
    """({relative path: bytes} for days/<d>/, or None while a part is missing and it is not yet time to give up;
    the gaps in words). A missing calendar copy is named but never waited for: after 09:30 none can appear."""
    files: dict[str, bytes] = {}
    gaps: list[str] = []
    chosen: dict = {}
    for m, folder in sorted(folders.items()):
        cands = candidates(folder, d)
        pick = choose(cands, d)
        files[f"{m}-candidates.json"] = _json(cands)
        chosen[m] = {}
        for k, c in pick.items():
            chosen[m][k] = c and {"file": c["file"], "asof": c["asof"]}
            if c is None:
                gaps.append(f"{m} {k} snapshot: {WHY[k]}")
            else:
                files[f"{m}-{k}.json"] = (folder / c["file"]).read_bytes()
        syms = MARKETS[m]
        for sym, (lo, hi) in ((syms["futures"], futures_window(d)), (syms["index"], (marketcal.rth_open_dt(d), marketcal.rth_close_dt(d)))):
            try:
                bars = fetch_bars(sym, lo, hi, get)
            except Exception as e:                            # any failure is named in the manifest
                bars, err = [], f"{type(e).__name__}: {e}"[:160]
            else:
                err = None if bars else "the source returned no bars"
            if err:
                gaps.append(f"{sym} 1-minute bars: {err}")
                continue
            files[file_name(sym)] = _json(bar_record(m, sym, d, lo, hi, bars))
    if gaps and now < datetime.combine(d + timedelta(days=GIVE_UP_DAYS), WRITE_AFTER, NY):
        return None, gaps
    cal = calendar_copy(calendar, d) if calendar else None
    if cal:
        files["calendar.json"] = (calendar / cal[0]).read_bytes()
    else:
        gaps.append("calendar: no ForexFactory copy fetched in the 30 hours before 09:30 ET")
    files["manifest.json"] = _json({
        "session": d.isoformat(), "rules_version": RULES_VERSION, "written_at": now.astimezone(timezone.utc).isoformat(),
        "build_commit": commit, "early_close": d in marketcal.early_closes(d.year), "roll_week": roll_week(d),
        "chosen": chosen, "calendar": cal and {"file": cal[0], "fetched_at": cal[1]}, "missing": gaps,
        "files": {n: {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for n, b in sorted(files.items())}})
    return {f"days/{d.isoformat()}/{n}": b for n, b in files.items()}, gaps


def due_days(now: datetime, have: set[str]) -> list[date]:
    """Trading days from FIRST_DAY within the last LOOKBACK_DAYS whose 17:15 ET has passed and that the branch lacks."""
    out, d = [], now.astimezone(NY).date()
    for _ in range(LOOKBACK_DAYS + 1):
        if d >= FIRST_DAY and marketcal.is_trading_day(d) and d.isoformat() not in have \
                and now >= datetime.combine(d, WRITE_AFTER, NY):
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def missing_days(now: datetime, have: set[str]) -> list[str]:
    """Trading days from FIRST_DAY whose 18:00 ET has passed and that the branch lacks (Data health: an error)."""
    out, d = [], FIRST_DAY
    while d <= now.astimezone(NY).date():
        if marketcal.is_trading_day(d) and d.isoformat() not in have and now >= datetime.combine(d, LATE_AFTER, NY):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def append_only_violations(name_status: str) -> list[str]:
    """`git diff --name-status A B` between two archive commits: anything but an added file is a violation."""
    return [line for line in name_status.splitlines() if line.strip() and not line.startswith("A\t")]


# ---------------------------------------------------------------- the build's summary (Data health, Backtesting tab)
def index_record(days: dict[str, dict], now: datetime, error: Optional[str] = None, last_ok: Optional[str] = None,
                 pending: Optional[dict] = None) -> dict:
    """What the site shows: depth per market (sessions with the 09:30 snapshot a study starts from), the newest day,
    days missing past 18:00 ET. days = {date: manifest}; last_ok = the previous successful check, kept on a failure."""
    have = set(days)
    depth = {m: sorted(d for d, man in days.items() if f"{m}-open.json" in man.get("files", {})) for m in MARKETS}
    checked = now.astimezone(timezone.utc).isoformat()
    return {"checked": checked, "last_ok": last_ok if error else checked, "first_day": FIRST_DAY.isoformat(), "error": error,
            "pending": pending or {},
            "missing": missing_days(now, have),
            "gaps": {d: man.get("missing") for d, man in sorted(days.items()) if man.get("missing")},
            "markets": {m: {"sessions": len(v), "from": v[0] if v else None, "through": v[-1] if v else None}
                        for m, v in depth.items()}}


def health_row(idx: Optional[dict]) -> dict:
    row = {"name": "History archive", "provider": "this site's own build (archive branch)", "pages": ["Backtesting"],
           "last_ok": None, "error": None, "note": None, "fresh_h": 2}
    if not idx:
        return dict(row, note="not checked yet in this build's saved state")
    row["last_ok"] = idx.get("last_ok")
    pend = idx.get("pending") or {}
    why = lambda d: f" ({pend[d][0]})" if pend.get(d) else ""
    errs = ([idx["error"]] if idx.get("error") else []) + \
           ([f"{len(idx['missing'])} trading day(s) missing after 18:00 ET: {', '.join(d + why(d) for d in idx['missing'][-3:])}"]
            if idx.get("missing") else [])
    row["error"] = "; ".join(errs) or None
    if pend and not row["error"]:
        d = sorted(pend)[-1]
        row["note"] = f"{d} waits for missing parts: {pend[d][0]}"
    elif idx.get("gaps") and not row["error"]:
        last = sorted(idx["gaps"])[-1]
        row["note"] = f"{len(idx['gaps'])} day(s) saved with gaps, newest {last}: {idx['gaps'][last][0]}"
    return row


# ---------------------------------------------------------------- the hosted build's step (git plumbing, no checkout)
BRANCH = "archive"
SNAPSHOT_KEYS = {"NQ": "NQ-CBOE", "ES": "ES-CBOE"}     # the hosted build's workers (gexsys/service.py MarketWorker.key)


def _git(*a: str, inp: Optional[bytes] = None, env: Optional[dict] = None, check: bool = True) -> str:
    import os
    import subprocess
    p = subprocess.run(["git", *a], input=inp, capture_output=True, env=None if env is None else {**os.environ, **env})
    if check and p.returncode:
        raise RuntimeError(f"git {a[0]}: {p.stderr.decode(errors='replace').strip()[:300]}")
    return p.stdout.decode()


class _Nothing(Exception):
    """Nothing is due: skip the network."""


def _exists(obj: str) -> bool:
    import subprocess
    return subprocess.run(["git", "cat-file", "-e", obj], capture_output=True).returncode == 0


def run(state: Path, now: Optional[datetime] = None, push: bool = True, get: Callable[[str], bytes] = _get) -> dict:
    """Fetch the archive branch's file list (trees only), add the due days, push, and save the summary the site reads
    (state/archive-index.json). Never changes a file the branch already has: a day is only ever added whole."""
    import os
    import tempfile
    now = now or datetime.now(timezone.utc)
    cache_f, index_f = state / "archive-manifests.json", state / "archive-index.json"
    try:
        manifests = json.loads(cache_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifests = {}
    error, wrote, pending = None, [], {}
    try:
        tip = None
        if not due_days(now, set(manifests)):
            raise _Nothing                                       # every due day is already archived: no network
        if _git("ls-remote", "--heads", "origin", BRANCH).strip():
            _git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", BRANCH)
            tip = _git("rev-parse", "FETCH_HEAD").strip()
        have = set()
        if tip:
            have = {p.rsplit("/", 1)[-1] for p in _git("ls-tree", "--name-only", f"{tip}:days").split()}
            for d in sorted(have - set(manifests)):              # read once, then kept in the state cache
                manifests[d] = json.loads(_git("cat-file", "-p", f"{tip}:days/{d}/manifest.json"))
        folders = {m: state / "snapshots" / k for m, k in SNAPSHOT_KEYS.items()}
        commit = os.environ.get("GEXPRO_BUILD_COMMIT") or os.environ.get("GITHUB_SHA")     # the commit the deploy gate built
        new: dict[str, bytes] = {}
        for d in due_days(now, have):
            files, gaps = build_day(d, folders, now, get=get, commit=commit, calendar=state / "calendar")
            if files is None:
                log.info("archive %s not written yet: %s", d, "; ".join(gaps))
                pending[d.isoformat()] = gaps
                continue
            new.update(files)
            wrote.append(d.isoformat())
        if new and push:
            with tempfile.TemporaryDirectory() as tmp:
                env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
                if tip:
                    _git("read-tree", tip, env=env)
                for path, b in sorted(new.items()):
                    if tip and _exists(f"{tip}:{path}"):
                        raise RuntimeError(f"{path} already exists: the archive is append-only")
                    blob = _git("hash-object", "-w", "--stdin", inp=b).strip()
                    _git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
                tree = _git("write-tree", env=env).strip()
                who = {"GIT_AUTHOR_NAME": "github-actions[bot]", "GIT_COMMITTER_NAME": "github-actions[bot]",
                       "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
                       "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com"}
                c = _git("commit-tree", tree, *(["-p", tip] if tip else []), "-m", f"Archive {', '.join(wrote)}", env=who).strip()
                try:
                    _git("push", "-q", "origin", f"{c}:refs/heads/{BRANCH}")  # fast-forward only: history is never rewritten
                except RuntimeError:
                    # another run (a second lane) may have written the same days first: then that is not a failure
                    _git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", BRANCH)
                    now_have = {p.rsplit("/", 1)[-1] for p in _git("ls-tree", "--name-only", "FETCH_HEAD:days").split()}
                    if not set(wrote) <= now_have:
                        raise
                    log.info("archive: %s already written by another run", ", ".join(wrote))
                    for d in wrote:
                        manifests[d] = json.loads(_git("cat-file", "-p", f"FETCH_HEAD:days/{d}/manifest.json"))
                    new, wrote = {}, []
            for path, b in new.items():
                if path.endswith("/manifest.json"):
                    manifests[path.split("/")[1]] = json.loads(b)
    except _Nothing:
        pass
    except Exception as e:                                       # named on Data health, never silent
        log.exception("archive step failed")
        error = f"{type(e).__name__}: {e}"[:300]
    state.mkdir(parents=True, exist_ok=True)
    cache_f.write_text(json.dumps(manifests), encoding="utf-8")
    idx = index_record(manifests, now, error, (load_index(state) or {}).get("last_ok"), pending)
    idx["wrote"] = wrote
    index_f.write_text(json.dumps(idx), encoding="utf-8")
    return idx


def load_index(state: Path) -> Optional[dict]:
    try:
        return json.loads((state / "archive-index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class ArchiveComponent:
    """The site's view of the archive: data/archive.json (the Backtesting tab's depth) and the Data health row.
    Only the hosted build has an archive step; the local app says unavailable and why."""
    name = "archive"
    LOCAL = {"unavailable": "The archive is written by the hosted site's daily build; this copy of the app does not run it."}

    def __init__(self) -> None:
        self.state: Optional[Path] = None

    def index(self) -> dict:
        return (load_index(self.state) if self.state else None) or self.LOCAL

    def routes(self) -> dict:
        return {"/api/archive": lambda q: (200, self.index())}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def build_static(self, data: Path, state: Path) -> dict:
        self.state = state
        data.mkdir(parents=True, exist_ok=True)
        (data / "archive.json").write_text(json.dumps(self.index()), encoding="utf-8")
        return {}

    def sources(self) -> list:
        return [health_row(load_index(self.state))] if self.state else []
