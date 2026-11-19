"""Walk-forward rule tester (Phase 6): hypothetical trades from a written rule, scored out of sample only.

The rule, its fills and its grid are fixed in studies/rules/fade_first_touch_v1.json, written before any trade was
computed; every rule version ever run is listed in studies/rules/tries.json, and p-values are also shown adjusted for
that many tries. No order is ever placed: every trade here is hypothetical.

  sessions   graded track-record plans (levels, expected move, 09:30 ratio: read by gexpro/reaction_lab.py) joined
             with the archive's futures 1-minute bars of the same day ({M}F-1m.json), RTH only (marketcal).
  trigger    the level-reaction touch (studies/level_reaction/v2.json), found on the archive bars.
  fills      entry at the next bar's open, stop and target 1 tick against us, stop first inside one bar, flat by the
             close; points and R before fees, dollars per 1 contract after fees.
  walk-fwd   expanding window per market: the grid point with the best in-sample mean net dollars per trade over
             sessions 1..k trades session k+1; only those sessions are scored.
  report     under 30 out-of-sample trades: "not enough data" with the counts and nothing else.
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import date
from pathlib import Path
from typing import Optional

from gexsys import marketcal

from . import reaction_lab as L
from . import uncertainty as U

DEFINITION = L.ROOT / "studies" / "rules" / "fade_first_touch_v1.json"
TRIES = L.ROOT / "studies" / "rules" / "tries.json"
ARCHIVE = "origin/archive"
MARKETS = ("NQ", "ES")
SHIFT = {"NQ": 5.0, "ES": 1.0}                 # the measured overnight basis miss, in futures points


def definition(path: Path = DEFINITION) -> tuple[dict, str]:
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def grid(d: dict) -> list[dict]:
    g = d["grid"]
    return [{"s": s, "t": t, "T": T} for s in g["s"] for t in g["t"] for T in g["T"]]


def tries(path: Path = TRIES) -> int:
    """Every grid point of every rule version run to date."""
    return sum(x["grid_points"] for x in json.loads(path.read_text(encoding="utf-8"))["tries"])


# ---------------------------------------------------------------- inputs
def rth_bars(raw: dict, day: date) -> list[list[float]]:
    """[minute after 09:30, open, high, low, close] for the bars starting in [09:30, close) ET of that day."""
    o, c = marketcal.rth_open_dt(day).timestamp(), marketcal.rth_close_dt(day).timestamp()
    return [[int((b[0] - o) // 60), b[1], b[2], b[3], b[4]] for b in raw["bars"]
            if o <= b[0] < c and None not in b[1:5]]


def join(track: list[dict], bars: dict[tuple[str, str], dict], skipped: Optional[list] = None) -> list[dict]:
    """Track-record sessions that have archive bars, with those bars (OHLC, RTH) and the archive's roll-week flag."""
    skipped = [] if skipped is None else skipped
    out = []
    for s in track:
        raw = bars.get((s["session"], s["market"]))
        if raw is None:
            skipped.append(f"{s['session']}_{s['market']}: no archive bars")
            continue
        ohlc = rth_bars(raw, date.fromisoformat(s["session"]))
        if not ohlc:
            skipped.append(f"{s['session']}_{s['market']}: no RTH bars in the archive file")
            continue
        out.append(dict(s, ohlc=ohlc, bars=[[b[0], b[2], b[3], b[4]] for b in ohlc], roll_week=bool(raw.get("roll_week"))))
    return out


# ---------------------------------------------------------------- one session
def triggers(s: dict, rules: dict, shift: float = 0.0) -> list[dict]:
    """The session's touches (non-dependent), in time order, ties in the level-type order; "px" is the exact level
    (the lab's "level" is rounded to 2 decimals for display)."""
    rows = [dict(r, px=s["levels"][r["type"]] + shift) for r in L.session_levels(s, rules, shift)
            if r["cat"] == "touch" and not r.get("dependent")]
    return sorted(rows, key=lambda r: (r["minute"], L.TYPES.index(r["type"])))


def trade(s: dict, trig: dict, p: dict, rules: dict, d: dict, fees: float) -> dict:
    """One hypothetical trade, or {"skip": reason}."""
    bars, tick = s["ohlc"], d["units"]["tick"]
    tol = L.tol_of(s, rules)
    i = next(k for k, b in enumerate(bars) if b[0] == trig["minute"])
    if i + 1 >= len(bars):
        return {"skip": "no RTH bar after the trigger"}
    short = trig["side"] == "above"
    sg = -1 if short else 1                                 # +1 long, -1 short
    lv, e_bar = trig["px"], bars[i + 1]
    entry = e_bar[1] + sg * tick
    stop = lv + p["s"] * tol if short else lv - p["s"] * tol
    risk = (stop - entry) * -sg
    if risk <= 0:
        return {"skip": "entry at or beyond the stop"}
    target = entry + sg * p["t"] * risk
    for j in range(i + 1, len(bars)):
        m, o, h, lo, c = bars[j]
        if m >= e_bar[0] + p["T"]:
            px, why = o, "time"
        elif (h >= stop) if short else (lo <= stop):
            px, why = (max(stop, o) if short else min(stop, o)), "stop"
        elif (lo <= target) if short else (h >= target):
            px, why = target, "target"
        else:
            continue
        break
    else:
        j, px, why = len(bars) - 1, bars[-1][4], "close"
    exit_ = px - sg * tick
    pts = (exit_ - entry) * sg
    return {"session": s["session"], "market": s["market"], "type": trig["type"], "side": "short" if short else "long",
            "level": lv, "entry_min": e_bar[0], "exit_min": bars[j][0], "entry": entry, "exit": exit_, "stop": stop,
            "target": target, "R": risk, "pts": pts, "r": pts / risk,
            "usd": pts * d["units"]["point_value_usd"][s["market"]] - fees, "why": why, "roll_week": s["roll_week"]}


def session_trades(s: dict, p: dict, rules: dict, d: dict, fees: float, shift: float = 0.0) -> tuple[list[dict], list[str]]:
    """One grid point on one session: one position at a time (a trigger before the open trade's exit bar is skipped)."""
    out, skips, busy = [], [], -1
    for trig in triggers(s, rules, shift):
        if trig["minute"] < busy:
            continue
        t = trade(s, trig, p, rules, d, fees)
        if "skip" in t:
            skips.append(t["skip"])
            continue
        out.append(t)
        busy = t["exit_min"]
    return out, skips


# ---------------------------------------------------------------- walk-forward
def choose(train: list[list[list[dict]]]) -> int:
    """train[session][grid point] = trades; the grid point with the best mean net dollars per trade (ties and no
    trades at all: the first)."""
    best, best_v = 0, None
    for g in range(len(train[0]) if train else 0):
        ts = [t for sess in train for t in sess[g]]
        if ts:
            v = sum(t["usd"] for t in ts) / len(ts)
            if best_v is None or v > best_v:
                best, best_v = g, v
    return best


def walk_forward(sessions: list[dict], d: dict, rules: dict, fees: float, shift: float = 0.0) -> dict:
    """One market's sessions, in date order. Returns the stitched out-of-sample sessions and the skip counts."""
    G, k0 = grid(d), d["walk_forward"]["min_train_sessions"]
    per, skips = [], {}
    for s in sessions:
        row = []
        for p in G:
            ts, sk = session_trades(s, p, rules, d, fees, shift)
            row.append(ts)
            for x in sk:
                skips[x] = skips.get(x, 0) + 1
        per.append(row)
    oos = []
    for k in range(k0, len(sessions)):
        g = choose(per[:k])
        ins = [t for sess in per[:k] for t in sess[g]]
        oos.append({"session": sessions[k]["session"], "roll_week": sessions[k]["roll_week"], "grid": G[g],
                    "trained_on": k, "in_sample_r": sum(t["r"] for t in ins) / len(ins) if ins else None,
                    "trades": per[k][g]})
    return {"sessions": len(sessions), "oos": oos, "skips": skips}


# ---------------------------------------------------------------- statistics
def _mean_stat(rows: list[tuple[float, int]], reps: int, seed: int) -> dict:
    """Mean of a per-session sum over a per-session count, with the Phase 4 interval: each session is the tuple
    (sum, count, 0, 1), whose baseline rate is 0, so uncertainty.diff is exactly sum / count."""
    out = U.summarize([(v, n, 0, 1) for v, n in rows], reps, seed)
    out.pop("headline", None)                       # worded for rejection rates; the tab words its own
    if "difference" in out:
        out["mean"] = out.pop("difference")
    return out


def max_drawdown(usd: list[float]) -> float:
    peak = cum = dd = 0.0
    for x in usd:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def losing_streak(usd: list[float]) -> int:
    best = run = 0
    for x in usd:
        run = run + 1 if x < 0 else 0
        best = max(best, run)
    return best


def equity_band(per_session_usd: list[float], reps: int, seed: int) -> dict:
    """Cumulative net dollars by out-of-sample session, and the 2.5% / 97.5% band from whole-session resamples."""
    n, rng = len(per_session_usd), random.Random(seed)
    cum, curve = 0.0, []
    for x in per_session_usd:
        cum += x
        curve.append(round(cum, 2))
    paths = []
    for _ in range(reps):
        c, path = 0.0, []
        for i in rng.choices(range(n), k=n):
            c += per_session_usd[i]
            path.append(c)
        paths.append(path)
    lo, hi = [], []
    for i in range(n):
        col = sorted(p[i] for p in paths)
        lo.append(round(U._quantile(col, 0.025), 2))
        hi.append(round(U._quantile(col, 0.975), 2))
    return {"curve": curve, "lo": lo, "hi": hi, "reps": reps, "seed": seed}


def summarize(wf: dict, d: dict, n_tries: int, reps: int = U.REPS, seed: int = U.SEED) -> dict:
    oos = wf["oos"]
    trades = [t for o in oos for t in o["trades"]]
    out = {"sessions": wf["sessions"], "oos_sessions": len(oos), "oos_trades": len(trades), "skipped_triggers": wf["skips"],
           "data_through": oos[-1]["session"] if oos else None}
    need = d["min_oos_trades"]
    if len(trades) < need:
        out.update(status="not enough data", reason=f"{len(trades)} of {need} out-of-sample trades")
        return out
    usd = [t["usd"] for t in trades]
    wins, losses = [t for t in trades if t["usd"] > 0], [t for t in trades if t["usd"] <= 0]
    per = {k: _mean_stat([(sum(t[k] for t in o["trades"]), len(o["trades"])) for o in oos], reps, seed)
           for k in ("r", "pts", "usd")}
    sess = {k: _mean_stat([(sum(t[k] for t in o["trades"]), 1) for o in oos], reps, seed) for k in ("r", "usd")}
    ins = [o["in_sample_r"] for o in oos if o["in_sample_r"] is not None]
    p = per["r"].get("p_value")
    out.update(
        status="tested", per_trade=per, per_session=sess,
        p_adjusted=None if p is None else round(min(1.0, p * n_tries), 4), tries=n_tries,
        win_rate=round(len(wins) / len(trades), 4),
        avg_win={"usd": round(sum(t["usd"] for t in wins) / len(wins), 2), "r": round(sum(t["r"] for t in wins) / len(wins), 4)} if wins else None,
        avg_loss={"usd": round(sum(t["usd"] for t in losses) / len(losses), 2), "r": round(sum(t["r"] for t in losses) / len(losses), 4)} if losses else None,
        max_drawdown_usd=round(max_drawdown(usd), 2), longest_losing_streak=losing_streak(usd),
        in_sample_r=round(sum(ins) / len(ins), 4) if ins else None, out_of_sample_r=round(sum(t["r"] for t in trades) / len(trades), 4),
        equity=equity_band([sum(t["usd"] for t in o["trades"]) for o in oos], reps, seed))
    return out


# ---------------------------------------------------------------- the study
def run(track: list[dict], bars: dict, fees: Optional[float] = None, reps: int = U.REPS, seed: int = U.SEED) -> dict:
    d, sha = definition()
    rules = L.definition()[0]["rules"]
    fees = d["units"]["fees_round_turn_usd"] if fees is None else fees
    skipped: list[str] = []
    sessions = join(track, bars, skipped)
    n_tries = tries()
    res = {"study": "rules", "rule": d["rule"], "version": d["version"], "definition_sha256": sha, "seed": seed,
           "fees_round_turn_usd": fees, "tries": n_tries, "hypothetical": True, "skipped": skipped,
           "data_from": min((s["session"] for s in sessions), default=None),
           "data_through": max((s["session"] for s in sessions), default=None), "markets": {}}
    for m in MARKETS:
        ss = sorted((s for s in sessions if s["market"] == m), key=lambda s: s["session"])
        wf = walk_forward(ss, d, rules, fees)
        r = summarize(wf, d, n_tries, reps, seed)
        r["roll_week_sessions"] = sum(s["roll_week"] for s in ss)
        r["choices"] = [{"session": o["session"], "grid": o["grid"], "trained_on": o["trained_on"]} for o in wf["oos"]]
        if r["status"] == "tested":
            no_roll = dict(wf, oos=[o for o in wf["oos"] if not o["roll_week"]])
            r["without_roll_weeks"] = {k: v for k, v in summarize(no_roll, d, n_tries, reps, seed).items()
                                       if k in ("status", "reason", "oos_trades", "per_trade")}
            r["shifted"] = {}
            for sign in (1, -1):
                sw = summarize(walk_forward(ss, d, rules, fees, sign * SHIFT[m]), d, n_tries, reps, seed)
                r["shifted"][f"{sign * SHIFT[m]:+g}"] = {k: sw.get(k) for k in ("status", "oos_trades")} | (
                    {"r_per_trade": sw["per_trade"]["r"].get("mean")} if sw["status"] == "tested" else {})
        res["markets"][m] = r
    return res


def read_bars(files: Optional[dict] = None) -> dict[tuple[str, str], dict]:
    """{(date, market): the archive's futures 1-minute file}."""
    files = L.read_branch(ARCHIVE, lambda f: f.endswith(("/NQF-1m.json", "/ESF-1m.json"))) if files is None else files
    return {(f.split("/")[1], f.split("/")[2].split("F-")[0]): json.loads(b) for f, b in files.items()}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="gexpro.rules")
    ap.add_argument("--out")
    ap.add_argument("--fees", type=float, help="round-turn fees in dollars per contract (default: the definition's)")
    a = ap.parse_args(argv)
    res = run(L.load(), read_bars(), a.fees)
    print(f"rule {res['rule']} v{res['version']}  definition sha256 {res['definition_sha256']}  seed {res['seed']}  "
          f"(hypothetical; fees ${res['fees_round_turn_usd']:.2f} round turn; tries to date {res['tries']})")
    print(f"sessions with archive bars: {res['data_from']} to {res['data_through']}; left out {len(res['skipped'])}")
    for m, r in res["markets"].items():
        head = f"{m}: {r['sessions']} sessions, {r['oos_sessions']} out of sample, {r['oos_trades']} trades"
        if r["status"] != "tested":
            print(f"{head}: not enough data ({r['reason']})")
            continue
        e = r["per_trade"]
        print(f"{head}: {e['r'].get('mean')} R/trade {e['r'].get('interval')}  ${e['usd'].get('mean')}/trade  "
              f"p {e['r'].get('p_value')} (adjusted for {r['tries']}: {r['p_adjusted']})  in-sample {r['in_sample_r']} R")
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
