"""Who holds E-mini S&P 500 and Nasdaq-100 futures: the CFTC's weekly Traders in Financial Futures report.

Free US government data (publicreporting.cftc.gov). Positions are as of Tuesday and published the following
Friday afternoon, so this is weekly context, never an intraday signal. E-mini contracts only, not the micros.

Raw net positions mislead: leveraged funds run a large short against cash holdings year after year, so a big
short in ES can be perfectly normal. Each net position is therefore ranked against its own last 3 years.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("feeds.positioning")
URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
UA = {"User-Agent": "Mozilla/5.0 (GEX PRO)", "Accept": "application/json"}
CONTRACTS = {"ES": ("13874A", "E-mini S&P 500"), "NQ": ("209742", "E-mini Nasdaq-100")}
GROUPS = (("lev_money", "Leveraged funds"), ("asset_mgr", "Asset managers"))
WEEKS = 156             # 3 years of weekly reports to rank against
MIN_WEEKS = 26
TTL_S = 6 * 3600        # the report is weekly; a few checks a day catch it soon after it appears


def label(rank: float) -> str:
    return ("very long for them" if rank >= 90 else "longer than usual" if rank >= 70
            else "very short for them" if rank <= 10 else "shorter than usual" if rank <= 30 else "normal range")


def parse_rows(rows: list) -> list:
    """[{date, oi, nets: {group: net contracts}}], oldest first; rows with missing numbers are dropped."""
    out = []
    for r in rows:
        try:
            nets = {g: int(r[f"{g}_positions_long"]) - int(r[f"{g}_positions_short"]) for g, _ in GROUPS}
            out.append({"date": r["report_date_as_yyyy_mm_dd"][:10], "oi": int(r["open_interest_all"]), "nets": nets})
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out, key=lambda x: x["date"])


def summarize(market: str, weeks: list) -> Optional[dict]:
    if len(weeks) < MIN_WEEKS + 1:
        return None
    now, prev, past = weeks[-1], weeks[-2], weeks[-WEEKS - 1:-1]
    groups = []
    for g, name in GROUPS:
        net = now["nets"][g]
        rank = round(100 * sum(w["nets"][g] < net for w in past) / len(past))
        groups.append({"key": g, "name": name, "net": net, "change": net - prev["nets"][g],
                       "pct_oi": round(100 * net / now["oi"], 1) if now["oi"] else None, "rank": rank, "label": label(rank)})
    return {"market": market, "contract": CONTRACTS[market][1], "asof": now["date"], "open_interest": now["oi"], "weeks": len(past), "groups": groups}


class Positioning:
    def __init__(self, cache_path: Optional[Path] = None, clock: Callable[[], float] = time.time,
                 fetch: Optional[Callable[[str], bytes]] = None):
        self.cache_path, self.clock = cache_path, clock
        self._fetch = fetch or self._get
        self._lock = threading.Lock()
        self._at = 0.0
        self._out: Optional[dict] = None
        if cache_path and cache_path.exists():
            try:
                self._out = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._out = None

    @staticmethod
    def _get(url: str) -> bytes:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.read()

    def _market(self, market: str) -> Optional[dict]:
        q = urllib.parse.urlencode({"cftc_contract_market_code": CONTRACTS[market][0], "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": WEEKS + 1})
        return summarize(market, parse_rows(json.loads(self._fetch(f"{URL}?{q}"))))

    def get(self) -> dict:
        """{"markets": {"ES": summary, "NQ": summary}}; the last good copy when the source fails."""
        with self._lock:
            if self._out is not None and self.clock() - self._at < TTL_S:
                return self._out
            self._at = self.clock()
            fresh, errors = {}, []
            for m in CONTRACTS:
                try:
                    got = self._market(m)
                    if got:
                        fresh[m] = got
                except Exception as e:
                    log.warning("CFTC positioning %s failed: %s", m, e)
                    errors.append(f"{m}: {e}")
            merged = dict((self._out or {}).get("markets") or {}, **fresh)     # a market that failed keeps its last report
            self._out = {"markets": merged, "source": "CFTC Traders in Financial Futures",
                         "error": "; ".join(errors) or None}
            if fresh and self.cache_path:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(json.dumps(self._out), encoding="utf-8")
            return self._out
