"""The track record component.

Same shape as every GEX PRO component (see gexpro/components.py):
  routes()                    /api/trackrecord: every graded session, summary statistics, the historical backtest
  start() / stop()            a background check every 10 minutes that freezes and grades sessions
  build_static(data, state)   trackrecord.json for the hosted site (sessions kept in $GEXPRO_TRACK_DIR,
                              else state/trackrecord; the GitHub workflow keeps that folder in a git branch;
                              the recomputable backtest is cached in state/trackrecord-cache)

Inputs from the app shell:
  pre_open(session_date) -> {market: levels or None}   the last calculation timestamped before that
                                                       session's 09:30 ET open (see gexpro/context.py)
  is_trading_day(date), session_close(date) -> datetime (ET, early closes included)

Each session is one file, sessions/YYYY-MM-DD_MARKET.json. A plan is written once, 30 minutes after
the open (Cboe data is 15 minutes delayed, so every pre-open snapshot exists by then), and never changed.
It is graded when that session's final bar is available. Sessions the app could not see are kept as
"missed" from the first recorded day on, so gaps are visible rather than quietly skipped.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from . import backtest, prices, strategies
from .score import grade, make_plan, summarize

log = logging.getLogger("trackrecord")
NY = ZoneInfo("America/New_York")
OPEN = time(9, 30)
FREEZE_AFTER = timedelta(minutes=30)
GIVE_UP = timedelta(days=7)          # no final bar after a week: graded as "no prices"
LOOKBACK_DAYS = 10
BACKTEST_MAX_AGE = timedelta(hours=20)


def _default_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "gexsys" / "trackrecord"


class TrackRecordComponent:
    name = "trackrecord"

    def __init__(self, pre_open: Callable[[date], dict], is_trading_day: Callable[[date], bool],
                 session_close: Callable[[date], datetime], store_dir: Optional[Path] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc), source=prices,
                 proof_url: Optional[str] = None):
        self.pre_open, self.is_trading_day, self.session_close, self.clock = pre_open, is_trading_day, session_close, clock
        self.dir = Path(store_dir) if store_dir else _default_dir()
        self.cache_dir: Optional[Path] = None          # where the (recomputable) backtest is cached; default self.dir
        self.src = source
        self.proof_url = proof_url
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._daily: dict[str, tuple[datetime, dict]] = {}

    # ---------------------------------------------------------------- storage
    def _path(self, d: date, market: str) -> Path:
        return self.dir / "sessions" / f"{d.isoformat()}_{market}.json"

    def _write(self, path: Path, obj: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
        tmp.replace(path)

    def _read(self, path: Path) -> Optional[dict]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def sessions(self) -> list[dict]:
        out = [s for s in map(self._read, sorted((self.dir / "sessions").glob("*.json"))) if s]
        return sorted(out, key=lambda s: (s["session"], s["market"]), reverse=True)

    def _started(self) -> Optional[str]:
        firsts = [s["session"] for s in self.sessions() if s.get("plan")]
        return min(firsts) if firsts else None

    # ---------------------------------------------------------------- prices
    def _daily_bars(self, underlying: str, now: datetime, fresh_after: Optional[datetime] = None) -> dict:
        """Cached 30 minutes; refetched when the cached copy is older than fresh_after (a partial day's bar)."""
        got = self._daily.get(underlying)
        if not got or now - got[0] > timedelta(minutes=30) or (fresh_after and got[0] < fresh_after):
            got = (now, self.src.daily(underlying, since=date.today() - timedelta(days=30)))
            self._daily[underlying] = got
        return got[1]

    def session_bar(self, underlying: str, d: date, now: datetime) -> Optional[dict]:
        """The final open/high/low/close of session d, or None while it is not final yet."""
        close = self.session_close(d)
        if now < close + timedelta(minutes=20):                 # 15-minute delayed data needs time to settle
            return None
        if now.astimezone(NY).date() == d:                       # same evening: Cboe's 1-minute bars
            b = self.src.intraday(underlying)
            if b and b["date"] == d.isoformat() and b.get("last", "") >= (close - timedelta(minutes=1)).astimezone(NY).strftime("%H:%M"):
                return b
        return self._daily_bars(underlying, now, fresh_after=close + timedelta(minutes=20)).get(d.isoformat())

    # ---------------------------------------------------------------- freezing and grading
    def tick(self) -> list[str]:
        """Freeze every plan that is due, grade every plan whose session is final. Returns what changed."""
        changed = []
        with self._lock:
            now = self.clock()
            today = now.astimezone(NY).date()
            started = self._started()
            for back in range(LOOKBACK_DAYS, -1, -1):
                d = today - timedelta(days=back)
                if not self.is_trading_day(d) or now < datetime.combine(d, OPEN, NY) + FREEZE_AFTER:
                    continue
                for m, inp in (self._pre_open(d) or {}).items():
                    p = self._path(d, m)
                    if p.exists():
                        continue
                    plan = make_plan(inp, d.isoformat(), now.isoformat()) if inp else None
                    if plan:
                        self._write(p, {"session": d.isoformat(), "market": m, "status": "pending", "plan": plan, "outcome": None})
                        changed.append(f"{d}_{m} frozen")
                    elif started and d.isoformat() > started:
                        self._write(p, {"session": d.isoformat(), "market": m, "status": "missed", "plan": None, "outcome": None,
                                        "why": "no GEX PRO calculation from before this session's open was saved"})
                        changed.append(f"{d}_{m} missed")
            for s in self.sessions():
                if s.get("status") != "pending":
                    continue
                d = date.fromisoformat(s["session"])
                bar = self.session_bar(s["plan"].get("underlying") or "", d, now)
                if bar:
                    s.update(status="graded", outcome=grade(s["plan"], bar), graded_at=now.isoformat())
                elif now > self.session_close(d) + GIVE_UP:
                    s.update(status="no_prices", why="no final price bar found for this session")
                else:
                    continue
                self._write(self._path(d, s["market"]), s)
                changed.append(f"{d}_{s['market']} {s['status']}")
        return changed

    def _pre_open(self, d: date) -> dict:
        try:
            return self.pre_open(d)
        except Exception:
            log.exception("pre-open levels for %s failed", d)
            return {}

    # ---------------------------------------------------------------- backtest (rebuilt about once a day)
    def backtest(self) -> dict:
        path = (self.cache_dir or self.dir) / "backtest.json"
        cached = self._read(path)
        now = self.clock()
        if cached and "strategy_lab" in cached and now - datetime.fromisoformat(cached["built"]) < BACKTEST_MAX_AGE:
            return cached                                       # (a cache from before the lab existed is rebuilt)
        today = now.astimezone(NY).date()
        final = today.isoformat() if now >= self.session_close(today) + timedelta(minutes=20) else (today - timedelta(days=1)).isoformat()
        out = {"built": now.isoformat(), "markets": {}}
        lab = {}
        for market, und in (("ES", "SPX"), ("NQ", "NDX")):
            try:
                bars = self.src.daily(und, since=date(1990, 1, 1))
                vol = self.src.vol_index(und)
                r = backtest.run(und, prices.VOL_INDEX[und], bars, vol, until=final) if bars and vol else None
                lab[und] = {"bars": bars, "vol": vol, "hourly": {d: v for d, v in self.src.hourly(und).items() if d <= final}}
            except Exception:
                log.exception("backtest %s failed", und)
                r = None
            if r:
                out["markets"][market] = r
        try:                                                    # the futures strategy lab (see strategies.py)
            if len(lab) == 2:
                lab["term"] = {"VIX": self.src.vol_index("SPX"), "VIX3M": self.src.cboe_index("VIX3M"), "VIX9D": self.src.cboe_index("VIX9D")}
                lab["vixh"] = self.src.vix_hourly()
                if lab["term"]["VIX3M"]:
                    out["strategy_lab"] = dict(strategies.study(lab, final), built=now.isoformat(),
                                               gex=strategies.gex_forward(self.sessions(), {u: lab[u]["hourly"] for u in ("SPX", "NDX")}))
        except Exception:
            log.exception("strategy lab failed")
        if not out["markets"] and cached:
            return cached                                       # keep the last good backtest when sources fail
        if "strategy_lab" not in out and cached and cached.get("strategy_lab"):
            out["strategy_lab"] = cached["strategy_lab"]        # and the last good strategy lab
        if out["markets"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
        return out

    def payload(self) -> dict:
        ss = self.sessions()
        graded = [s for s in ss if s.get("status") == "graded"]
        markets = sorted({s["market"] for s in ss})
        return {"now": self.clock().isoformat(), "started": self._started(), "proof_url": self.proof_url,
                "rules": {"touch_em": 0.05, "min_sample": 20, "freeze": "levels from the last calculation timestamped before 09:30 ET"},
                "stats": dict({m: summarize([s for s in graded if s["market"] == m]) for m in markets}, ALL=summarize(graded)),
                "sessions": ss, "backtest": self.backtest()}

    # ---------------------------------------------------------------- component contract
    def routes(self) -> dict:
        def get(q):
            self.tick()
            return 200, self.payload()
        return {"/api/trackrecord": get}

    def start(self) -> None:
        def loop():
            while not self._stop.is_set():
                try:
                    self.tick()
                    self.backtest()
                except Exception:
                    log.exception("track record check failed")
                self._stop.wait(600)
        self._thread = threading.Thread(target=loop, daemon=True, name="trackrecord")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def build_static(self, data: Path, state: Path) -> dict:
        self.dir = Path(os.environ.get("GEXPRO_TRACK_DIR") or state / "trackrecord")
        self.cache_dir = state / "trackrecord-cache"      # kept by the workflow's cache, not in the git branch
        repo = os.environ.get("GITHUB_REPOSITORY")
        if repo and not self.proof_url:
            self.proof_url = f"https://github.com/{repo}/commits/track-record"
        self.tick()
        data.mkdir(parents=True, exist_ok=True)
        p = self.payload()
        (data / "trackrecord.json").write_text(json.dumps(p), encoding="utf-8")
        return {}
