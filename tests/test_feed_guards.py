"""Regression tests for the gaps stress test E1 (feed fuzzing, 2026-11-10) found: each corrupted input must be
refused or labelled, never turned into levels or numbers without a word."""
import json
import unittest
from datetime import datetime, timedelta, timezone

from feeds import drivers, quotes
from gexsys import engine as eng
from gexsys.normalize import normalize
from gexsys.providers.cboe import CboeProvider, ProviderError
from tests.util import chain, contract


def _raw(price, ts=None, n=3):
    ts = ts or datetime.now(timezone.utc) - timedelta(minutes=20)
    opts = [{"option": f"SPXW261120C0{7600 + 25 * i}000", "iv": 0.2, "gamma": 0.001, "open_interest": 100,
             "bid": 1.0, "ask": 1.2, "volume": 1} for i in range(n)]
    return {"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "data": {"current_price": price, "options": opts}}


def _etf(price):
    r = _raw(price)
    for o in r["data"]["options"]:
        o["option"] = "SPY261120C00760000"
    return r


class TestProviderGuards(unittest.TestCase):
    def test_timestamp_in_the_future_is_refused(self):
        raw = _raw(7600.0, ts=datetime.now(timezone.utc) + timedelta(hours=5))
        with self.assertRaises(ProviderError):
            CboeProvider(http=lambda *a, **k: raw, include_etf=False).fetch_snapshot("SPX", 45, True)

    def test_etf_without_a_price_or_with_a_wrong_one_is_not_used_and_says_so(self):
        for etf_price, why in ((0, "no price"), (76.0, "price ratio 100.00 outside 9.5-10.5")):
            raws = {"_SPX": _raw(7600.0), "SPY": _etf(etf_price)}
            prov = CboeProvider(http=lambda url, headers, limiter=None: raws[url.rsplit("/", 1)[1][:-5]], include_etf=True)
            snap = prov.fetch_snapshot("SPX", 45, True)
            self.assertFalse(any(c.root == "SPY" for c in snap.contracts))
            self.assertTrue(any("SPY options not used (" + why in w for w in snap.warnings), snap.warnings)
            res = eng.compute(normalize(snap), asof=snap.fetched_at)
            self.assertEqual(res.status, "DEGRADED")


class TestCorruptChain(unittest.TestCase):
    def test_many_invalid_values_degrade_the_result(self):
        cs = [contract(k, oi=float("nan") if k % 7 == 0 else 1000.0) for k in range(80, 121)]
        snap = normalize(chain(cs))
        self.assertTrue(any("may be corrupt" in w for w in snap.warnings))
        self.assertEqual(eng.compute(snap, asof=snap.fetched_at).status, "DEGRADED")
        ok = normalize(chain([contract(k) for k in range(80, 121)]))
        self.assertFalse(any("may be corrupt" in w for w in ok.warnings))


class TestFiniteQuotes(unittest.TestCase):
    def test_nan_prices_are_not_shown(self):
        meta = {"regularMarketPrice": float("nan"), "chartPreviousClose": 100.0}
        raw = json.dumps({"chart": {"result": [{"meta": meta}]}}).encode()
        self.assertIsNone(quotes.parse(raw))
        self.assertIsNone(drivers.parse_intraday(raw))
        bars = {"timestamp": [1, 2], "indicators": {"quote": [{"open": [1.0, float("nan")], "high": [1.0, 2.0],
                                                               "low": [1.0, 2.0], "close": [1.0, 2.0]}]}}
        self.assertEqual(drivers._bars(bars), [[1, 1.0, 1.0, 1.0, 1.0]])


if __name__ == "__main__":
    unittest.main()
