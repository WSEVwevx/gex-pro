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

The record is kept forever, apart from the snapshots (which are pruned after 12 days):
  sessions/*.json   one file per session, never deleted
  pastes/*.txt      the TradingView paste as it stood at each session's 09:30 open (for backtesting), never changed
  minutes/*.json    each graded session's 1-minute futures bars (09:30-16:00), for the level reaction stats
                    (see reactions.py); saved within a few days of the close, as the free source keeps ~30 days
  history.csv       every session in one permanent table, rewritten whenever a session changes
  public copy       the hosted site commits the folder to the repository's track-record branch, so it
                    keeps growing on GitHub while this PC is off; the local app copies in every session
                    it is missing from that public record (mirror(), hourly)
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from . import backtest, prices, reactions, weeks
from .score import grade, make_plan, summarize

log = logging.getLogger("trackrecord")
NY = ZoneInfo("America/New_York")
OPEN = time(9, 30)
FREEZE_AFTER = timedelta(minutes=30)
GIVE_UP = timedelta(days=7)          # no final bar after a week: graded as "no prices"
LOOKBACK_DAYS = 10
MINUTES_KEPT_BY_SOURCE = timedelta(days=28)    # Yahoo serves 1-minute bars for about 30 days
BACKTEST_MAX_AGE = timedelta(hours=20)
MIRROR_URL = "https://wsevwevx.github.io/gex-pro/data/trackrecord.json"      # the public record ($GEXPRO_TRACK_MIRROR)
HISTORY_COLUMNS = ["session", "market", "status", "data_asof", "frozen_at", "ref", "em", "regime", "zero_gamma", "call_wall",
                   "put_wall", "abs_gamma", "bias", "target", "open", "high", "low", "close", "move_em", "close_in_band",
                   "range_in_band", "call_wall_result", "put_wall_result", "bias_right", "graded_at", "note"]


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

    def _paste_path(self, d: date, market: str) -> Path:
        return self.dir / "pastes" / f"{d.isoformat()}_{market}.txt"

    def _minutes_path(self, d: date, market: str) -> Path:
        return self.dir / "minutes" / f"{d.isoformat()}_{market}.json"

    def pastes(self) -> list[dict]:
        """Every saved 9:30 paste, newest first: [{"session", "market", "paste"}]."""
        out = []
        for f in sorted((self.dir / "pastes").glob("*.txt"), reverse=True):
            day, _, m = f.stem.partition("_")
            try:
                out.append({"session": day, "market": m, "paste": f.read_text(encoding="utf-8").strip()})
            except OSError:
                continue
        return out

    def pastes_payload(self) -> dict:
        """The Backtesting page: every day's 9:30 paste, and each week's as one paste (trackrecord/weeks.py)."""
        ps = self.pastes()
        return {"pastes": ps, "weeks": weeks.weeks(ps)}

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

    # ---------------------------------------------------------------- the permanent table
    @staticmethod
    def _wall(w) -> str:
        return "" if not w else "held" if w.get("held") else "broke" if w.get("touched") else "not reached"

    def history_rows(self) -> list[list]:
        rows = []
        for s in sorted(self.sessions(), key=lambda s: (s["session"], s["market"])):
            p, o = s.get("plan") or {}, s.get("outcome") or {}
            yn = lambda v: "" if v is None else ("yes" if v else "no")
            rows.append([s["session"], s["market"], s.get("status", ""), p.get("asof", ""), p.get("frozen_at", ""), p.get("ref", ""),
                         p.get("em", ""), p.get("regime", ""), p.get("zg", ""), p.get("cw", ""), p.get("pw", ""), p.get("ag", ""),
                         p.get("bias", ""), p.get("target", ""), o.get("open", ""), o.get("high", ""), o.get("low", ""), o.get("close", ""),
                         o.get("move_em", ""), yn(o.get("em_close")), yn(o.get("em_range")), self._wall(o.get("cw")), self._wall(o.get("pw")),
                         yn(o.get("bias_hit")), s.get("graded_at", ""), s.get("why", "")])
        return rows

    def write_history(self) -> Path:
        """history.csv: every session ever recorded, oldest first (opens in Excel / Google Sheets)."""
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(HISTORY_COLUMNS)
        w.writerows(self.history_rows())
        path = self.dir / "history.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != buf.getvalue():
            tmp = path.with_suffix(".tmp")
            tmp.write_text(buf.getvalue(), encoding="utf-8")
            tmp.replace(path)
        return path

    # ---------------------------------------------------------------- copy in what the public record has
    def mirror(self, url: Optional[str] = None, fetch: Optional[Callable[[str], bytes]] = None) -> list[str]:
        """Copy sessions from the public record (the hosted site, which runs on GitHub while this PC is
        off). A session this app already graded is never replaced; a missing, missed, pending or
        no-prices one takes the public version. Returns what was copied."""
        url = url or os.environ.get("GEXPRO_TRACK_MIRROR") or MIRROR_URL
        if not url or url == "off":
            return []
        def get(u):
            req = urllib.request.Request(u, headers={"User-Agent": "GEX PRO track record"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read()
        try:
            remote = json.loads((fetch or get)(url)).get("sessions") or []
        except Exception as e:
            log.warning("track record mirror %s failed: %s", url, e)
            return []
        copied = []
        with self._lock:
            for s in remote:
                try:
                    d, m = date.fromisoformat(s["session"]), s["market"]
                except (KeyError, ValueError, TypeError):
                    continue
                path = self._path(d, m)
                mine = self._read(path) if path.exists() else None
                if mine and mine.get("status") == "graded":
                    continue
                if mine and s.get("status") not in ("graded", "pending"):
                    continue                                    # a public miss never replaces anything here
                if mine and mine.get("status") == s.get("status") and mine.get("plan") == s.get("plan"):
                    continue
                self._write(path, dict(s, mirrored_from=url))
                copied.append(f"{d}_{m} {s.get('status')}")
        try:
            for x in json.loads((fetch or get)(url.replace("trackrecord.json", "pastes.json"))).get("pastes") or []:
                d, m, text = date.fromisoformat(x["session"]), str(x["market"]), str(x["paste"])
                if m.isalnum() and text.startswith("GEX1;") and not self._paste_path(d, m).exists():
                    self._paste_path(d, m).parent.mkdir(parents=True, exist_ok=True)
                    self._paste_path(d, m).write_text(text, encoding="utf-8")
                    copied.append(f"{d}_{m} paste")
        except Exception as e:
            log.warning("track record pastes mirror failed: %s", e)
        if copied:
            self.write_history()
        return copied

    def _started(self) -> Optional[str]:
        firsts = [s["session"] for s in self.sessions() if s.get("plan")]
        return min(firsts) if firsts else None

    # ---------------------------------------------------------------- prices
    def _daily_bars(self, underlying: str, now: datetime, fresh_after: Optional[datetime] = None) -> dict:
        """Cached 30 minutes; refetched when the cached copy is older than fresh_after (a partial day's bar)."""
        got = self._daily.get(underlying)
        if not got or now - got[0] > timedelta(minutes=30) or (fresh_after and got[0] < fresh_after):
            got = (now, self.src.daily(underlying, since=now.astimezone(NY).date() - timedelta(days=30)))
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
                    if inp and inp.get("paste") and not self._paste_path(d, m).exists():
                        self._paste_path(d, m).parent.mkdir(parents=True, exist_ok=True)
                        self._paste_path(d, m).write_text(inp["paste"], encoding="utf-8")
                        changed.append(f"{d}_{m} paste")
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
            if changed or not (self.dir / "history.csv").exists():
                self.write_history()
        changed += self.save_minutes()
        return changed

    # ---------------------------------------------------------------- level reactions
    def save_minutes(self) -> list[str]:
        """Save the 1-minute futures bars of every graded session that has none yet, while the free source
        still has them (it keeps about 30 days). One try per session per hour; a failure just waits."""
        now, done = self.clock(), []
        tried = getattr(self, "_minutes_tried", {})
        self._minutes_tried = tried
        for s in self.sessions():
            if s.get("status") != "graded" or s["market"] not in reactions.FUTURES:
                continue
            d = date.fromisoformat(s["session"])
            path = self._minutes_path(d, s["market"])
            key = path.name
            if path.exists() or not hasattr(self.src, "minutes") or now.timestamp() - tried.get(key, 0) < 3600:
                continue
            tried[key] = now.timestamp()
            try:
                rec = self.src.minutes(s, recent=now - datetime.combine(d, OPEN, NY) <= MINUTES_KEPT_BY_SOURCE,
                                       end=reactions.session_minutes(self.session_close(d)))
            except Exception as e:
                log.warning("1-minute bars for %s failed: %s", key, e)
                continue
            if rec and len(rec["bars"]) >= 0.75 * rec["close_min"]:   # a full session (early closes included), not a partial download
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(rec, separators=(",", ":")), encoding="utf-8")
                done.append(f"{d}_{s['market']} minutes")
        return done

    def reaction_stats(self) -> Optional[dict]:
        """The level reaction study over every saved session (cached until a session is added)."""
        files = sorted((self.dir / "minutes").glob("*.json"))
        sig = [f.name for f in files] + [f.name for f in sorted((self.dir / "pastes").glob("*.txt"))]
        if getattr(self, "_rx", None) and self._rx[0] == sig:
            return self._rx[1]
        recs, levels = [], {}
        plans = {(s["session"], s["market"]): s["plan"] for s in self.sessions() if s.get("plan")}
        for f in files:
            rec = self._read(f)
            key = (rec or {}).get("session"), (rec or {}).get("market")
            if not rec or key not in plans:
                continue
            pp = self._paste_path(date.fromisoformat(key[0]), key[1])
            recs.append(rec)
            levels[key] = reactions.session_levels(plans[key], pp.read_text(encoding="utf-8") if pp.exists() else None)
        out = reactions.summarize(reactions.observations(recs, levels)) if recs else None
        if out:                                                 # how far back each kind of level goes
            out["since"] = min(r["session"] for r in recs)
            full = [r["session"] for r in recs if self._paste_path(date.fromisoformat(r["session"]), r["market"]).exists()]
            out["full_since"] = min(full) if full else None
        self._rx = (sig, out)
        return out

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
        if cached and "strategy_lab" not in cached and all("levels" in m for m in cached["markets"].values()) and now - datetime.fromisoformat(cached["built"]) < BACKTEST_MAX_AGE:
            return cached                                       # (an old cache that still holds the removed strategy lab is rebuilt)
        today = now.astimezone(NY).date()
        final = today.isoformat() if now >= self.session_close(today) + timedelta(minutes=20) else (today - timedelta(days=1)).isoformat()
        out = {"built": now.isoformat(), "markets": {}}
        for market, und in (("ES", "SPX"), ("NQ", "NDX")):
            try:
                bars = self.src.daily(und, since=date(1990, 1, 1))
                vol = self.src.vol_index(und)
                r = backtest.run(und, prices.VOL_INDEX[und], bars, vol, until=final) if bars and vol else None
            except Exception:
                log.exception("backtest %s failed", und)
                r = None
            if r:
                out["markets"][market] = r
        if not out["markets"] and cached:
            return cached                                       # keep the last good backtest when sources fail
        if out["markets"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
        return out

    def payload(self) -> dict:
        ss = self.sessions()
        graded = [s for s in ss if s.get("status") == "graded"]
        markets = sorted({s["market"] for s in ss})
        bt = self.backtest()
        stats = {m: summarize([s for s in graded if s["market"] == m]) for m in markets}
        stats["ALL"] = summarize(graded)
        for m, st in stats.items():                             # what plain price levels score at the walls' distances
            st["walls_held"]["baseline"] = backtest.wall_baseline([s for s in graded if m == "ALL" or s["market"] == m], bt.get("markets") or {})
        return {"now": self.clock().isoformat(), "started": self._started(), "proof_url": self.proof_url,
                "rules": {"touch_em": 0.05, "min_sample": 20, "freeze": "levels from the last calculation timestamped before 09:30 ET"},
                "stats": stats, "sessions": ss, "backtest": bt, "reactions": self.reaction_stats()}

    def sources(self) -> list:
        """The Data health page's row: sessions still waiting for a final price 3 hours after the close, or
        given up on (no_prices) in the last 10 days."""
        now = self.clock()
        ss = self.sessions()
        waiting = [s for s in ss if s.get("status") == "pending"
                   and now > self.session_close(date.fromisoformat(s["session"])) + timedelta(hours=3)]
        recent = (now - timedelta(days=10)).date().isoformat()
        lost = [s for s in ss if s.get("status") == "no_prices" and s["session"] >= recent]
        graded = [s["graded_at"] for s in ss if s.get("graded_at")]
        why = ([f"{len(waiting)} session(s) past the close still waiting for a final price"] if waiting else []) + \
              ([f"{len(lost)} session(s) could not be graded: no final price was found"] if lost else [])
        return [{"name": "Closing prices for grading", "provider": "Cboe (same evening), Yahoo Finance (daily)",
                 "pages": ["Track record"], "last_ok": max(graded, default=None), "error": "; ".join(why) or None}]

    # ---------------------------------------------------------------- component contract
    def routes(self) -> dict:
        def get(q):
            self.tick()
            return 200, self.payload()
        return {"/api/trackrecord": get, "/api/pastes": lambda q: (200, self.pastes_payload())}

    def start(self) -> None:
        def loop():
            last_mirror = 0.0
            while not self._stop.is_set():
                try:
                    if datetime.now(timezone.utc).timestamp() - last_mirror > 3600:
                        last_mirror = datetime.now(timezone.utc).timestamp()
                        self.mirror()
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
        (data / "pastes.json").write_text(json.dumps(self.pastes_payload()), encoding="utf-8")
        return {}
