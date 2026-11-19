"""Session context: watched levels, steady changes, the open's levels and reaction stats."""
import unittest
from datetime import datetime, timedelta

from gexsys import session
from gexsys.marketcal import NY


def snap(t, c1=100.0, p1=90.0, regime="POSITIVE", zg=95.0, etf_share=0.6):
    rk = {"call": [{"price": c1}, {"price": c1 + 5}], "put": [{"price": p1}], "abs": [{"price": c1}]}
    return {"asof": t.isoformat(), "regime": regime, "zero_gamma": {"price": zg}, "call_wall": {"price": 110.0},
            "put_wall": {"price": 80.0},
            "extras": {"nearest": {"ranked": rk, "ranked_etf": {"call": [{"price": 1.0}]}, "etf_share": etf_share,
                                   "zero_gamma": {"price": 96.0}}}}


T0 = datetime(2026, 10, 27, 9, 0, tzinfo=NY)          # a Tuesday


class TestSession(unittest.TestCase):
    def test_prior_levels_take_each_sessions_close(self):
        import tempfile
        from pathlib import Path
        from gexsys.storage import SnapshotStore
        with tempfile.TemporaryDirectory() as tmp:
            st = SnapshotStore(tmp)
            mon, tue = datetime(2026, 10, 26, tzinfo=NY), datetime(2026, 10, 27, tzinfo=NY)
            for day, zg in ((mon, 95.0), (tue, 97.0)):
                st.save("NQ-CBOE", dict(snap(day.replace(hour=11), zg=zg - 1), status="OK"))
                st.save("NQ-CBOE", dict(snap(day.replace(hour=16, minute=10), zg=zg), status="OK"))      # the session's last
                st.save("NQ-CBOE", dict(snap(day.replace(hour=19), zg=zg + 5), status="OK"))             # evening: not the close
            folder = Path(tmp) / "NQ-CBOE"
            # Tuesday 12:00: only Monday has closed
            pr = session.prior_levels(folder, tue.replace(hour=12))
            self.assertEqual([(d.isoformat(), lv["ZG"]) for d, lv in pr], [("2026-10-26", 95.0)])
            pr = session.prior_levels(folder, tue.replace(hour=20), n=5)                                 # newest first
            self.assertEqual([(d.isoformat(), lv["ZG"]) for d, lv in pr], [("2026-10-27", 97.0), ("2026-10-26", 95.0)])
            self.assertEqual(session.history_token(pr), "20261027:97.0:110.0:80.0,20261026:95.0:110.0:80.0")
            self.assertEqual(session.prior_levels(folder, tue.replace(hour=20), n=1), pr[:1])

    def test_key_levels_use_index_and_etf_together(self):
        # NDX stays in even when QQQ holds most of the expiry's gamma (it held 64% on 2026-11-18)
        lv = session.key_levels(snap(T0, etf_share=0.64))
        self.assertEqual((lv["C1"], lv["C2"], lv["P1"], lv["Ab1"], lv["flip"], lv["ZG"], lv["CW"]), (100.0, 105.0, 90.0, 100.0, 96.0, 95.0, 110.0))
        s = snap(T0)
        s["extras"]["nearest"]["ranked"] = None                                          # no index chain: the ETF alone
        self.assertEqual(session.key_levels(s)["C1"], 1.0)

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

    def test_open_and_changes_keep_their_own_futures_mapping(self):
        """The open's levels use the mapping saved at the open and each change the one saved with it, not the
        latest ratio: on 2026-11-19 the NQ open levels moved ~4 points between refreshes as the basis moved."""
        import tempfile
        from types import SimpleNamespace
        from gexsys.service import MarketWorker
        from gexsys.storage import SnapshotStore
        at = lambda h, m: datetime(2026, 10, 27, h, m, tzinfo=NY)
        with tempfile.TemporaryDirectory() as tmp:
            st = SnapshotStore(tmp)
            for t, c1, fm in ((at(9, 33), 100.0, {"factor": 1.01, "offset": 0.0}), (at(10, 0), 110.0, {"factor": 1.02, "offset": 2.0}),
                              (at(10, 5), 110.0, {"factor": 1.03, "offset": 0.0}), (at(10, 30), 120.0, None), (at(10, 35), 120.0, None)):
                st.save("NQ-CBOE", dict(snap(t, c1=c1), status="OK", **({"futures_map": fm} if fm else {})))
            w = SimpleNamespace(store=st, key="NQ-CBOE", _stats=lambda *a: {})
            r = {"summary": dict(snap(at(11, 0), c1=120.0), status="OK"), "mapped": {"mapping": {"factor": 1.05, "offset": 0.0}}}
            MarketWorker._add_session(w, r, at(11, 0))
            S = r["session"]
            self.assertEqual(S["open"]["C1"], 101.0)                                   # 100 x 1.01, frozen at the open
            self.assertNotIn("map", S["open"])
            c1 = [c for c in S["changes"] if c["what"] == "C1"]
            self.assertEqual([(c["frm"], c["to"]) for c in c1], [(115.5, 126.0), (104.0, 114.25)])  # no saved map: 1.05 now
            self.assertTrue(all("map" not in c for c in S["changes"]))
            self.assertEqual(S["levels"]["C1"], 126.0)                                 # the live levels: today's mapping
            r2 = {"summary": dict(snap(at(11, 0), c1=120.0), status="OK"), "mapped": None}      # no mapping now: index prices
            MarketWorker._add_session(w, r2, at(11, 0))
            self.assertEqual(r2["session"]["open"]["C1"], 100.0)

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
