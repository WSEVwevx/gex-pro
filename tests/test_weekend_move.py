"""Study weekend_move (tools/stress/weekend_move.py): its rules on hand-made data, and its frozen definition."""
import math
import unittest
from datetime import date

from tools.stress import weekend_move as wm

ROW = {"SPX": 100.0, "NDX": 200.0, "VIX1D": 20.0, "VIX9D": 20.0, "VIX": 20.0, "VIX3M": 20.0, "VXN": 30.0}


class WeekendMove(unittest.TestCase):
    def test_both_rules_by_hand(self):
        a, b = wm.sigmas(ROW, "SPX", 3.0)
        self.assertAlmostEqual(a, 0.20 * math.sqrt(3 / 365))                # a flat curve
        self.assertAlmostEqual(b, 0.20 / math.sqrt(252))
        a, b = wm.sigmas(ROW, "NDX", 1.0)
        self.assertAlmostEqual(a, 0.30 * math.sqrt(1 / 365))                # x VXN / VIX = 1.5
        self.assertAlmostEqual(b, 0.30 / math.sqrt(252))
        a, _ = wm.sigmas(dict(ROW, VIX1D=40.0), "SPX", 3.0)                 # w = 0.16 + (0.04 x 9 - 0.16) x 2 / 8
        self.assertAlmostEqual(a, math.sqrt((0.16 + 0.2 * 2 / 8) / 365))

    def test_pairs_gaps_groups_and_drops(self):
        days = [date(2026, 11, d) for d in (18, 19, 20, 23, 24, 25, 27, 30)]
        rows = {d: dict(ROW, SPX=100.0 + i) for i, d in enumerate(days)}
        ps, dropped = wm.pairs(rows, "SPX", date(2026, 11, 18), date(2026, 11, 30))
        self.assertEqual([(p["d"].day, p["n"].day, p["gap"]) for p in ps],
                         [(18, 19, 1), (19, 20, 1), (20, 23, 3), (23, 24, 1), (24, 25, 1), (25, 27, 2), (27, 30, 3)])
        self.assertEqual(dropped, 0)
        self.assertEqual([p["d"].day for p in wm.group(ps, "primary")], [20])           # 27 Nov closes at 13:00
        self.assertEqual([p["d"].day for p in wm.group(ps, "early")], [25, 27])
        self.assertEqual(wm.group(ps, "two_day"), [])
        self.assertEqual(len(wm.group(ps, "ordinary")), 4)
        self.assertAlmostEqual(ps[2]["r"], math.log(103 / 102))
        self.assertAlmostEqual(ps[2]["t"], 3.0)
        p = ps[2]

        def q(s):
            return p["r"] ** 2 / s ** 2 + math.log(s ** 2)
        self.assertAlmostEqual(p["diff"], q(p["a"]) - q(p["b"]))
        gone = {d: dict(r) for d, r in rows.items()}
        del gone[date(2026, 11, 20)]["VIX9D"]                                           # no vol on the close day
        ps, dropped = wm.pairs(gone, "SPX", date(2026, 11, 18), date(2026, 11, 30))
        self.assertEqual((len(ps), dropped), (6, 1))

    def test_a_result_never_uses_a_later_vol(self):
        rows = {date(2026, 11, 19): dict(ROW), date(2026, 11, 20): dict(ROW, VIX1D=99.0, VIX=99.0, VXN=99.0)}
        (p,), _ = wm.pairs(rows, "SPX", date(2026, 11, 19), date(2026, 11, 20))
        self.assertAlmostEqual(p["b"], 0.20 / math.sqrt(252))

    def test_the_interval_draws_whole_weeks(self):
        ps = [{"d": d, "diff": x} for d, x in ((date(2026, 11, 2), 1.0), (date(2026, 11, 3), 1.0), (date(2026, 11, 9), 1.0))]
        self.assertEqual(wm.interval(ps, 1, 200), (1.0, 1.0))
        ps = [{"d": date(2026, 11, 2), "diff": 0.0}, {"d": date(2026, 11, 9), "diff": 4.0}]
        self.assertEqual(wm.interval(ps, 1, 400), (0.0, 4.0))                           # two weeks: 0, 2 or 4
        self.assertEqual(wm.interval(ps, 1, 400), wm.interval(ps, 1, 400))              # a fixed seed
        self.assertEqual((10000 // 40 - 1, 10000 - 10000 // 40 - 1), (249, 9749))       # the ends named in the definition

    def test_every_condition_must_hold(self):
        def pair(d, gap, r, a, b, diff):
            return {"d": d, "n": d, "gap": gap, "r": r, "a": a, "b": b, "diff": diff, "early": False, "roll": False}
        weeks = [date(2026, 1, 2 + 7 * i) for i in range(4)]
        prim = [pair(d, 3, r, 9.0, 1.0, 1.0) for d, r in zip(weeks, (0.5, 0.5, 0.5, 2.0))]     # A holds 100%, B 75%
        ordi = [pair(d, 1, 0.5, 1.0, 1.0, 0.0) for d in weeks]
        self.assertEqual(list(wm.conditions(prim + ordi, 1, 400).values()), [True, True, True, True])
        worse = [dict(p, diff=-1.0) for p in prim]
        self.assertEqual(list(wm.conditions(worse + ordi, 1, 400).values()), [False, False, True, True])
        bad_nights = [dict(p, diff=-1.0) for p in ordi]
        self.assertEqual(list(wm.conditions(prim + bad_nights, 1, 400).values()), [True, True, True, False])
        same = [dict(p, b=9.0) for p in prim]                                            # equal coverage is not closer
        self.assertFalse(list(wm.conditions(same + ordi, 1, 400).values())[2])

    def test_wilson(self):
        lo, hi = wm.wilson(50, 100)
        self.assertAlmostEqual(lo, 0.4038, places=4)
        self.assertAlmostEqual(hi, 0.5962, places=4)

    def test_the_definition_is_frozen(self):
        d, sha = wm.definition()
        self.assertEqual(sha, "9d53ae9b8914480cb465b5222f12ce2622a47b13000c1e6a75ce5229a82ba25c")
        self.assertGreater(len(wm.read_inputs(d)), 1000)                                # its hash matches the definition


if __name__ == "__main__":
    unittest.main()
