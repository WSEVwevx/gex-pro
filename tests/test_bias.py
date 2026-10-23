"""Bias engine: scenarios with known answers, path/cone geometry, and session timing."""
import math
import unittest
from datetime import datetime

from gexsys.bias import compute, session_window
from gexsys.marketcal import NY

TUE_1100 = datetime(2026, 10, 20, 11, 0, tzinfo=NY)


def levels(ref=20000.0, zg=19800.0, cw=20300.0, pw=19700.0, ag=20100.0, charm=5e8, vanna=1e8, em=200.0,
           near="0DTE", mp=20050.0):
    return {"status": "OK", "regime": "POSITIVE", "futures_equiv_of_ref": ref,
            "zero_gamma": {"price": zg} if zg is not None else None, "call_wall": {"price": cw}, "put_wall": {"price": pw},
            "abs_gamma": {"price": ag}, "max_positive": {"price": ag},
            "extras": {"expected_move": {"daily_points_fut": em},
                       "greeks": {"charm_flow_usd_per_day": charm, "vanna_usd_per_vol_pt": vanna},
                       "nearest": {"label": near}, "max_pain": [{"expiration": "2026-10-20", "price": mp}]}}


class TestBiasScenarios(unittest.TestCase):
    def test_positive_gamma_magnet_above_is_bullish_range_day(self):
        b = compute(levels(), TUE_1100)
        self.assertEqual(b["side"], "positive")                        # (20000 - 19800) / 200 = 1.0 sigma above
        self.assertEqual(b["day_type"], "Range / mean reversion")
        self.assertEqual(b["bias"], "Bullish")
        # magnet +0.4*... : (20100-20000)/(100) = 1 -> +1.0; charm +1; vanna +0.5 (IV eases, v>0); max pain +0.25
        self.assertAlmostEqual(b["score"], 1.0 + 1.0 + 0.5 + 0.25)
        self.assertEqual(b["confidence"], "High")
        self.assertEqual(b["target"], 20100.0)                         # settles on the magnet
        self.assertEqual(b["range"], [19860.0, 20140.0])               # +/-0.7 sigma; walls are outside it

    def test_negative_gamma_with_selling_is_bearish_trend_day(self):
        b = compute(levels(ref=19600.0, zg=19800.0, ag=19650.0, charm=-5e8, vanna=1e8, near="next 10-21"), TUE_1100)
        self.assertEqual(b["side"], "negative")                        # 1 sigma below zero gamma
        self.assertEqual(b["day_type"], "Trend / expansion")
        self.assertEqual(b["bias"], "Bearish")                         # magnet +0.25, charm -1, vanna (IV rises) -0.5
        self.assertAlmostEqual(b["target"], 19600.0 - 0.8 * 200)
        self.assertEqual(b["range"], [19600.0 - 240.0, 19600.0 + 160.0])

    def test_pivot_day_is_low_confidence_and_targets_zero_gamma(self):
        b = compute(levels(ref=19820.0, zg=19800.0, charm=0, vanna=0, mp=19820.0, ag=19830.0), TUE_1100)
        self.assertEqual((b["side"], b["bias"]), ("pivot", "Neutral"))
        self.assertEqual(b["confidence"], "Low")
        self.assertEqual(b["target"], 19800.0)
        self.assertIn("losing it", b["summary"])

    def test_base_case_always_agrees_with_the_bias(self):
        # pivot day just above zero gamma, but charm buying + put-wall support = bullish: path must not fall to ZG
        b = compute(levels(ref=19820.0, zg=19800.0, pw=19790.0, ag=19700.0, vanna=0, mp=19820.0), TUE_1100)
        self.assertEqual((b["side"], b["bias"]), ("pivot", "Bullish"))
        self.assertGreater(b["target"], 19820.0)
        # range day whose magnet sits above, outvoted by selling flows: bearish, so the target is below price
        b = compute(levels(ref=20000.0, zg=19800.0, cw=20040.0, ag=20030.0, charm=-5e8, vanna=-1e8, mp=19950.0), TUE_1100)
        self.assertEqual(b["bias"], "Bearish")
        self.assertLess(b["target"], 20000.0)
        for p in (b["path"][i][1] for i in range(1, len(b["path"]))):
            self.assertLessEqual(p, 20000.0)

    def test_walls_close_by_count(self):
        b = compute(levels(ref=20260.0, zg=19800.0, cw=20300.0, ag=20100.0, charm=0, vanna=0), TUE_1100)
        names = {f["name"]: f["score"] for f in b["factors"]}
        self.assertEqual(names["Call wall overhead"], -0.5)            # 40 pts < 0.25 * 200

    def test_unavailable_or_missing_expected_move(self):
        self.assertIsNone(compute({"status": "UNAVAILABLE"}, TUE_1100))
        lv = levels()
        lv["extras"]["expected_move"] = {}
        self.assertIsNone(compute(lv, TUE_1100))


class TestPathAndSession(unittest.TestCase):
    def test_live_path_starts_now_and_ends_on_target(self):
        b = compute(levels(), TUE_1100)
        self.assertTrue(b["session"]["live"])
        self.assertEqual(b["session"]["start_minute"], 90)            # 11:00 is 90 minutes after the open
        self.assertEqual(b["path"][0], [90, 20000.0])
        self.assertEqual(b["path"][-1], [390, 20100.0])
        m, lo, hi = b["cone"][-1]
        self.assertAlmostEqual(hi - 20000.0, 200 * math.sqrt(300 / 390), places=1)   # sigma * sqrt(remaining / day)

    def test_after_close_plans_next_session_from_the_open(self):
        o, c, start, live = session_window(datetime(2026, 10, 23, 18, 0, tzinfo=NY))   # Friday evening
        self.assertEqual((o.date().isoformat(), live, start), ("2026-10-26", False, o))
        b = compute(levels(), datetime(2026, 10, 23, 18, 0, tzinfo=NY))
        self.assertEqual(b["path"][0][0], 0)

    def test_early_close_session_is_shorter(self):
        o, c, _, _ = session_window(datetime(2026, 11, 27, 10, 0, tzinfo=NY))
        self.assertEqual((c - o).total_seconds() / 60, 210)            # 09:30 to 13:00


if __name__ == "__main__":
    unittest.main()
