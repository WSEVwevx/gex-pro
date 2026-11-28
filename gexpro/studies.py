"""The Backtesting tab's studies (Phases 2-6) as one file: data/studies.json on the hosted site, /api/studies locally.

The three studies (gexpro/reaction_lab.py, gexpro/splits.py, gexpro/rules.py) take a few seconds together, and their
inputs change at most a few times a day, so the result is recomputed only when a key changes: the track-record and
archive branch heads, the definition files and the study code. Otherwise the copy saved in the state folder is reused.
A failed run keeps the last good result and says so (with its own computed-at time); nothing is shown as newer than
it is.

What the page shows per market:
  verdict       "no proven edge yet", unless a study has evidence, each named with its direction: a level type whose
                interval excludes 0 and whose p-value survives Benjamini-Hochberg (q = 0.10) across that market's tested
                level types; a split that survives its own Benjamini-Hochberg; a rule whose interval excludes 0 with a
                p-value below 0.05 after adjusting for every try.
  needs         per study: sessions it has, sessions it needs and the date that is reached at today's rate (trading
                days from marketcal, after the last data day). The rates (best case, all labelled estimates):
                  level reaction  per level type: 20 x the sessions that have that level / its touches; the smallest
                                  (every session has every level type now: the 9:30 pastes, which give C1-C3 and
                                  P1-P3, started after the track record did, so have and need count the sessions
                                  with that level)
                  splits          per split: 20 x the market's sessions / its smallest group; the smallest
                (the date is the (need - have)-th trading day after the last data day)
                  rules           20 training sessions + 30 / (counted touches per track-record session)
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from gexsys import marketcal

from . import reaction_lab as L
from . import rules as R
from . import splits as S

log = logging.getLogger("gexpro.studies")
CODE = ["reaction_lab.py", "splits.py", "rules.py", "uncertainty.py", "studies.py"]
DEFS = {"level_reaction": L.DEFINITION, "splits": S.DEFINITION, "rules": R.DEFINITION}
SHIFT_UP, SHIFT_DOWN = {"NQ": 5.0, "ES": 1.0}, {"NQ": -5.0, "ES": -1.0}
SPLIT_LABEL = {"regime": "gamma regime", "zg_distance": "distance from zero gamma", "vol_tercile": "VIX / VXN third",
               "event_day": "event day", "weekday": "weekday", "opex_week": "opex week", "zero_dte_tercile": "0DTE share third"}


# ---------------------------------------------------------------- cache key
def key() -> str:
    """Branch heads, the build's own commit (any code the studies call), definitions and study code: any change
    recomputes."""
    git = lambda *a: subprocess.run(["git", *a], cwd=L.ROOT, capture_output=True, text=True).stdout.strip()
    git("fetch", "-q", "origin", "track-record", "archive")
    h = hashlib.sha256()
    for part in (git("rev-parse", "origin/track-record"), git("rev-parse", "origin/archive"), git("rev-parse", "HEAD")):
        h.update(part.encode())
    for p in [*DEFS.values(), R.TRIES, *(Path(__file__).parent / f for f in CODE)]:
        h.update(p.read_bytes())
    for p in sorted(R.BACKFILL.glob("*/*.json")):                 # backfilled bars (committed, so also in HEAD)
        h.update(p.name.encode() + p.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------- sample needed
def trading_days_after(d: str, n: int) -> str:
    day, k = date.fromisoformat(d), 0
    while k < n:
        day += timedelta(days=1)
        k += marketcal.is_trading_day(day)
    return day.isoformat()


def need_row(study: str, have: int, need: Optional[int], last: str, basis: str) -> dict:
    row = {"study": study, "have": have, "need": need, "basis": basis}
    if need is not None:
        row["reached"] = have >= need
        row["est_date"] = None if have >= need else trading_days_after(last, need - have)
    return row


def needs(m: str, lab_rows: list[dict], split_tests: list[dict], sessions: int, touches_per_session: Optional[float],
          archive_sessions: int, last: str, d_rules: dict) -> list[dict]:
    lvl = [(math.ceil(20 * r["all"]["sessions"] / r["all"]["touches"]) - r["all"]["sessions"], r) for r in lab_rows
           if r["all"]["touches"]]
    _, r = min(lvl, key=lambda x: x[0]) if lvl else (None, None)
    out = [need_row("level_reaction", r["all"]["sessions"] if r else sessions,
                    math.ceil(20 * r["all"]["sessions"] / r["all"]["touches"]) if r else None, last,
                    f"nearest level type {r['type']}: 20 touches at {r['all']['touches']} in its {r['all']['sessions']} sessions"
                    if r else "no level touched yet")]
    sp = []
    for t in split_tests:
        g = [v["sessions"] for v in t["groups"].values()]
        if min(g) > 0:
            sp.append((math.ceil(20 * sessions / min(g)), t))
    n, t = min(sp, key=lambda x: x[0]) if sp else (None, None)
    out.append(need_row("splits", sessions, n, last, f"nearest split {SPLIT_LABEL.get(t['split'], t['split'])}: 20 sessions in its smallest group; "
                        f"the other {len(split_tests) - 1} need as long or longer" if t
                        else "every split has an empty group"))
    k0, oos = d_rules["walk_forward"]["min_train_sessions"], d_rules["min_oos_trades"]
    n = k0 + math.ceil(oos / touches_per_session) if touches_per_session else None
    out.append(need_row("rules", archive_sessions, n, last,
                        f"sessions with 1-minute futures bars: {k0} to train + {oos} trades at {touches_per_session:.2f} "
                        f"touches per session (best case)"
                        if touches_per_session else "no level touched yet"))
    return out


# ---------------------------------------------------------------- the page's file
def _lab_row(r: dict, up: dict, down: dict) -> dict:
    c, keep = r["all"], ("sessions", "touches", "small", "reject", "baseline", "difference", "interval", "interval_method",
                         "p_value", "sessions_needed_80pct", "headline", "unavailable")
    row = {"type": r["type"], **{k: c[k] for k in keep if k in c}}
    nr = r["no_roll_weeks"]
    row["no_roll_weeks"] = {"touches": nr["touches"], "difference": nr.get("difference")}
    row["shifted"] = {f"{SHIFT_UP[r['market']]:+g}": up.get("difference"), f"{SHIFT_DOWN[r['market']]:+g}": down.get("difference")}
    return row


def payload(lab: dict, splits: dict, rules: dict, sessions: list[dict], archive_days: dict[str, int]) -> dict:
    main, d_rules = lab["main"], R.definition()[0]
    alt = {k: {(x["market"], x["type"]): x["all"] for x in lab[k]["table"]} for k in ("shift_up", "shift_down")}
    out = {"computed_at": datetime.now(timezone.utc).isoformat(), "hypothetical": True,
           "definitions": {"level_reaction": main["definition_sha256"], "splits": splits["definition_sha256"],
                           "rules": rules["definition_sha256"]},
           "seed": main["seed"], "markets": {}}
    for m in R.MARKETS:
        ss = [s for s in sessions if s["market"] == m]
        rows = [x for x in main["table"] if x["market"] == m]
        tests = [t for t in splits["tests"] if t["market"] == m]
        rm = rules["markets"].get(m, {})
        last = max((s["session"] for s in ss), default=None)
        touches = sum(x["all"]["touches"] for x in rows)
        lab_rows = [_lab_row(x, alt["shift_up"].get((m, x["type"]), {}), alt["shift_down"].get((m, x["type"]), {})) for x in rows]
        tested = {r["type"]: r["p_value"] for r in lab_rows if r.get("interval") and r.get("p_value") is not None}
        keep, excl = S.bh(tested), lambda iv: not (iv[0] <= 0 <= iv[1])
        edge = [f"level {r['type']}: {'more' if r['difference'] > 0 else 'fewer'} rejections than random levels"
                for r in lab_rows if r["type"] in keep and excl(r["interval"])]
        edge += [f"split {t['split']}: the groups differ" for t in tests if t.get("survives")]
        e = (rm.get("per_trade") or {}).get("r") or {}
        if e.get("interval") and excl(e["interval"]) and (rm.get("p_adjusted") or 1) < 0.05:
            edge.append(f"rule {rules['rule']}: {'gains' if e['mean'] > 0 else 'loses'} out of sample (hypothetical)")
        out["markets"][m] = {
            "sessions": len(ss), "data_from": min((s["session"] for s in ss), default=None), "data_through": last,
            "archive_sessions": archive_days.get(m, 0), "roll_week_sessions": sum(s["roll_week"] for s in ss),
            "verdict": {"edge": edge, "text": ("evidence: " + "; ".join(edge)) if edge else f"no proven edge yet ({len(ss)} sessions)"},
            "counts": {"level_types": len(rows), "level_types_20": sum(not x["all"].get("small") for x in rows),
                       "splits_registered": len(tests), "splits_tested": sum(t["status"] == "tested" for t in tests),
                       "oos_trades": rm.get("oos_trades", 0), "oos_needed": d_rules["min_oos_trades"]},
            "needs": needs(m, rows, tests, len(ss), touches / len(ss) if ss and touches else None,
                           archive_days.get(m, 0), last, d_rules) if last else [],
            "level_reaction": lab_rows,
            "splits": [{k: t[k] for k in ("split", "status", "groups", "unavailable", "p_value", "survives", "verdict",
                                           "named_events") if k in t} for t in tests],
            "rules": rm}
    out["studies"] = {
        "level_reaction": {"version": main["version"], "sha256": main["definition_sha256"], "data_through": main["data_through"],
                           "baseline_per_type": main["baseline_per_type"], "reps": main["bootstrap_reps"]},
        "splits": {"version": splits["version"], "sha256": splits["definition_sha256"], "registered": splits["registered"],
                   "tested": splits["tested"], "survivors": splits["survivors"], "q": splits["q"], "permutations": splits["permutations"]},
        "rules": {"rule": rules["rule"], "version": rules["version"], "sha256": rules["definition_sha256"], "tries": rules["tries"],
                  "fees_round_turn_usd": rules["fees_round_turn_usd"], "grid_points": d_rules["grid"]["points"],
                  "min_train_sessions": d_rules["walk_forward"]["min_train_sessions"], "min_oos_trades": d_rules["min_oos_trades"],
                  "data_from": rules["data_from"], "data_through": rules["data_through"],
                  "backfilled_from": min(rules["backfilled"], default=None), "backfilled_through": max(rules["backfilled"], default=None)}}
    return out


def compute() -> dict:
    from trackrecord import prices
    sessions = L.load()
    lab = {"main": L.run(sessions), "shift_up": L.run(sessions, SHIFT_UP), "shift_down": L.run(sessions, SHIFT_DOWN)}
    rules_def = L.definition()[0]["rules"]
    real = lab["main"]["levels"]
    rand = L.baseline(sessions, real, rules_def, L.DRAWS, L.SEED)
    cals, shares = S.read_archive()
    closes = {m: prices.vol_index(u) for m, u in S.VOL.items()}
    if not all(closes.values()):                     # never cache a split result built on a failed download
        raise RuntimeError("the VIX / VXN history did not download (Yahoo)")
    sp = S.run(sessions, S.counts(real, rand), closes, cals, {m: S.dte_labels(v) for m, v in shares.items()})
    bars = R.read_bars()
    ru = R.run(sessions, bars)
    days = {m: sum(1 for (_, mm) in bars if mm == m) for m in R.MARKETS}
    return payload(lab, sp, ru, sessions, days)


def current(state: Path) -> dict:
    """The saved result when its key still matches, else a fresh run (a failure keeps the last good one, flagged)."""
    f = state / "studies.json"
    try:
        old = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    try:
        k = key()
        if old and old.get("key") == k and not old.get("error"):
            return old
        res = dict(compute(), key=k)
    except Exception as e:                                       # keep the last good result, and say why it is old
        log.exception("studies failed")
        msg = f"{type(e).__name__}: {e}"[:300]
        return dict(old, error=msg) if old else {"unavailable": f"the studies could not run: {msg}"}
    state.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(res), encoding="utf-8")
    return res


class StudiesComponent:
    name = "studies"

    def __init__(self, state: Optional[Path] = None) -> None:
        self.state = state or Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "gexsys"

    def routes(self) -> dict:
        return {"/api/studies": lambda q: (200, current(self.state))}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def build_static(self, data: Path, state: Path) -> dict:
        self.state = state
        data.mkdir(parents=True, exist_ok=True)
        (data / "studies.json").write_text(json.dumps(current(state)), encoding="utf-8")
        return {}

    def sources(self) -> list:
        """One Data health row, read from the saved result (never recomputed here)."""
        try:
            x = json.loads((self.state / "studies.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            x = None
        row = {"name": "Backtesting studies", "provider": "GEX PRO (track record, archive, Yahoo VIX / VXN)",
               "pages": ["Backtesting"], "fresh_h": 72,
               "detail": "recomputed when the track record, the archive or a study definition changes"}
        if not x:
            return [dict(row, last_ok=None, error=None, note="runs the first time the Backtesting page loads")]
        return [dict(row, last_ok=x.get("computed_at"), error=x.get("error") or x.get("unavailable"))]
