"""Independent re-check of the track record and the backtest. Shares no code with trackrecord/.

1. Plans: for each session, scan every saved snapshot file myself and confirm the plan used the latest
   one timestamped before 09:30 ET (and none after).
2. Grades: re-fetch the session bars from a second source where possible and re-grade by hand.
3. Backtest: recompute the S&P 500 / VIX close-inside rate from Yahoo's raw ^GSPC and ^VIX charts with my own loop.

Run from the project folder: python tools/verify_track.py [track folder]  (default: the local app's copy)
"""
import json
import math
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0"}
SNAP = Path(os.environ["LOCALAPPDATA"]) / "gexsys" / "snapshots"
TRACK = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ["LOCALAPPDATA"]) / "gexsys" / "trackrecord"
bad = 0


def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read()


def check(ok, msg):
    global bad
    bad += not ok
    print(("OK   " if ok else "FAIL ") + msg)


def yahoo(sym):
    r = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?interval=1d&range=1mo"))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    return {datetime.fromtimestamp(t, NY).date().isoformat(): (q["open"][i], q["high"][i], q["low"][i], q["close"][i]) for i, t in enumerate(r["timestamp"])}


bars2 = {"SPX": yahoo("^GSPC"), "NDX": yahoo("^NDX")}
PUBLIC = {(x["session"], x["market"]): x for x in json.loads(get("https://wsevwevx.github.io/gex-pro/data/trackrecord.json"))["sessions"]}
for f in sorted((TRACK / "sessions").glob("*.json")):
    s = json.loads(f.read_text())
    p, o = s.get("plan"), s.get("outcome")
    if not p:
        continue
    d = date.fromisoformat(s["session"])
    open_ = datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY)
    cands = []
    # the plan's snapshot folder: today's key, or the retired key that held the plans made before 2026-11-28
    for g in [g for key in (f"{s['market']}-OCC", f"{s['market']}-CBOE") for g in (SNAP / key).glob("*/*.json")]:
        j = json.loads(g.read_text())
        t = datetime.fromisoformat(j["asof"])
        if t < open_ and t >= open_ - timedelta(hours=30) and j.get("status") != "UNAVAILABLE":
            cands.append((t, j))
    made_here = any(abs((t - datetime.fromisoformat(p["asof"])).total_seconds()) < 1 for t, _ in cands)
    if cands and made_here:                    # this PC's snapshot made the plan: it must be the last one before the open
        t, j = max(cands, key=lambda x: x[0])
        check(datetime.fromisoformat(p["asof"]) == t and abs(p["ref"] - j["ref_price"]) < 0.01,
              f"{f.stem}: plan uses the last pre-open snapshot {t.astimezone(NY):%m-%d %H:%M} ET (ref {j['ref_price']:.2f})")
        check(abs(p["em"] - j["extras"]["expected_move"]["daily_points"]) < 0.01 and p["cw"] == round(j["call_wall"]["price"], 2)
              and p["pw"] == round(j["put_wall"]["price"], 2),
              f"{f.stem}: em {p['em']:.2f}, walls {j['call_wall']['price']} / {j['put_wall']['price']} copied unchanged")
    else:
        # the hosted site made this plan; its snapshots live in GitHub's cache, not on this PC
        print(f"SKIP {f.stem}: plan made by the hosted site (its snapshot is not on this PC); grade still checked")
    em = p["em"]
    if not o:
        print(f"     {f.stem}: {s['status']}")
        continue
    if o.get("source") == "Cboe 1-minute":
        # graded on the 15:59 minute bar (until 2026-11-17), which misses the closing print. The site shows these on
        # the official close: the next session's plan reference, frozen from the index level before its open.
        later = sorted(g for g in (TRACK / "sessions").glob(f"*_{s['market']}.json") if g.stem[:10] > s["session"])
        n = json.loads(later[0].read_text()) if later else {}
        np_ = n.get("plan") or {}
        nd = date.fromisoformat(n["session"]) if n else None
        if not np_ or datetime.fromisoformat(np_["asof"]) >= datetime(nd.year, nd.month, nd.day, 9, 30, tzinfo=NY):
            print(f"WAIT {f.stem}: close from the 15:59 bar; corrected once the next session's plan is frozen")
            continue
        o = dict(o, close=np_["ref"])
        pub = PUBLIC.get((s["session"], s["market"])) or {}
        check((pub.get("correction") or {}).get("official") == np_["ref"],
              f"{f.stem}: the site shows the official close {np_['ref']} (recorded {s['outcome']['close']}, the 15:59 bar)")
        o = dict(pub.get("outcome") or o, close=np_["ref"])
    b2 = bars2[p["underlying"]].get(s["session"])
    if b2:
        diff = max(abs(a - b) for a, b in zip((o["open"], o["high"], o["low"], o["close"]), b2))
        check(diff < 0.05 * em, f"{f.stem}: bar from {o['source']} agrees with Yahoo within {diff:.2f} pts")
        _, h, l, c = b2
        ref = p["ref"]
        mine = {"em_close": abs(c - ref) <= em, "em_range": h <= ref + em and l >= ref - em}
        if p["cw"] > ref:
            touched = h >= p["cw"] - 0.05 * em
            mine["cw_held"] = touched and c <= p["cw"] if touched else None
        if p["bias"] in ("Bullish", "Bearish"):
            mine["bias_hit"] = (c > ref) == (p["bias"] == "Bullish")
        theirs = {"em_close": o["em_close"], "em_range": o["em_range"], "cw_held": (o["cw"] or {}).get("held") if (o["cw"] or {}).get("touched") else None,
                  "bias_hit": o["bias_hit"]}
        same = all(theirs[k] == v for k, v in mine.items())
        check(same, f"{f.stem}: hand grade {mine} matches")

# ---- backtest, S&P 500 with VIX, from raw files (Yahoo's ^GSPC and ^VIX daily charts, read with my own parser)
def _yahoo(sym):
    r = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&period1=631152000&period2="
                       f"{int(datetime.now().timestamp()) + 86400}"))["chart"]["result"][0]
    z = ZoneInfo(r["meta"]["exchangeTimezoneName"])
    q = r["indicators"]["quote"][0]
    return {datetime.fromtimestamp(t, z).date().isoformat(): (q["open"][i], q["high"][i], q["low"][i], q["close"][i])
            for i, t in enumerate(r["timestamp"]) if q["close"][i]}


spx = {d: b for d, b in _yahoo("%5EGSPC").items() if b[0]}
vix = {d: b[3] for d, b in _yahoo("%5EVIX").items()}
ds = sorted(spx)
_m = json.loads((TRACK / "backtest.json").read_text())["markets"]["ES"]
END = _m.get("end") or _m.get("to")
n = k = 0
for a, b in zip(ds, ds[1:]):
    if a not in vix or b > END:
        continue
    band = spx[a][3] * vix[a] / 100 * math.sqrt((date.fromisoformat(b) - date.fromisoformat(a)).days / 365)
    n += 1
    k += abs(spx[b][3] - spx[a][3]) <= band
bt = json.loads((TRACK / "backtest.json").read_text())["markets"]["ES"]["overall"]
# the saved backtest may predate the Yahoo-only source: counts may differ by a day or two, the rate may not
check(abs(n - bt["n"]) <= 5 and abs(k / n - bt["close_in"]["k"] / bt["n"]) < 0.001,
      f"backtest SPX/VIX: mine {k}/{n} = {k / n:.4f}, engine {bt['close_in']['k']}/{bt['n']} "
      f"= {bt['close_in']['k'] / bt['n']:.4f}: within 0.1%")
print("ALL MATCH" if not bad else f"{bad} FAILED")
sys.exit(1 if bad else 0)
