"""Strategy lab: order simulation (worst case inside a bar), option pricing, rules, verdicts, live mapping."""
import unittest

from trackrecord import strategies as S


def day(ref=100.0, em=1.0, path=None, regime="calm", date="2026-01-02", prev="2026-01-01"):
    path = path or [(100, 101, 99, 100)]
    return {"date": date, "date_prev": prev, "ref": ref, "em": em, "o": path[0][0], "h": max(p[1] for p in path),
            "l": min(p[2] for p in path), "c": path[-1][3], "path": path, "regime": regime}


class TestTrade(unittest.TestCase):
    def test_limit_fill_then_close(self):
        self.assertEqual(S.trade([(100, 100.5, 98.5, 99.5)], +1, 99, "limit", 98), 0.5)
        self.assertIsNone(S.trade([(100, 100.5, 99.5, 100)], +1, 99, "limit", 98))

    def test_stop_in_fill_bar_is_worst_case(self):
        self.assertEqual(S.trade([(100, 100.5, 97.5, 99.5)], +1, 99, "limit", 98), -1.0)   # low under the stop: stopped
        self.assertEqual(S.trade([(97, 99, 96, 98)], +1, 99, "limit", 98), 0.0)             # opened at 97, under the stop: filled and out at once
        self.assertEqual(S.trade([(97, 99, 96.5, 98)], +1, 99, "limit", 97.5), min(0.0, 97.5 - 97))

    def test_stop_before_target_in_one_bar(self):
        # opened at the open: one bar touching both the target (101) and the stop (99) counts as stopped
        self.assertEqual(S.trade([(100, 101.5, 98.5, 100)], +1, None, "open", 99, 101), -1.0)
        # hour by hour the target comes first
        self.assertEqual(S.trade([(100, 101.5, 99.5, 101), (101, 101, 98.5, 99)], +1, None, "open", 99, 101), 1.0)

    def test_short_stop_entry_and_gap_through_stop(self):
        self.assertEqual(S.trade([(100, 100.2, 98.8, 99.0)], -1, 99.5, "stop", 101), 0.5)
        self.assertEqual(S.trade([(100, 100, 99, 99.4), (102, 103, 101.5, 102)], -1, 99.5, "stop", 101), 99.5 - 102)   # opened through the stop


class TestPricing(unittest.TestCase):
    def test_atm_straddle_and_wings(self):
        ref, em = 100.0, 1.0
        self.assertAlmostEqual(S.option_pair(ref, em, 0.0), ref * (2 * S._ncdf(0.005) - 1) * 2, places=6)   # BS ATM straddle
        self.assertAlmostEqual(S.option_pair(ref, em, 0.0), 0.7979 * em, places=3)                            # ~0.8 sigma
        self.assertGreater(S.option_pair(ref, em, 1.0), S.option_pair(ref, em, 2.0))

    def test_condor_loss_is_capped(self):
        d = day(path=[(100, 106, 99, 105)])                                          # a 5-em day
        credit = (S.option_pair(100, 1) - S.option_pair(100, 1, 2.0)) * (1 - S.OPTION_COST)
        self.assertAlmostEqual(S.iron_condor([d], 0)[0], credit - 1.0)
        self.assertAlmostEqual(S.short_strangle([d], 0)[0], S.option_pair(100, 1) * (1 - S.OPTION_COST) - 4.0)
        quiet = day(path=[(100, 100.5, 99.6, 100.2)])
        self.assertAlmostEqual(S.iron_condor([quiet], 0)[0], credit)


class TestRules(unittest.TestCase):
    def test_close_reversal_needs_the_next_session(self):
        d1 = day(path=[(100, 100, 98, 98.5)], date="2026-01-02")                     # closed 1.5 em below
        d2 = day(ref=98.5, path=[(98.5, 99.5, 98, 99.2)], date="2026-01-05", prev="2026-01-02")
        self.assertAlmostEqual(S.close_reversal([d1, d2], 0)[0], 0.7)
        self.assertAlmostEqual(S.close_follow([d1, d2], 0)[0], -0.7)
        self.assertEqual(S.close_reversal([d1], 0), [])
        gap = dict(d2, date_prev="2026-01-01")                                       # a missing day in between: no trade
        self.assertEqual(S.close_reversal([d1, gap], 0), [])

    def test_gap_rules(self):
        up = day(path=[(100.8, 101.0, 99.9, 100.5)])                                 # +0.8 em gap that filled
        self.assertAlmostEqual(S.gap_fade([up], 0)[0], 0.8)
        self.assertAlmostEqual(S.gap_and_go([up], 0)[0], -0.8)                       # stopped at the previous close
        self.assertEqual(S.gap_fade([day(path=[(100.2, 101, 99, 100)])], 0), [])

    def test_regime_filter_and_costs(self):
        days = [day(regime="calm"), day(regime="stressed", date="2026-01-05", prev="2026-01-02")]
        self.assertEqual(len(S.run(days, S.short_strangle, 0.0, "calm")), 1)
        self.assertEqual(S.run(days[:1], S.gap_and_go, 0.5), [])                      # no gap: no trade
        (d, pts, r), = S.run(days[:1], S.short_strangle, 0.25)
        self.assertAlmostEqual(r, pts / 1.0, places=3)


class TestVerdict(unittest.TestCase):
    def test_rules(self):
        good = {"n": 100, "avg_r": 0.1, "t": 3.0}
        self.assertEqual(S.verdict(good, [{"n": 50, "avg_r": 0.05}, {"n": 50, "avg_r": 0.1}]), "holds up")
        self.assertEqual(S.verdict(good, [{"n": 50, "avg_r": -0.05}, {"n": 50, "avg_r": 0.2}]), "mixed")
        self.assertEqual(S.verdict(dict(good, t=1.5), [{"n": 50, "avg_r": 0.05}] * 2), "mixed")
        self.assertEqual(S.verdict(dict(good, avg_r=-0.01), [{"n": 50, "avg_r": 0.05}] * 2), "does not work")
        self.assertEqual(S.verdict({"n": 10, "avg_r": 1, "t": 9}, []), "too few trades")

    def test_history_end_to_end(self):
        bars, vol = {}, {}
        c = 100.0
        from datetime import date, timedelta
        d = date(2020, 1, 1)
        for i in range(400):
            d += timedelta(days=1)
            bars[d.isoformat()] = {"open": c, "high": c + 0.6, "low": c - 0.6, "close": c + (0.3 if i % 2 else -0.3)}
            vol[d.isoformat()] = 16.0 + (i % 7)
            c = bars[d.isoformat()]["close"]
        h = S.history("SPX", bars, vol)
        self.assertEqual(h["sessions"], 399 - S.REGIME_LOOKBACK)
        r = h["strategies"]["iron_condor"]
        self.assertEqual(r["verdict"], "holds up")                                   # quiet market: the band always holds
        self.assertEqual(r["stats"]["win"], 1.0)
        self.assertEqual(r["verdict_basis"], "daily")
        self.assertAlmostEqual(h["strategies"]["band_fade"]["stats"].get("n", 0), 0)  # the band is never reached


class TestLive(unittest.TestCase):
    def test_gex_regime_drives_the_filter(self):
        def sess(d, regime, o):
            return {"session": d, "market": "ES", "status": "graded",
                    "plan": {"ref": 100.0, "em": 1.0, "regime": regime, "underlying": "SPX"},
                    "outcome": {"open": o[0], "high": o[1], "low": o[2], "close": o[3]}}
        out = S.live([sess("2026-10-21", "POSITIVE", (100, 100.5, 99.5, 100.2)), sess("2026-10-22", "NEGATIVE", (100.8, 101.5, 100.5, 101.4))])
        self.assertEqual(out["iron_condor"]["n"], 1)                                 # positive gamma only
        self.assertEqual(out["gap_and_go"]["n"], 1)                                  # negative gamma, 0.8 em gap
        self.assertAlmostEqual(out["gap_and_go"]["trades"][0]["pts"], 101.4 - 100.8 - S.COST["SPX"], places=3)


if __name__ == "__main__":
    unittest.main()
