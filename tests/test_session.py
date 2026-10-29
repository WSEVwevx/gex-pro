"""Session context: watched levels, steady changes, the open's levels and reaction stats."""
import unittest
from datetime import datetime, timedelta, timezone

from gexsys import session
from gexsys.marketcal import NY


def snap(t, c1=100.0, p1=90.0, regime="POSITIVE", zg=95.0, etf_share=0.6):
    rk = {"call": [{"price": c1}, {"price": c1 + 5}], "put": [{"price": p1}], "abs": [{"price": c1}]}
    return {"asof": t.isoformat(), "regime": regime, "zero_gamma": {"price": zg}, "call_wall": {"price": 110.0},
            "put_wall": {"price": 80.0},
            "extras": {"nearest": {"ranked": {"call": [{"price": 1.0}]}, "ranked_etf": rk, "etf_share": etf_share,
                                   "zero_gamma": {"price": 96.0}}}}


T0 = datetime(2026, 10, 27, 9, 0, tzinfo=NY)          # a Tuesday


class TestSession(unittest.TestCase):
    def test_key_levels_follow_the_auto_chain(self):
        lv = session.key_levels(snap(T0))
        self.assertEqual((lv["C1"], lv["C2"], lv["P1"], lv["Ab1"], lv["flip"], lv["ZG"], lv["CW"]), (100.0, 105.0, 90.0, 100.0, 96.0, 95.0, 110.0))
        self.assertEqual(session.key_levels(snap(T0, etf_share=0.2))["C1"], 1.0)        # index + ETF ranking

    def test_changes_need_two_snapshots(self):
        s = [snap(T0), snap(T0 + timedelta(minutes=5), c1=104), snap(T0 + timedelta(minutes=10)),   # one-off flicker
             snap(T0 + timedelta(minutes=15), c1=120), snap(T0 + timedelta(minutes=20), c1=120, regime="NEGATIVE"),
             snap(T0 + timedelta(minutes=25), c1=120, regime="NEGATIVE")]
        ch = session.changes(s)
        self.assertEqual([(c["what"], c["frm"], c["to"]) for c in ch],
                         [("regime", "POSITIVE", "NEGATIVE"), ("C1", 100.0, 120), ("C2", 105.0, 125), ("Ab1", 100.0, 120)])

    def test_open_levels_window(self):
        s = [snap(T0), snap(datetime(2026, 10, 27, 9, 33, tzinfo=NY), c1=101)]
        self.assertEqual(session.open_levels(s, datetime(2026, 10, 27, 11, 0, tzinfo=NY))["C1"], 101)
        self.assertIsNone(session.open_levels(s, datetime(2026, 10, 27, 9, 0, tzinfo=NY)))     # before the open
        self.assertIsNone(session.open_levels(s, datetime(2026, 10, 27, 18, 30, tzinfo=NY)))   # next session
        self.assertIsNone(session.open_levels([snap(T0)], datetime(2026, 10, 27, 11, 0, tzinfo=NY)))  # none near 09:30

    def test_session_start(self):
        self.assertEqual(session.session_start(datetime(2026, 10, 27, 10, 0, tzinfo=NY)), datetime(2026, 10, 26, 18, 0, tzinfo=NY))
        self.assertEqual(session.session_start(datetime(2026, 10, 27, 19, 0, tzinfo=NY)), datetime(2026, 10, 27, 18, 0, tzinfo=NY))

    def test_reaction_stats_hold_and_break(self):
        t = T0.timestamp()
        bar = lambda i, h, lo, c: [int(t + 300 * i), c, h, lo, c]
        # C1 at 100: price rises into it, rejects to 96 (held, bounce 4); later breaks through and closes 101
        candles = [bar(0, 98, 97, 97.5), bar(1, 100.01, 98, 99), *[bar(2 + k, 99, 96, 96.5) for k in range(12)],
                   bar(14, 98, 97, 97.5), bar(15, 98, 97, 97.5), bar(16, 98, 97, 97.5), bar(17, 98, 97, 97.5), bar(18, 98, 97, 97.5),
                   bar(19, 98, 97, 97.5), bar(20, 100.02, 99, 99.5), *[bar(21 + k, 101.5, 100.5, 101) for k in range(12)]]
        st = session.reaction_stats([snap(T0 - timedelta(hours=1))], candles, 1.0)["C1"]
        self.assertEqual((st["n"], st["held"]), (2, 1))
        self.assertAlmostEqual(st["bounce"], 4.0)
        self.assertEqual(session.stats_token({"C1": st}), "C1:2:1:4.0")
        self.assertEqual(session.open_token({"C1": 100.0, "P1": 90.0}), "C1:100.00,P1:90.00")


if __name__ == "__main__":
    unittest.main()
