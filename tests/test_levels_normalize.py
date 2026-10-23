import unittest
from dataclasses import replace
from datetime import timedelta

from gexsys import engine as eng
from gexsys.levels import LevelConfig, summarize
from gexsys.normalize import normalize, parse_occ
from tests.util import ASOF, chain, contract


class TestLevels(unittest.TestCase):
    def setUp(self):
        cs = [contract(95, "P", oi=5000, gamma=0.04), contract(100, "P", oi=1000, gamma=0.05),
              contract(100, "C", oi=1500, gamma=0.05), contract(105, "C", oi=4000, gamma=0.04),
              contract(110, "C", oi=100, gamma=0.01)]
        self.s = summarize(eng.compute(chain(cs), eng.EngineConfig(unit="delta_per_point")),
                           LevelConfig(top_n=3, min_share=0.05))

    def test_walls_use_side_magnitude(self):
        self.assertEqual(self.s["call_wall"]["price"], 105.0)     # 4000*0.04*100 = 16000
        self.assertEqual(self.s["put_wall"]["price"], 95.0)       # 5000*0.04*100 = 20000
        self.assertAlmostEqual(self.s["put_wall"]["value"], 20000.0)
        self.assertEqual(self.s["call_wall"]["metric"], "|call exposure|")

    def test_max_positive_negative(self):
        self.assertEqual(self.s["max_positive"]["price"], 105.0)
        self.assertEqual(self.s["max_negative"]["price"], 95.0)

    def test_concentrations_ranked_and_thresholded(self):
        prices = [c["price"] for c in self.s["concentrations"]]
        self.assertEqual(prices[:2], [95.0, 105.0])
        self.assertLessEqual(len(prices), 3)
        self.assertNotIn(110.0, prices)       # 100/41600 share < 5%

    def test_unavailable_summary_has_no_levels(self):
        s = summarize(eng.compute(chain([contract(100, "C", oi=0, gamma=0.1)])))
        self.assertEqual(s["status"], "UNAVAILABLE")
        self.assertIsNone(s["call_wall"])
        self.assertEqual(s["concentrations"], [])


class TestNormalize(unittest.TestCase):
    def test_occ_parse(self):
        p = parse_occ("SPXW261020C05800000")
        self.assertEqual((p["root"], p["strike"], p["type"].value), ("SPXW", 5800.0, "C"))
        self.assertEqual(parse_occ("O:QQQ261023P00487500")["strike"], 487.5)
        for bad in ("SPXW26102C05800000", "SPX261340C05800000", "", "NOTASYMBOL"):
            self.assertIsNone(parse_occ(bad))

    def test_duplicates_keep_latest(self):
        a = contract(100, "C", oi=10, gamma=0.01)
        b = replace(a, open_interest=20, greeks_time=ASOF)
        n = normalize(chain([a, b]))
        self.assertEqual(len(n.contracts), 1)
        self.assertEqual(n.contracts[0].open_interest, 20)
        self.assertTrue(any("duplicate" in w for w in n.warnings))

    def test_invalid_symbols_and_mismatch(self):
        exp = ASOF.replace(hour=20)
        good = contract(5800, "C", gamma=0.001, exp=exp, root="SPXW", symbol="SPXW261020C05800000")
        bad = contract(5800, "P", gamma=0.001, exp=exp, root="SPXW", symbol="GARBAGE")
        mism = contract(5805, "C", gamma=0.001, exp=exp, root="SPXW", symbol="SPXW261020C05800000")
        n = normalize(chain([good, bad, mism]), check_occ=True)
        self.assertEqual(len(n.contracts), 1)

    def test_bad_fields_become_none(self):
        c = contract(100, "C", oi=-5, gamma=-0.1, iv=9.0, bid=2.0, ask=1.0)
        n = normalize(chain([c, contract(-1, "C"), replace(contract(100, "P"), multiplier=0)]))
        self.assertEqual(len(n.contracts), 1)
        x = n.contracts[0]
        self.assertIsNone(x.open_interest)
        self.assertIsNone(x.gamma)
        self.assertIsNone(x.iv)
        self.assertIsNone(x.bid)

    def test_stale_quote_marked(self):
        from gexsys.models import Quality
        c = replace(contract(100, "C"), last_time=ASOF - timedelta(hours=1), quote_quality=Quality.DELAYED)
        n = normalize(chain([c]), max_quote_age_s=600, now=ASOF)
        self.assertEqual(n.contracts[0].quote_quality, Quality.STALE)


if __name__ == "__main__":
    unittest.main()
