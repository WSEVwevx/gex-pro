"""Level reaction study: touch / outcome rules on synthetic days with known answers, and the random baseline."""
import json
import unittest
from datetime import date

from trackrecord import reactions as R


def rec(path, session="2026-11-04", market="NQ", open_=1000.0, em=100.0, underlying="NDX"):
    """A session whose futures equal the index (ratio 1): path = closes per minute from 09:30."""
    bars = [[m, max(p, path[m - 1] if m else p), min(p, path[m - 1] if m else p), p] for m, p in enumerate(path)]
    return {"session": session, "market": market, "underlying": underlying, "index_open": open_, "ratio": 1.0, "em": em, "bars": bars}


def walk(*legs, start=1000.0):
    """Straight-line path through (minutes, price) legs, 390 minutes long."""
    out, p = [start], start
    for mins, target in legs:
        step = (target - p) / mins
        for _ in range(mins):
            p += step
            out.append(p)
    return (out + [p] * 390)[:390]


class TestReact(unittest.TestCase):
    def test_bounce_off_a_level_above(self):
        r = R.react(rec(walk((10, 1020), (20, 990))), 1020.0)        # up to 1020 at 09:40, then quickly back down
        self.assertEqual((r["side"], r["touched"], r["minute"]), (1, True, 10))
        self.assertEqual(r["out"], {5: "bounce", 15: "bounce", 60: "bounce"})

    def test_break_through_a_level_below(self):
        r = R.react(rec(walk((10, 980), (60, 940))), 980.0)
        self.assertEqual((r["side"], r["out"][5], r["out"][60]), (-1, "break", "break"))

    def test_stall_and_horizon_past_the_close(self):
        r = R.react(rec(walk((360, 1020))), 1020.0)                   # reaches it at 15:30 and stays there
        self.assertEqual(r["out"], {5: "stall", 15: "stall"})           # no 60-minute result: it would end after 16:00

    def test_level_at_the_open_and_untouched_level(self):
        self.assertIsNone(R.react(rec(walk((10, 1005))), 1000.5))       # within the touch distance at the open: no side
        self.assertFalse(R.react(rec(walk((10, 1005))), 1050.0)["touched"])

    def test_futures_mapping_uses_the_open_ratio(self):
        r = rec(walk((10, 1022))); r["ratio"] = 1.002                  # futures 0.2% over the index
        self.assertTrue(R.react(r, 1020.0)["touched"])                  # the level sits at 1022.04 in futures
        self.assertFalse(R.react(dict(r, bars=[b for b in r["bars"] if b[1] < 1021]), 1020.0)["touched"])


class TestLevels(unittest.TestCase):
    def test_plan_and_paste_levels(self):
        plan = {"zg": 1010.0, "cw": 1050.0, "pw": 950.0, "ag": 950.0}
        paste = "GEX1;R=C1050.00:4.0,C1030.00:1.2,P950.00:9.0,P960.00:3.0,A1000.00:5;z0=1005;c0=1030;p0=0;ema=1000;emd=40;vc=1060;END"
        lv = R.session_levels(plan, paste)
        self.assertIn(("calls", 1030.0), lv)
        self.assertNotIn(("calls", 1050.0), lv)                         # already the call wall
        self.assertIn(("puts", 960.0), lv)
        self.assertIn(("em", 1040.0), lv)
        self.assertIn(("em", 960.0), lv)
        self.assertNotIn(("odte", 0.0), lv)                             # a zero is a missing value, not a level
        self.assertEqual(R.session_levels(plan), [("zg", 1010.0), ("cw", 1050.0), ("pw", 950.0), ("ag", 950.0)])


class TestStudy(unittest.TestCase):
    def days(self, n, bounce_at_level):
        """n sessions; every day price rises to 1020 then falls back. The level sits at 1020 (a bounce), the
        random strikes land at the same distance on other days, which see the same bounce, so no edge."""
        recs, levels = [], {}
        for i in range(n):
            s = f"2026-10-{i + 1:02d}"
            path = walk((10, 1020), (60, 990)) if bounce_at_level else walk((10, 1020), (60, 1060))
            recs.append(rec(path, session=s))
            levels[(s, "NQ")] = [("cw", 1020.0)]
        return recs, levels

    def test_same_tape_everywhere_is_no_edge(self):
        recs, levels = self.days(20, True)
        res = R.summarize(R.observations(recs, levels))
        cw = next(t for t in res["types"] if t["type"] == "cw")["h"]["15"]
        self.assertEqual(cw["touches"], 20)
        self.assertEqual(cw["bounce"]["rate"], 1.0)
        self.assertEqual(cw["verdict"], "few" if cw["touches"] < R.MIN_TOUCHES else "none")   # random strikes did the same

    def test_level_that_holds_where_random_strikes_do_not(self):
        # price tags the level and turns; on the other days the same distance is crossed on the way to 1060
        recs, levels = [], {}
        for i in range(24):
            s = f"2026-10-{i + 1:02d}"
            lvl = 1020.0 + 4 * (i % 2)                                   # alternate 1020 / 1024 so the strikes differ
            recs.append(rec(walk((10, lvl), (60, 990)), session=s))
            levels[(s, "NQ")] = [("cw", lvl)]
        res = R.summarize(R.observations(recs, levels))
        cw = next(t for t in res["types"] if t["type"] == "cw")["h"]["15"]
        self.assertEqual(cw["bounce"]["rate"], 1.0)
        self.assertLess(cw["bounce"]["random"], 1.0)
        self.assertEqual(cw["verdict"], "bounce")

    def test_random_strike_on_a_real_level_is_dropped(self):
        recs = [rec(walk((10, 1020), (60, 990)), session="2026-10-01"), rec(walk((10, 1020), (60, 990)), session="2026-10-02")]
        levels = {("2026-10-01", "NQ"): [("cw", 1020.0)], ("2026-10-02", "NQ"): [("pw", 1020.0)]}
        obs = R.observations(recs, levels)
        self.assertEqual([o for o in obs if not o["real"]], [])          # the only same-distance strike is a real level

    def test_minutes_record_and_parse(self):
        ts0 = 1793802600                                                  # 2026-11-04 09:30 ET
        raw = {"chart": {"result": [{"timestamp": [ts0 - 60, ts0, ts0 + 60, ts0 + 390 * 60],
                                     "indicators": {"quote": [{"open": [1, 2002, 2003, 9], "high": [1, 2004, 2005, 9],
                                                               "low": [1, 2001, 2002, 9], "close": [1, 2003, 2004, 9]}]}}]}}
        bars = R.parse_minutes(json.dumps(raw).encode(), date(2026, 11, 4))
        self.assertEqual([b[0] for b in bars], [0, 1])                    # before 09:30 and from 16:00 are dropped
        r = R.minutes_record({"session": "2026-11-04", "market": "NQ", "plan": {"em": 50.0, "underlying": "NDX"},
                              "outcome": {"open": 2000.0}}, bars)
        self.assertEqual((r["ratio"], r["bars"][0]), (1.001, [0, 2004.0, 2001.0, 2003.0]))


if __name__ == "__main__":
    unittest.main()
