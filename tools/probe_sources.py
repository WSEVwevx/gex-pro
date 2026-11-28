"""Does every outside source still answer, from wherever this runs? python tools/probe_sources.py

Run weekly on GitHub's build servers (.github/workflows/probe.yml): the hosted site is built there, and a source that
answers this PC can still refuse GitHub (Truth Social returns HTTP 403 to GitHub, 2026-11-18). Each request uses the
same headers as the app's own fetcher, so a pass here means the app's request works.

A source with a working backup may fail without failing the run (its backup is probed too); exit 1 only when a source
with no working backup fails.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from feeds import drivers, hostswitch, positioning, truthsocial, weekinfo  # noqa: E402
from trackrecord import prices  # noqa: E402

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=1m&range=1d"
VOLS = "https://query1.finance.yahoo.com/v8/finance/chart/%5E{n}?range=1mo&interval=1d"     # the OCC chain's vol curve
PLAIN = {"User-Agent": "Mozilla/5.0 (GEX PRO)"}
DAY = date.today().isoformat()


def _json(b: bytes, need) -> str:
    return need(json.loads(b))


def _contracts(d) -> str:
    n = d["data"]["totalRecord"]
    if not n:
        raise ValueError("no contracts")                     # an empty chain is not a working source
    return f"{n} contracts"


def _rows(key):
    return lambda d: f"{len(d[key] if key else d)} rows"


# (name, url, headers, check(bytes) -> short description, backup name or None)
SOURCES = [
    # candidates (2026-11-21): Nasdaq's option-chain JSON (bid/ask/volume/OI per strike) to give the OCC chain skew and
    # volume. Not used by the app yet; the probe decides whether it answers GitHub.
    ("Nasdaq NDX options (candidate)", "https://api.nasdaq.com/api/quote/NDX/option-chain?assetclass=index&limit=60&excode=oprac&callput=callput&money=all&type=all",
     {**PLAIN, "Accept": "application/json"}, lambda b: _json(b, _contracts), None),
    ("Nasdaq QQQ options (candidate)", "https://api.nasdaq.com/api/quote/QQQ/option-chain?assetclass=etf&limit=60&excode=oprac&callput=callput&money=all&type=all",
     {**PLAIN, "Accept": "application/json"}, lambda b: _json(b, _contracts), None),
    ("Nasdaq SPY options (candidate)", "https://api.nasdaq.com/api/quote/SPY/option-chain?assetclass=etf&limit=60&excode=oprac&callput=callput&money=all&type=all",
     {**PLAIN, "Accept": "application/json"}, lambda b: _json(b, _contracts), None),
    ("OCC NDX open interest", "https://marketdata.theocc.com/series-search?symbolType=U&symbol=NDX", PLAIN,
     lambda b: f"{sum(1 for l in b.decode(errors='replace').splitlines() if l.startswith('NDX'))} series", None),
    ("OCC SPX open interest", "https://marketdata.theocc.com/series-search?symbolType=U&symbol=SPX", PLAIN,
     lambda b: f"{sum(1 for l in b.decode(errors='replace').splitlines() if l.startswith('SPX'))} series", None),
    ("OCC QQQ open interest", "https://marketdata.theocc.com/series-search?symbolType=U&symbol=QQQ", PLAIN,
     lambda b: f"{sum(1 for l in b.decode(errors='replace').splitlines() if l.startswith('QQQ'))} series", None),
    ("OCC SPY open interest", "https://marketdata.theocc.com/series-search?symbolType=U&symbol=SPY", PLAIN,
     lambda b: f"{sum(1 for l in b.decode(errors='replace').splitlines() if l.startswith('SPY'))} series", None),
    ("Yahoo ^VIX1D daily", VOLS.format(n="VIX1D"), PLAIN,
     lambda b: _json(b, lambda d: f"{len(d['chart']['result'][0]['timestamp'])} days"), None),
    ("Yahoo ^VIX9D daily", VOLS.format(n="VIX9D"), PLAIN,
     lambda b: _json(b, lambda d: f"{len(d['chart']['result'][0]['timestamp'])} days"), None),
    ("Yahoo ^VIX daily", VOLS.format(n="VIX"), PLAIN,
     lambda b: _json(b, lambda d: f"{len(d['chart']['result'][0]['timestamp'])} days"), None),
    ("Yahoo ^VIX3M daily", VOLS.format(n="VIX3M"), PLAIN,
     lambda b: _json(b, lambda d: f"{len(d['chart']['result'][0]['timestamp'])} days"), None),
    ("Yahoo ^VXN daily", VOLS.format(n="VXN"), PLAIN,
     lambda b: _json(b, lambda d: f"{len(d['chart']['result'][0]['timestamp'])} days"), None),
    ("Yahoo NQ=F 1-minute", YAHOO.format(s="NQ%3DF"), PLAIN, lambda b: _json(b, lambda d: f"{len(d['chart']['result'][0]['timestamp'])} bars"), "carry model"),
    ("Yahoo ^NDX 1-minute", YAHOO.format(s="%5ENDX"), PLAIN, lambda b: _json(b, lambda d: f"{len(d['chart']['result'][0]['timestamp'])} bars"), "carry model"),
    ("Yahoo ES=F 1-minute", YAHOO.format(s="ES%3DF"), PLAIN, lambda b: _json(b, lambda d: f"{len(d['chart']['result'][0]['timestamp'])} bars"), "carry model"),
    ("Yahoo ^GSPC daily", "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?interval=1d&range=1mo", prices.UA,
     lambda b: _json(b, lambda d: f"{len(d['chart']['result'][0]['timestamp'])} days"), None),
    ("Yahoo quotes (spark)", weekinfo.SPARK.format(syms="NQ%3DF,ES%3DF"), weekinfo.UA, lambda b: _json(b, lambda d: f"{len(d['spark']['result'])} symbols"), None),
    ("ForexFactory calendar", "https://nfs.faireconomy.media/ff_calendar_thisweek.json", {"User-Agent": "Mozilla/5.0 (gexsys personal use)"},
     lambda b: _json(b, lambda d: f"{len(d)} events"), None),
    ("Truth Social posts", truthsocial.API_URL, truthsocial.UA, lambda b: _json(b, lambda d: f"{len(d)} posts"), "trumpstruth.org archive"),
    ("trumpstruth.org archive", truthsocial.RSS_URL, truthsocial.UA, lambda b: f"{len(ET.fromstring(b).findall('.//item'))} posts", None),
    ("slickcharts Nasdaq-100 weights", drivers.WEIGHTS_URL["NQ"], drivers.UA, lambda b: f"{len(b) // 1024} KB page", "weights saved with the app"),
    ("Nasdaq earnings calendar", weekinfo.EARNINGS.format(d=DAY), weekinfo.UA, lambda b: _json(b, lambda d: "ok" if d.get("data") else "no data"), None),
    ("CFTC positioning", positioning.URL + "?$limit=1", positioning.UA, lambda b: _json(b, lambda d: f"{len(d)} rows"), None),
    ("Google News", weekinfo.NEWS.format(q="Nasdaq"), weekinfo.UA, lambda b: f"{len(ET.fromstring(b).findall('.//item'))} items", None),
]


def probe(name, url, headers, check) -> tuple[bool, str, float]:
    t = time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
            body = r.read()
        return True, check(body), time.monotonic() - t
    except Exception as e:                                   # any failure is the finding
        return False, f"{type(e).__name__}: {e}"[:120], time.monotonic() - t


def main() -> int:
    where = "GitHub Actions" if "GITHUB_ACTIONS" in os.environ else "this PC"
    print(f"Source probe from {where}, {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    ok_by = {}
    rows = []
    for name, url, headers, check, backup in SOURCES:
        if hostswitch.why_off(url):                          # GEX_OFF_HOSTS: this computer never asks that host
            print(f"SKIP {name:32s} {hostswitch.why_off(url)}")
            continue
        ok, msg, dt = probe(name, url, headers, check)
        ok_by[name] = ok
        rows.append((name, ok, msg, dt, backup))
    hard = []
    for name, ok, msg, dt, backup in rows:
        covered = not ok and backup and ok_by.get(backup, backup in ("carry model", "weights saved with the app"))
        candidate = not ok and name.endswith("(candidate)")      # not used by the app yet: it can't break the site
        mark = "OK  " if ok else "WARN" if covered or candidate else "FAIL"
        if mark == "FAIL":
            hard.append(name)
        print(f"{mark} {name:32s} {dt:5.1f}s  {msg}" + (f"  (backup in use: {backup})" if covered else "  (candidate, not used yet)" if candidate else ""))
    print("RESULT:", "PASS" if not hard else "FAIL - " + ", ".join(hard))
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
