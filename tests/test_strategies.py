"""Futures strategy lab: order simulation (worst case inside a bar), rules, single-position swings, the bar, GEX forward test."""
import unittest
from datetime import date, timedelta

from trackrecord import strategies as S


class TestTrade(unittest.TestCase):
    def test_limit_fill_then_close(self):
        self.assertEqual(S.trade([(100, 100.5, 98.5, 99.5)], +1, 99, "limit", 98), 0.5)
        self.assertIsNone(S.trade([(100, 100.5, 99.5, 100)], +1, 99, "limit", 98))

    def test_stop_in_fill_bar_is_worst_case(self):
        self.assertEqual(S.trade([(100, 100.5, 97.5, 99.5)], +1, 99, "limit", 98), -1.0)
        self.assertEqual(S.trade([(97, 99, 96, 98)], +1, 99, "limit", 98), 0.0)            # opened under the stop: filled and out at once

    def test_stop_before_target_in_one_bar(self):
        self.assertEqual(S.trade([(100, 101.5, 98.5, 100)], +1, None, "open", 99, 101), -1.0)
        self.assertEqual(S.trade([(100, 101.5, 99.5, 101), (101, 101, 98.5, 99)], +1, None, "open", 99, 101), 1.0)

    def test_short_stop_entry_and_gap_through_stop(self):
        self.assertEqual(S.trade([(100, 100.2, 98.8, 99.0)], -1, 99.5, "stop", 101), 0.5)
        self.assertEqual(S.trade([(100, 100, 99, 99.4), (102, 103, 101.5, 102)], -1, 99.5, "stop", 101), 99.5 - 102)


def day(path, ref=100.0, em=1.0, **kw):
    d = {"date": "2026-01-02", "ref": ref, "em": em, "path": path, "ts_prev": 0.85, "front_prev": 0.85,
         "vix_prev": 20.0, "vixh": {}, "regime": "POSITIVE"}
    d.update(kw)
    return d


class TestIntradayRules(unittest.TestCase):
    def test_orb_one_cancels_other_and_worst_case(self):
        p = [(100, 101, 99, 100.5), (100.5, 101.6, 100.4, 101.5), (101.5, 102, 101, 101.8)]
        self.assertEqual(S._orb(day(p)), [101.8 - 101])                                  # up break, out at the close
        both = [(100, 101, 99, 100), (100, 101.5, 98.5, 100)]                           # one hour breaks both sides
        self.assertEqual(S._orb(day(both)), [-2.0])
        self.assertEqual(S.orb_front_stress(day(p, front_prev=0.95)), [])               # filter: VIX9D must be over VIX

    def test_last_half_hour_and_vanna(self):
        p = [(100, 100.5, 99.8, 100.4)] * 5 + [(100.4, 100.6, 100.3, 100.5), (100.5, 100.9, 100.4, 100.8)]
        self.assertAlmostEqual(S.last_half_hour_momentum(day(p))[0], 0.3)              # +0.5 em by 15:30: long the last bar
        self.assertEqual(S.vanna_afternoon(day(p, vixh={"12:00": 19.0})), [100.8 - p[4][0]])   # VIX -5% by 13:00: long from 13:30
        self.assertEqual(S.vanna_afternoon(day(p, vixh={"12:00": 19.9})), [])

    def test_first_hour_fade(self):
        p = [(100, 100.8, 100, 100.7), (100.7, 100.8, 99.9, 100.1)]                     # +0.7 em first hour, then fills
        self.assertAlmostEqual(S.first_hour_fade(day(p))[0], 100.7 - 100.0)
        self.assertEqual(S.first_hour_fade(day(p, ts_prev=0.95)), [])


class TestSwing(unittest.TestCase):
    def D(self, closes, ts):
        out, d = [], date(2026, 1, 1)
        for c, t in zip(closes, ts):
            d += timedelta(days=1)
            out.append({"date": d.isoformat(), "ref": c, "em": 1.0, "o": c, "c": c, "ts": t, "front": 1.0, "vix": 20, "vix_prev": 20})
        return out

    def test_single_position_and_hold(self):
        spec = next(r for r in S.RULES if r["id"] == "backwardation_bounce")
        D = self.D([100, 101, 102, 103, 104, 105, 106, 107], [1.1, 1.1, 1.1, 0.9, 0.9, 0.9, 0.9, 0.9])
        tr = S.run_swing(D, spec, 0.5)
        self.assertEqual(len(tr), 1)                                                     # signals on days 2-3 ignored while in the trade
        self.assertAlmostEqual(tr[0][1], 103 - 100 - 0.5)

    def test_position_kept_while_signal_stays_on(self):
        spec = next(r for r in S.RULES if r["id"] == "contango_hold")
        D = self.D([100, 101, 102, 103, 102, 104], [0.9, 0.9, 0.9, 1.0, 0.9, 0.9])
        tr = S.run_swing(D, spec, 0.5)
        # one round trip for the 3-session run; the trade still open on the last day is valued at the last close
        self.assertEqual([round(x[1], 2) for x in tr], [103 - 100 - 0.5, 104 - 102 - 0.5])
        self.assertEqual(tr[0][3], 3)
        now = S.position_now(D, spec)
        self.assertTrue(now["in"])
        self.assertEqual((now["since"], now["entry"]), (D[4]["date"], 102))

    def test_overnight_exit(self):
        spec = next(r for r in S.RULES if r["id"] == "overnight_contango")
        D = self.D([100, 102], [0.9, 0.9])
        D[1]["o"] = 101
        self.assertAlmostEqual(S.run_swing(D, spec, 0.5)[0][1], 101 - 100 - 0.5)


class TestVerdict(unittest.TestCase):
    def res(self, n=100, avg=0.1, t=2.5, halves=(0.1, 0.1), oos=None):
        w = {"stats": {"n": n, "avg_r": avg, "avg_pts": avg, "t": t}, "halves": [{"n": 10, "avg_r": h} for h in halves]}
        r = {"window": w}
        if oos is not None:
            r["oos"] = oos
        return r

    def test_intraday_bar(self):
        self.assertEqual(S.verdict("intraday", {"SPX": self.res(), "NDX": self.res()}), (True, "passed every test"))
        self.assertFalse(S.verdict("intraday", {"SPX": self.res(), "NDX": self.res(t=1.9)})[0])
        self.assertFalse(S.verdict("intraday", {"SPX": self.res(halves=(0.2, -0.01)), "NDX": self.res()})[0])
        self.assertIn("too few", S.verdict("intraday", {"SPX": self.res(n=20), "NDX": self.res()})[1])

    def test_swing_needs_out_of_sample(self):
        good = {"stats": {"n": 100, "avg_r": 0.1, "avg_pts": 1.0, "t": 1.7}, "halves": [{"n": 50, "avg_r": 0.1}] * 2}
        weak = dict(good, stats={"n": 100, "avg_r": 0.1, "avg_pts": 1.0, "t": 1.5})
        self.assertTrue(S.verdict("swing", {"SPX": self.res(t=0.5, oos=good), "NDX": self.res(t=0.5, oos=good)})[0])
        self.assertIn("out-of-sample", S.verdict("swing", {"SPX": self.res(oos=good), "NDX": self.res(oos=weak)})[1])


class TestStudyAndGex(unittest.TestCase):
    def test_study_end_to_end(self):
        bars, vol, hourly, term = {}, {}, {}, {"VIX": {}, "VIX3M": {}, "VIX9D": {}}
        d, c = date(2009, 12, 1), 100.0
        for i in range(1200):
            d += timedelta(days=1)
            k = d.isoformat()
            bars[k] = {"open": c, "high": c + 0.6, "low": c - 0.6, "close": c + (0.2 if i % 2 else -0.2)}
            vol[k], term["VIX"][k], term["VIX3M"][k] = 16.0, 16.0, 18.0
            hourly[k] = [(c, c + 0.3, c - 0.3, c)] * 7
            c = bars[k]["close"]
        data = {"SPX": {"bars": bars, "vol": vol, "hourly": hourly}, "NDX": {"bars": bars, "vol": vol, "hourly": hourly}, "term": term, "vixh": {}}
        out = S.study(data, max(bars))
        self.assertEqual(len(out["rules"]), len(S.RULES))
        self.assertEqual(out["oos"][0], S.OOS_START)
        r = next(x for x in out["rules"] if x["id"] == "contango_hold")
        w = r["results"]["SPX"]["window"]
        self.assertEqual(w["stats"]["n"], 1)                                             # always in contango: one trade, held throughout
        self.assertGreater(w["stats"]["sessions_held"], 100)                             # (not a round trip every day)
        self.assertEqual(w["buy_hold"]["sessions"], w["stats"]["sessions_held"])          # in the market every session
        self.assertIn("oos", r["results"]["SPX"])
        self.assertTrue(r["results"]["SPX"]["now"]["in"])                               # and still in at the last close
        self.assertAlmostEqual(out["now"]["vix_vix3m"], 16 / 18, places=4)

    def test_gex_forward_hidden_until_30(self):
        path = [(100, 100.2, 98.9, 99.2)] + [(99.2, 100.1, 99.1, 100.0)] * 6               # dips to the put wall at 99, recovers
        sess = [{"session": "2026-10-21", "market": "ES", "plan": {"underlying": "SPX", "ref": 100.0, "em": 1.0, "regime": "POSITIVE",
                 "pw": 99.0, "cw": 103.0, "zg": 98.0, "ag": 100.0}, "outcome": {"open": 100}}]
        g = S.gex_forward(sess, {"SPX": {"2026-10-21": path}})
        wall = next(r for r in g["rules"] if r["id"] == "wall_fade")
        self.assertEqual(wall["stats"]["n"], 1)
        self.assertFalse(wall["passed"])
        self.assertIn("1 of 30", wall["why"])


if __name__ == "__main__":
    unittest.main()
