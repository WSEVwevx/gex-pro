"""Performance guards (perf_profile, 2026-11-13). The history-dependent costs are checked by counting work, which
cannot flake; the compute cost by a generous time ceiling (3x the measured median on the development PC)."""
import json
import statistics
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from gexsys import engine as eng, extras, session
from gexsys.storage import SnapshotStore
from tests.util import ASOF, chain, contract

COMPUTE_CEILING_S = 1.1          # 3 x 0.354 s median for this chain (it took ~3.5x longer before the profile fix)


def _fill(root: Path, days: int, per_day: int) -> None:
    t0 = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
    st = SnapshotStore(str(root))
    for d in range(days):
        for i in range(per_day):
            t = t0 - timedelta(days=d) + timedelta(minutes=i)
            st.save("NQ-CBOE", {"asof": t.isoformat(), "status": "OK", "zero_gamma": {"price": 100.0 + i}})


class TestHistoryCosts(unittest.TestCase):
    def test_store_read_lists_only_the_newest_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fill(Path(tmp), days=12, per_day=20)
            globbed = []
            real = Path.glob
            with mock.patch.object(Path, "glob", lambda self, pat: globbed.append(self.name) or real(self, pat)):
                s = SnapshotStore(tmp).latest("NQ-CBOE", usable=True)
            self.assertEqual(s["zero_gamma"]["price"], 119.0)
            self.assertEqual(globbed, ["20261113"])                     # one folder, however long the history

    def test_session_reader_parses_each_file_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fill(Path(tmp), days=2, per_day=30)
            folder = Path(tmp) / "NQ-CBOE"
            since = datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc)
            session._LIGHT.clear()
            with mock.patch.object(session.json, "loads", wraps=json.loads) as loads:
                first = session.summaries_since(folder, since)
                n = loads.call_count
                again = session.summaries_since(folder, since)
            self.assertEqual(n, 60)
            self.assertEqual(loads.call_count, 60)                     # the second refresh parses nothing
            self.assertEqual(first, again)

    def test_max_pain_is_computed_once_per_input(self):
        cs = [contract(k, typ=t, oi=100 + k) for k in range(90, 111) for t in ("C", "P")]
        extras._MAX_PAIN.clear()
        first = extras.max_pain(cs)
        with mock.patch.object(extras.math, "inf", side_effect=AssertionError("recomputed")):
            self.assertEqual(extras.max_pain(cs), first)


class TestComputeCeiling(unittest.TestCase):
    def test_compute_stays_fast(self):
        cs = [contract(k, typ=t, iv=0.15 + abs(k - 1000) / 4000, oi=100 + (k % 7) * 50, days=d)
              for d in (0.2, 1, 2, 3, 7, 14, 30) for k in range(700, 1301) for t in ("C", "P")]
        snap = chain(cs, spot=1000.0)
        ts = []
        for _ in range(3):
            t = time.perf_counter()
            eng.compute(snap, asof=ASOF)
            ts.append(time.perf_counter() - t)
        self.assertLess(statistics.median(ts), COMPUTE_CEILING_S,
                        "GEX compute got much slower: profile it (tools/stress/perf_profile.py)")


if __name__ == "__main__":
    unittest.main()
