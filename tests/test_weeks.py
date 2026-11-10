"""A week of 9:30 pastes as one paste (trackrecord/weeks.py), as the indicator's W token reads it."""
import unittest

from trackrecord.weeks import day_entry, week_paste, weeks


def paste(day, zg="28000", cw="28500", extra=""):
    return f"GEX1;fv=5;prov=CBOE;mkt=NQ;src=NDX;tv=NASDAQ:NDX;map=ratio;fac=0;ts=1;st=OK;zg={zg};cw={cw};pw=27500;ag=27900;R=C28500:4,C28600:2,C28700:1,C28800:1,P27500:5,P27400:3{extra};bt={day};END"


class TestWeek(unittest.TestCase):
    def test_day_entry_keeps_the_top_three_each_side(self):
        self.assertEqual(day_entry(paste("20261102")), "20261102:28000:28500:27500:27900:28500/28600/28700:27500/27400")

    def test_week_paste_in_day_order_with_the_last_day_marked(self):
        w = week_paste([paste("20261104"), paste("20261102", zg="")])
        self.assertTrue(w.startswith("GEX1;fv=5;prov=CBOE;mkt=NQ;src=NDX;tv=NASDAQ:NDX;map=ratio;") and w.endswith(";END"))
        self.assertIn(";bt=20261104;", w)
        self.assertIn("W=20261102::28500:", w)                     # a missing level stays an empty field
        self.assertLess(w.index("20261102:"), w.index("20261104:"))
        self.assertNotIn("zg=", w)                                  # no live levels: only the week is drawn

    def test_weeks_group_by_monday_and_market(self):
        ps = [{"session": "2026-11-02", "market": "NQ", "paste": paste("20261102")},
              {"session": "2026-11-06", "market": "NQ", "paste": paste("20261106")},
              {"session": "2026-11-09", "market": "NQ", "paste": paste("20261109")},
              {"session": "2026-11-09", "market": "ES", "paste": "not a paste"}]
        got = weeks(ps)
        self.assertEqual([(w["week"], w["market"], w["days"]) for w in got], [("2026-11-09", "NQ", 1), ("2026-11-02", "NQ", 2)])


if __name__ == "__main__":
    unittest.main()
