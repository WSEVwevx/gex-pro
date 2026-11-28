"""Regression tests for the gaps stress test E1 (feed fuzzing, 2026-11-10) found: each corrupted input must be
refused or labelled, never turned into levels or numbers without a word."""
import json
import unittest
from datetime import datetime, timedelta, timezone

from feeds import drivers, quotes
from gexsys import engine as eng
from gexsys.normalize import normalize
from tests.util import chain, contract

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


class TestStoreLatest(unittest.TestCase):
    def test_latest_skips_unusable_results_and_reads_newest_first(self):
        # stress test F1: after one blanked refresh, the next good one fired "regime changed from UNAVAILABLE" and
        # "level appeared" alerts; and latest() read every saved file on every refresh
        import tempfile
        from gexsys.storage import SnapshotStore
        with tempfile.TemporaryDirectory() as tmp:
            st = SnapshotStore(tmp)
            t0 = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)
            st.save("NQ", {"asof": t0.isoformat(), "status": "OK", "n": 1})
            st.save("NQ", {"asof": (t0 + timedelta(minutes=1)).isoformat(), "status": "UNAVAILABLE", "n": 2})
            self.assertEqual(st.latest("NQ")["n"], 2)
            self.assertEqual(st.latest("NQ", usable=True)["n"], 1)
            self.assertIsNone(st.latest("ES"))


class TestDamagedCache(unittest.TestCase):
    def test_service_starts_on_damaged_saved_files(self):
        # stress test F1: a last-good or published file holding null or the wrong JSON shape crashed startup
        import tempfile
        from pathlib import Path
        from gexsys import config as cfgmod, service
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cfgmod.load("configs/free_nq.json")
            cfg.storage["root"] = tmp
            for junk in (b"null", b'{"unexpected": 1}', b'{"summary": 3}', b"\x00\xff garbage", b'{"slot_et": 5}'):
                for name in ("last_good_NQ-OCC.json", "published_NQ-OCC.json"):
                    (Path(tmp) / name).write_bytes(junk)
                w = service.MarketWorker(cfg)
                self.assertIsNone(w.result)
                self.assertIsNone(w.published)


if __name__ == "__main__":
    unittest.main()
