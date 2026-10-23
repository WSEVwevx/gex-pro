"""0DTE levels, volume/OI walls, max pain, expected-move bands, GEX profile, payload END marker."""
import math
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from gexsys import engine as eng
from gexsys import extras as ex
from gexsys.export import extras_tokens, parse_payload, pine_payload
from gexsys.levels import summarize
from gexsys.mapping import MappingContext, map_extras
from gexsys.marketcal import NY
from tests.util import ASOF, chain, contract

TUE_CLOSE = datetime(2026, 10, 20, 20, 0, tzinfo=timezone.utc)   # 16:00 ET


class TestMaxPain(unittest.TestCase):
    def test_hand_calculated(self):
        # calls OI 10 @100, puts OI 30 @110.  payout at 100: puts 30*10=300; at 105: 10*5 + 30*5 = 200;
        # at 110: calls 10*10 = 100  -> max pain 110
        cs = [contract(100, "C", oi=10), contract(110, "P", oi=30), contract(105, "C", oi=0)]
        self.assertEqual(ex.max_pain(cs), 110.0)

    def test_tie_takes_lower_and_empty(self):
        self.assertEqual(ex.max_pain([contract(100, "C", oi=5), contract(100, "P", oi=5)]), 100.0)
        self.assertIsNone(ex.max_pain([contract(100, "C", oi=0)]))

    def test_per_expiry(self):
        cs = [contract(100, "C", oi=10, days=1), contract(110, "P", oi=30, days=1),
              contract(100, "P", oi=50, days=8), contract(95, "C", oi=10, days=8)]
        snap = chain(cs)
        basket = sorted({c.expiration.date().isoformat() for c in cs})
        out = ex.max_pain_by_expiry(snap, basket)
        self.assertEqual([m["price"] for m in out], [110.0, 100.0])


class TestWalls(unittest.TestCase):
    def test_volume_and_oi_walls_near_money_only(self):
        cs = [replace(contract(100, "C", oi=100), volume=500.0), replace(contract(103, "C", oi=900), volume=900.0),
              replace(contract(150, "C", oi=99999), volume=5000.0),          # >5% away: ignored
              replace(contract(97, "P", oi=700), volume=300.0), replace(contract(99, "P", oi=50), volume=800.0),
              replace(contract(102, "P", oi=99999), volume=99999.0)]               # ITM put above price: ignored
        snap = chain(cs)
        w = ex.volume_and_oi_walls(snap, [cs[0].expiration.date().isoformat()])
        self.assertEqual(w["vol_call"]["price"], 103.0)
        self.assertEqual(w["vol_put"]["price"], 99.0)
        self.assertEqual(w["oi_call"]["price"], 103.0)
        self.assertEqual(w["oi_put"]["price"], 97.0)

    def test_call_wall_above_put_wall_below_by_default(self):
        # deep ITM call at 90 has the biggest call exposure, but the call wall must sit at/above price
        cs = [contract(90, "C", oi=9000, gamma=0.02), contract(105, "C", oi=1000, gamma=0.03),
              contract(110, "P", oi=9000, gamma=0.02), contract(95, "P", oi=1000, gamma=0.03)]
        s = summarize(eng.compute(chain(cs)))
        self.assertEqual(s["call_wall"]["price"], 105.0)
        self.assertEqual(s["put_wall"]["price"], 95.0)


class TestRatios(unittest.TestCase):
    def test_put_call_ratios_and_nearest_share(self):
        cs = [replace(contract(100, "C", oi=200, days=1), volume=100.0), replace(contract(100, "P", oi=300, days=1), volume=300.0),
              replace(contract(105, "C", oi=200, days=8), volume=100.0)]
        snap = chain(cs)
        basket = sorted({c.expiration.date().isoformat() for c in cs})
        r = ex.flow_ratios(snap, basket)
        self.assertAlmostEqual(r["pc_oi"], 300 / 400)
        self.assertAlmostEqual(r["pc_volume"], 300 / 200)
        self.assertAlmostEqual(r["nearest_volume_share"], 400 / 500)
        self.assertIsNone(ex.flow_ratios(chain([contract(100, "P", oi=5)]), [cs[0].expiration.date().isoformat()])["pc_oi"])


class TestNearest(unittest.TestCase):
    def test_label_0dte_vs_next(self):
        today = ASOF.replace(hour=20)           # expires 16:00 ET today
        cs = [contract(100, "C", oi=500, iv=0.2, exp=today), contract(100, "P", oi=500, iv=0.2, exp=today),
              contract(100, "C", oi=500, iv=0.2, days=7)]
        snap = chain(cs)
        res = eng.compute(snap)
        n = ex.nearest_expiry_levels(snap, eng.EngineConfig(), res)
        self.assertEqual(n["label"], "0DTE")
        self.assertEqual(n["expiration"], today.date().isoformat())
        res2 = eng.compute(snap, eng.EngineConfig(include_0dte=False))
        self.assertTrue(ex.nearest_expiry_levels(snap, eng.EngineConfig(include_0dte=False), res2)["label"].startswith("next "))


class TestExpectedMove(unittest.TestCase):
    def mk(self, spot=100.0, prev=98.0):
        cs = []
        for d in ("2026-10-21", "2026-10-23", "2026-11-20"):
            exp = datetime.fromisoformat(d + "T16:00:00").replace(tzinfo=NY)
            cs += [contract(100, "C", oi=10, iv=0.20, exp=exp), contract(100, "P", oi=10, iv=0.20, exp=exp)]
        return replace(chain(cs, spot=spot), prev_close=prev), ["2026-10-21", "2026-10-23", "2026-11-20"]

    def test_rth_anchor_is_previous_close(self):
        snap, basket = self.mk()
        em = ex.expected_moves(snap, basket, ASOF, snap.contracts)      # Tue 11:00 ET, RTH
        self.assertEqual(em["anchor"], 98.0)
        self.assertAlmostEqual(em["daily_points"], 98 * 0.2 * math.sqrt(1 / 252))
        self.assertEqual(em["weekly_expiry"], "2026-10-23")
        self.assertEqual(em["weekly_days"], 4)                         # Tue, Wed, Thu, Fri
        self.assertAlmostEqual(em["weekly_points"], 98 * 0.2 * math.sqrt(4 / 252))

    def test_index_options_preferred_over_converted_etf(self):
        # a converted ETF option sits closer to the money, but the band uses the index's own ATM IV
        snap, basket = self.mk(spot=100.4)
        etf = [replace(c, strike=100.4, group_strike=100.0, iv=0.15, symbol="X@IDX") for c in snap.contracts]
        em = ex.expected_moves(snap, basket, ASOF, snap.contracts + etf)
        self.assertAlmostEqual(em["daily_iv"], 0.20)
        self.assertAlmostEqual(ex.atm_iv(etf, "2026-10-21", 100.4), 0.15)      # ETF-only chain still works

    def test_after_close_anchor_is_last_price(self):
        snap, basket = self.mk()
        em = ex.expected_moves(snap, basket, TUE_CLOSE + timedelta(hours=3), snap.contracts)
        self.assertEqual(em["anchor"], 100.0)
        self.assertEqual(em["session"], "2026-10-21")

    def test_session_date_skips_weekend_and_holiday(self):
        fri_night = datetime(2026, 10, 23, 23, 0, tzinfo=timezone.utc)
        self.assertEqual(ex.session_date(fri_night), date(2026, 10, 26))
        wed_before_thanksgiving = datetime(2026, 11, 25, 22, 0, tzinfo=timezone.utc)
        self.assertEqual(ex.session_date(wed_before_thanksgiving), date(2026, 11, 27))


class TestProfile(unittest.TestCase):
    def test_bins_scale_and_round_trip(self):
        cs = [contract(100, "C", oi=1000, gamma=0.05), contract(98, "P", oi=500, gamma=0.05),
              contract(101, "C", oi=100, gamma=0.05)]
        res = eng.compute(chain(cs))
        p = ex.profile_bins(res)
        self.assertEqual(max(abs(v) for v in p["values"]), 99)
        i100 = round((100 - p["base"]) / p["width"])
        self.assertEqual(p["values"][i100], 99)
        self.assertLess(p["values"][round((98 - p["base"]) / p["width"])], 0)
        base, width, vals = extras_tokens({"profile": p})["P"].split("/")
        self.assertEqual(float(base), p["base"])
        self.assertEqual([int(v) for v in vals.split(",")], p["values"])


class TestPayloadAndMapping(unittest.TestCase):
    def summary(self):
        return {"asof": "2026-10-20T15:00:00+00:00", "ref_price": 5800.0, "ref_quality": "DL", "positioning": "conventional",
                "unit": "usd_per_1pct", "net": 1e9, "regime": "POSITIVE", "status": "OK", "zero_gamma_status": "",
                "basket": ["2026-10-20"], "concentrations": [],
                "extras": {"nearest": {"label": "0DTE", "zero_gamma": {"price": 5790.0}, "call_wall": {"price": 5850.0},
                                       "put_wall": {"price": 5750.0}},
                           "vol_call": {"price": 5825.0}, "vol_put": {"price": 5775.0},
                           "max_pain": [{"expiration": "2026-10-20", "price": 5800.0}, {"expiration": "2026-10-21", "price": 5810.0}],
                           "expected_move": {"anchor": 5790.0, "daily_points": 45.5, "weekly_points": 90.25, "weekly_expiry": "2026-10-23"},
                           "profile": {"base": 5650.0, "width": 10.0, "values": [0, -5, 99]}}}

    def test_tokens_and_end_marker(self):
        p = pine_payload(self.summary(), "ES", "SPX", "ratio", provider="CBOE")
        d = parse_payload(p)
        self.assertTrue(d["complete"])
        self.assertEqual((d["x0"], d["z0"], d["vc"], d["emd"], d["emx"]), ("0DTE", "5790.00", "5825.00", "45.50", "2026-10-23"))
        self.assertEqual(d["xp"], "2026-10-20:5800.00,2026-10-21:5810.00")
        self.assertEqual(d["P"], "5650/10/0,-5,99")
        self.assertFalse(parse_payload(p[: len(p) // 2])["complete"])      # a cut-off paste is detectable

    def test_map_extras(self):
        t = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
        ctx = MappingContext("ES", "SPX", "ratio", 5858.0, t, 5800.0, t)
        m = map_extras(self.summary()["extras"], ctx, 0.25)
        self.assertEqual(m["vol_call"]["src_price"], 5825.0)
        self.assertEqual(m["vol_call"]["price"], round(5825 * 1.01 * 4) / 4)
        self.assertAlmostEqual(m["expected_move"]["daily_points_fut"], 45.5 * 1.01)
        self.assertAlmostEqual(m["profile"]["width_fut"], 10.1)
        self.assertEqual(m["max_pain"][1]["src_price"], 5810.0)


if __name__ == "__main__":
    unittest.main()
