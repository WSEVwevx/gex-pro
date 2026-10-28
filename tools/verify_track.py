"""Independent re-check of the track record and the backtest. Shares no code with trackrecord/.

1. Plans: for each session, scan every saved snapshot file myself and confirm the plan used the latest
   one timestamped before 09:30 ET (and none after).
2. Grades: re-fetch the session bars from a second source where possible and re-grade by hand.
3. Backtest: recompute the S&P 500 / VIX close-inside rate from the raw CSV + JSON with my own loop.

Run from the project folder: python tools/verify_track.py [track folder]  (default: the local app's copy)
"""
import csv
import io
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
for f in sorted((TRACK / "sessions").glob("*.json")):
    s = json.loads(f.read_text())
    p, o = s.get("plan"), s.get("outcome")
    if not p:
        continue
    d = date.fromisoformat(s["session"])
    open_ = datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY)
    key = {"NQ": "NQ-CBOE", "ES": "ES-CBOE"}[s["market"]]
    cands = []
    for g in (SNAP / key).glob("*/*.json"):
        j = json.loads(g.read_text())
        t = datetime.fromisoformat(j["asof"])
        if t < open_ and t >= open_ - timedelta(hours=30) and j.get("status") != "UNAVAILABLE":
            cands.append((t, j))
    if cands:
        t, j = max(cands, key=lambda x: x[0])
        check(datetime.fromisoformat(p["asof"]) == t and abs(p["ref"] - j["ref_price"]) < 0.01,
              f"{f.stem}: plan uses the last pre-open snapshot {t.astimezone(NY):%m-%d %H:%M} ET (ref {j['ref_price']:.2f})")
        check(abs(p["em"] - j["extras"]["expected_move"]["daily_points"]) < 0.01 and p["cw"] == round(j["call_wall"]["price"], 2)
              and p["pw"] == round(j["put_wall"]["price"], 2),
              f"{f.stem}: em {p['em']:.2f}, walls {j['call_wall']['price']} / {j['put_wall']['price']} copied unchanged")
    else:
        # the hosted site made this plan; its snapshots live in GitHub's cache, not on this PC
        print(f"SKIP {f.stem}: no local snapshot before the open (plan made by the hosted site); grade still checked")
    em = p["em"]
    if not o:
        print(f"     {f.stem}: {s['status']}")
        continue
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

# ---- backtest, S&P 500 with VIX, from raw files
spx = json.loads(get("https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/_SPX.json"))["data"]
spx = {r["date"]: (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])) for r in spx if float(r["open"]) > 0}
vix = {}
for r in csv.DictReader(io.StringIO(get("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv").decode())):
    m, dd, y = r["DATE"].split("/")
    vix[f"{y}-{int(m):02d}-{int(dd):02d}"] = float(r["CLOSE"])
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
check(n == bt["n"] and k == bt["close_in"]["k"], f"backtest SPX/VIX: mine {k}/{n} = {k / n:.4f}, engine {bt['close_in']['k']}/{bt['n']}")
print("ALL MATCH" if not bad else f"{bad} FAILED")
sys.exit(1 if bad else 0)
