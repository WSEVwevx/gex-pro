"""The Bias chart replay (gexsys/timeline.py): the levels shown at a minute are exactly the ones the site had then."""
import gzip
import json
import random
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from gexsys import marketcal, timeline
from gexsys.mapping import round_to_tick
from gexsys.storage import SnapshotStore

OPEN = datetime(2026, 11, 13, 9, 30, tzinfo=marketcal.NY)          # a Friday
KEY = "NQ-CBOE"


def snap(t, zg, cw=29000.0, pw=27000.0, factor=1.0032, ref_time=None, status="OK", mapped=True):
    s = {"asof": t.isoformat(), "status": status, "zero_gamma": {"price": zg}, "call_wall": {"price": cw},
         "put_wall": {"price": pw}, "abs_gamma": {"price": cw}, "ref_price": 28000.0,
         "ref_time": (ref_time or t - timedelta(minutes=15)).isoformat(),
         "extras": {"nearest": {"label": "0DTE"}, "max_pain": [{"price": 28100.0}]}}
    if mapped:
        s["futures_map"] = {"factor": factor, "offset": 0.0}
    return s


def shown(tl, minute):
    """What the page draws at a slider minute: the last row that became visible at or before it."""
    rows = [r for r in tl["rows"] if r[0] <= minute]
    return rows[-1] if rows else None


class TestReplay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = SnapshotStore(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, now, candles=()):
        return timeline.build(self.root / KEY, "NQ", "ratio", list(candles), now)

    def test_no_hindsight(self):
        rng = random.Random(7)
        saved = []
        t = OPEN - timedelta(minutes=20)
        while t < OPEN + timedelta(minutes=380):
            s = snap(t, zg=28000.0 + rng.randrange(0, 40) * 5, factor=1.003 + rng.random() / 1000)
            self.store.save(KEY, s)
            saved.append(s)
            t += timedelta(seconds=rng.randrange(40, 200))
        tl = self.build(OPEN + timedelta(minutes=390))
        for minute in rng.sample(range(0, 390), 20):
            cut = OPEN + timedelta(minutes=minute)
            want = [s for s in saved if datetime.fromisoformat(s["asof"]) <= cut][-1]
            f = want["futures_map"]["factor"]
            self.assertEqual(shown(tl, minute)[1], round_to_tick(want["zero_gamma"]["price"] * f, 0.25), minute)

    def test_a_snapshot_one_second_late_is_not_shown(self):
        self.store.save(KEY, snap(OPEN + timedelta(minutes=10), zg=28000.0))
        self.store.save(KEY, snap(OPEN + timedelta(minutes=20, seconds=1), zg=28500.0))
        tl = self.build(OPEN + timedelta(minutes=60))
        self.assertEqual(shown(tl, 20)[1], round_to_tick(28000.0 * 1.0032, 0.25))
        self.assertEqual(shown(tl, 21)[1], round_to_tick(28500.0 * 1.0032, 0.25))

    def test_gap_holds_the_last_levels(self):
        for m in list(range(0, 60, 2)) + list(range(90, 120, 2)):         # nothing from 10:30 to 11:00
            self.store.save(KEY, snap(OPEN + timedelta(minutes=m), zg=28000.0 + (m >= 90) * 100))
        self.store.save(KEY, snap(OPEN + timedelta(minutes=70), zg=1.0, status="UNAVAILABLE"))
        tl = self.build(OPEN + timedelta(minutes=125))
        self.assertEqual(shown(tl, 80)[1], round_to_tick(28000.0 * 1.0032, 0.25))
        self.assertFalse([s for s in tl["seen"] if 58 * 60 < s < 90 * 60])           # the page shows "no update since"

    def test_rows_only_on_change_and_the_levels_at_the_open(self):
        self.store.save(KEY, snap(OPEN - timedelta(hours=2), zg=27000.0))
        self.store.save(KEY, snap(OPEN - timedelta(minutes=5), zg=27900.0))
        for m in range(0, 30):
            self.store.save(KEY, snap(OPEN + timedelta(minutes=m, seconds=30), zg=28000.0))
        tl = self.build(OPEN + timedelta(minutes=40))
        self.assertEqual([r[0] for r in tl["rows"]], [0, 1])
        self.assertEqual(tl["rows"][0][1], round_to_tick(27900.0 * 1.0032, 0.25))
        self.assertEqual(tl["seen"][0], -300)

    def test_old_snapshots_are_mapped_from_the_futures_bar_and_flagged(self):
        rt = OPEN + timedelta(minutes=5, seconds=20)
        self.store.save(KEY, snap(OPEN + timedelta(minutes=20), zg=28000.0, ref_time=rt, mapped=False))
        self.store.save(KEY, snap(OPEN + timedelta(minutes=30), zg=28000.0, ref_time=OPEN + timedelta(hours=9), mapped=False))
        bar = int((OPEN + timedelta(minutes=5)).timestamp())
        tl = self.build(OPEN + timedelta(minutes=40), [[bar, 0, 0, 0, 28084.0]])
        self.assertEqual(tl["rows"], [[20, round_to_tick(28000.0 * 28084.0 / 28000.0, 0.25),
                                       *[round_to_tick(v * 28084.0 / 28000.0, 0.25) for v in (29000.0, 27000.0, 29000.0, 28100.0)], 1, 0]])
        self.assertEqual(tl["estimated"], 1)                                # the one without a bar is left out

    def test_price_bars_only_once_closed(self):
        self.store.save(KEY, snap(OPEN, zg=28000.0))
        now = OPEN + timedelta(minutes=10, seconds=30)
        bars = [[int((OPEN + timedelta(minutes=m)).timestamp()), 1, 1, 1, 28000.0 + m] for m in range(-5, 12)]
        tl = self.build(now, bars)
        self.assertEqual([p[0] for p in tl["price"]], list(range(0, 10)))   # 09:39 closed at 09:40; 09:40 still open
        self.assertEqual(tl["session"]["now_minute"], 10)

    def test_after_the_close_and_on_the_weekend_the_last_session(self):
        self.store.save(KEY, snap(OPEN, zg=28000.0))
        tl = self.build(datetime(2026, 11, 14, 12, 0, tzinfo=marketcal.NY))
        self.assertEqual(tl["session"]["open"], OPEN.isoformat())
        self.assertFalse(tl["session"]["live"])
        self.assertEqual(tl["session"]["now_minute"], 390)

    def test_size_on_a_busy_session(self):
        rng = random.Random(3)
        for s in range(0, 390 * 60, 30):                                    # every 30 s, every level moving
            self.store.save(KEY, snap(OPEN + timedelta(seconds=s), zg=28000.0 + rng.random() * 400,
                                      cw=29000.0 + rng.random() * 400, pw=27000.0 + rng.random() * 400))
        bars = [[int((OPEN + timedelta(minutes=m)).timestamp()), 1, 1, 1, 28000.0 + m] for m in range(390)]
        tl = self.build(OPEN + timedelta(minutes=391), bars)
        self.assertLess(len(gzip.compress(json.dumps(tl, separators=(",", ":")).encode())), 30_000)

    def test_a_basis_change_is_not_a_level_move(self):
        # the futures basis moves the mapped prices every refresh; only a change in the options level itself is a move
        self.store.save(KEY, snap(OPEN - timedelta(minutes=5), zg=27000.0))
        self.store.save(KEY, snap(OPEN + timedelta(minutes=1), zg=28000.0, factor=1.0032))
        self.store.save(KEY, snap(OPEN + timedelta(minutes=2), zg=28000.0, factor=1.0034))
        self.store.save(KEY, snap(OPEN + timedelta(minutes=3), zg=28100.0, factor=1.0034))
        tl = self.build(OPEN + timedelta(minutes=10))
        self.assertEqual([(r[0], r[-1]) for r in tl["rows"]], [(0, 0), (1, 1), (2, 0), (3, 1)])

    def test_empty_history(self):
        tl = self.build(OPEN + timedelta(minutes=30))
        self.assertEqual((tl["rows"], tl["seen"], tl["price"]), ([], [], []))


class TestSavedMapping(unittest.TestCase):
    def test_replay_equals_the_levels_the_site_showed(self):
        # a real refresh saves its mapping; the replayed row at that minute is the Bias chart's own levels
        from tests.test_integration import synth_cfg
        from gexsys.config import make_provider
        from gexsys.pipeline import run_once
        with tempfile.TemporaryDirectory() as tmp:
            cfg = synth_cfg(tmp)
            r = run_once(cfg, make_provider(cfg), SnapshotStore(tmp))       # Tue 2026-10-20 11:00 ET
            lv = r["bias"]["levels"]
            tl = timeline.build(Path(tmp) / f"NQ-{r['summary']['provider']}", "NQ", cfg.method, [],
                                datetime.fromisoformat(r["summary"]["asof"]) + timedelta(seconds=1))
            row = dict(zip(tl["cols"], tl["rows"][-1][1:]))
            self.assertEqual({k: v for k, v in row.items() if v is not None}, lv)
            self.assertEqual(tl["rows"][-1][-2], 0)                          # its own saved mapping, not an estimate


if __name__ == "__main__":
    unittest.main()
