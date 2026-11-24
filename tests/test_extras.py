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
from gexsys.models import OptionType
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

    def test_first_expiry_rankings_index_and_etf(self):
        today = ASOF.replace(hour=20)
        idx = [contract(100, "C", oi=500, iv=0.2, exp=today), contract(100, "P", oi=500, iv=0.2, exp=today)]
        # converted ETF legs: exact strike = ETF strike x ratio, grouped onto the index grid
        etf = [replace(contract(101.3, "C", oi=40000, iv=0.2, exp=today), group_strike=101.0, symbol="Q1@TST"),
               replace(contract(98.7, "P", oi=30000, iv=0.2, exp=today), group_strike=99.0, symbol="Q2@TST")]
        snap = chain(idx + etf)
        n = ex.nearest_expiry_levels(snap, eng.EngineConfig(), eng.compute(snap))
        self.assertEqual(n["ranked_etf"]["call"][0]["price"], 101.3)        # the ETF's own strike, not the index grid
        self.assertEqual(n["ranked_etf"]["put"][0]["price"], 98.7)
        self.assertGreater(n["etf_share"], 0.5)                              # the ETF legs hold most of the gamma
        self.assertTrue(n["ranked"]["call"])


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
        # no Tuesday expiration: per-session average of the variance to Wed 16:00 (29 h, 2 sessions)
        self.assertAlmostEqual(em["daily_points"], 100 * math.sqrt(0.2 ** 2 * (29 / 8760) / 2))
        self.assertEqual(em["weekly_expiry"], "2026-10-23")
        self.assertEqual(em["weekly_days"], 4)                         # Tue, Wed, Thu, Fri
        self.assertAlmostEqual(em["weekly_points"], 100 * math.sqrt(0.2 ** 2 * (77 / 8760)))   # to Fri 16:00
        # monthly: through the third Friday of November (October's was the 16th, already past)
        nov = datetime.fromisoformat("2026-11-20T16:00:00").replace(tzinfo=NY)
        self.assertEqual((em["monthly_expiry"], em["monthly_iv"]), ("2026-11-20", 0.20))
        self.assertAlmostEqual(em["monthly_points"], 100 * math.sqrt(0.2 ** 2 * (nov - ASOF).total_seconds() / (8760 * 3600)))

    def test_rth_full_session_is_forward_variance(self):
        exp = lambda d: datetime.fromisoformat(d + "T16:00:00").replace(tzinfo=NY)
        cs = [contract(100, cp, oi=10, iv=iv, exp=exp(d)) for d, iv in (("2026-10-20", 0.25), ("2026-10-21", 0.20),
                                                                         ("2026-10-23", 0.18)) for cp in "CP"]
        snap = replace(chain(cs, spot=100.0), prev_close=98.0)
        em = ex.expected_moves(snap, ["2026-10-20", "2026-10-21", "2026-10-23"], ASOF, snap.contracts)
        w_tue, w_wed, w_fri = 0.25 ** 2 * 5 / 8760, 0.20 ** 2 * 29 / 8760, 0.18 ** 2 * 77 / 8760
        self.assertAlmostEqual(em["daily_points"], 100 * math.sqrt(w_wed - w_tue))     # one full session
        self.assertAlmostEqual(em["weekly_points"], 100 * math.sqrt((w_wed - w_tue) + (w_fri - w_tue)))
        self.assertIn("forward", em["daily_method"])

    def test_after_close_uses_variance_to_next_session_expiry(self):
        snap, basket = self.mk()
        em = ex.expected_moves(snap, basket, TUE_CLOSE + timedelta(hours=3), snap.contracts)   # Tue 19:00 ET
        # quotes are from the session (before the close): the variance runs from Tue 16:00, not from 19:00
        self.assertAlmostEqual(em["daily_points"], 100 * math.sqrt(0.2 ** 2 * 24 / 8760))    # to Wed 16:00
        self.assertAlmostEqual(em["weekly_points"], 100 * math.sqrt(0.2 ** 2 * 72 / 8760))   # to Fri 16:00

    def test_overnight_band_does_not_shrink_on_frozen_quotes(self):
        snap, basket = self.mk()
        snap = replace(snap, spot_time=TUE_CLOSE + timedelta(minutes=15))              # Cboe's last quote, 16:15
        ems = [ex.expected_moves(snap, basket, TUE_CLOSE + timedelta(hours=h), snap.contracts)["daily_points"] for h in (1, 4, 9)]
        self.assertAlmostEqual(ems[0], ems[2])                                          # same quotes, same band all night
        self.assertAlmostEqual(ems[0], 100 * math.sqrt(0.2 ** 2 * 23.75 / 8760))
        live = replace(snap, spot_time=TUE_CLOSE + timedelta(hours=9))                  # fresh overnight quotes count from now
        self.assertAlmostEqual(ex.expected_moves(live, basket, TUE_CLOSE + timedelta(hours=9), live.contracts)["daily_points"],
                               100 * math.sqrt(0.2 ** 2 * 15 / 8760))

    def test_the_backup_band_does_not_grow_on_frozen_quotes(self):
        """The backup's IV is a curve read at the time left from now; with the variance clock at the quote it grew all
        weekend (NQ 2026-11-21: 1,257 to 1,324 points on unchanged prices)."""
        from gexsys.providers.occ import curve_iv
        pts = [(1.0, 0.50), (9.0, 0.40), (30.0, 0.35), (93.0, 0.30)]            # inverted: the short end is the higher
        quote = TUE_CLOSE + timedelta(minutes=15)
        snap, basket = self.mk()
        def at(now, vol_points=pts):
            cs = [replace(c, iv=curve_iv(pts, (c.expiration - now).total_seconds() / 86400)) for c in snap.contracts]
            return ex.expected_moves(replace(snap, contracts=cs, spot_time=quote, vol_points=vol_points), basket, now, cs)
        a, b = at(TUE_CLOSE + timedelta(hours=1)), at(TUE_CLOSE + timedelta(hours=16))     # Tue 17:00, Wed 08:00
        for k in ("daily_points", "weekly_points", "monthly_points", "daily_iv"):
            self.assertAlmostEqual(a[k], b[k], msg=k)
        # by hand, to Fri 2026-10-23 16:00: T = 2.98958 days, w = 0.25 + (0.16 x 9 - 0.25) x (T - 1) / 8
        t = 71.75 / 24
        self.assertAlmostEqual(a["weekly_points"], 100 * math.sqrt((0.25 + (0.16 * 9 - 0.25) * (t - 1) / 8) / 365))
        self.assertAlmostEqual(a["daily_points"], 100 * 0.50 / math.sqrt(252))               # one session at VIX1D (study weekend_move)
        self.assertGreater(at(TUE_CLOSE + timedelta(hours=16), None)["weekly_points"], a["weekly_points"])   # what it did before
        rth = [at(ASOF, p)["daily_points"] for p in (pts, None)]                 # during RTH the two clocks are one
        self.assertEqual(rth[0], rth[1])

    def test_the_backup_counts_one_session_while_closed(self):
        """Study weekend_move v1 (PR 76): with the market closed the backup's daily band is one session at VIX1D,
        sigma = S x VIX1D / sqrt(252), not calendar days on its curve. RTH and Cboe's own quotes are unchanged."""
        from gexsys.providers.occ import curve_iv
        pts = [(1.0, 0.50), (9.0, 0.40), (30.0, 0.35), (93.0, 0.30)]
        exps = [datetime.fromisoformat(d + "T16:00:00").replace(tzinfo=NY) for d in ("2026-10-22", "2026-10-23", "2026-10-26", "2026-11-20")]

        def at(now, quote, vol_points=pts):
            cs = [replace(contract(100, t, oi=10, exp=e), iv=curve_iv(pts, (e - now).total_seconds() / 86400)) for e in exps if e > now for t in "CP"]
            snap = replace(chain(cs, spot=100.0), prev_close=98.0, spot_time=quote, vol_points=vol_points)
            return ex.expected_moves(snap, [e.date().isoformat() for e in exps], now, cs)
        fri = datetime(2026, 10, 23, 20, 15, tzinfo=timezone.utc)                              # Friday 16:15 ET, the quote
        new, old = at(fri + timedelta(hours=5), fri), at(fri + timedelta(hours=5), fri, None)
        self.assertAlmostEqual(new["daily_points"], 100 * 0.50 / math.sqrt(252))               # 3.1497
        self.assertEqual((new["daily_method"], new["daily_iv"]), ("one session at VIX1D (backup, market closed)", 0.50))
        t = 71.75 / 24                                                                          # Fri 16:15 to Mon 16:00
        self.assertAlmostEqual(old["daily_points"], 100 * curve_iv(pts, (t * 24 - 5) / 24) * math.sqrt(t / 365))   # no curve: as before
        a = 100 * math.sqrt((0.25 + (0.16 * 9 - 0.25) * (t - 1) / 8) / 365)                    # the weekend by the calendar rule
        self.assertAlmostEqual(a, 3.8675, places=4)                                             # w = 0.25 + 1.19 x 1.98958 / 8 = 0.54595
        self.assertAlmostEqual(new["daily_points"] / a, 0.8144, places=4)                       # 3.1497 / 3.8675
        thu = datetime(2026, 10, 22, 20, 15, tzinfo=timezone.utc)
        night = at(thu + timedelta(hours=3), thu)                                               # Thursday night: the week ends tomorrow
        self.assertAlmostEqual(night["daily_points"], 100 * 0.50 / math.sqrt(252))
        self.assertAlmostEqual(night["weekly_points"], night["daily_points"])                   # never less than the day inside it
        day = at(datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc), datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc))
        self.assertNotEqual(day["daily_method"], new["daily_method"])                           # RTH: unchanged
        gone = at(fri + timedelta(hours=5), fri, [p for p in pts if p[0] != 1.0])               # no VIX1D close: the old rule
        self.assertEqual(gone["daily_method"], "variance to the next session's expiration")

    def test_the_band_names_its_centre(self):
        """The page says what the 1 sigma range is centred on: on a gap day a band around the prior close reads
        as one around today's price unless it says so (NQ 2026-11-19, +1.7% gap)."""
        snap, basket = self.mk()
        rth = ex.expected_moves(snap, basket, ASOF, snap.contracts)                               # Tue 11:00 ET
        self.assertEqual((rth["anchor"], rth["anchor_label"]), (98.0, "prior close"))
        night = ex.expected_moves(snap, basket, TUE_CLOSE + timedelta(hours=3), snap.contracts)    # Tue 19:00 ET
        self.assertEqual((night["anchor"], night["anchor_label"]), (100.0, "last close"))
        live = ex.expected_moves(replace(snap, prev_close=None), basket, ASOF, snap.contracts)     # RTH, no prior close
        self.assertEqual((live["anchor"], live["anchor_label"]), (100.0, "price"))
        no_iv = [replace(c, iv=None) for c in snap.contracts]                                       # nothing to measure
        self.assertIsNone(ex.expected_moves(replace(snap, contracts=no_iv), basket, ASOF, no_iv))

    def test_spot_sigma_says_where_price_sits_in_the_band(self):
        """Decision 001, C1: price in prior-close band widths, only while the band is centred on the prior close."""
        snap, basket = self.mk(spot=100.0, prev=98.0)
        rth = ex.expected_moves(snap, basket, ASOF, snap.contracts)                               # Tue 11:00 ET
        d = 100 * math.sqrt(0.2 ** 2 * (29 / 8760) / 2)                                             # as in the test above
        self.assertAlmostEqual(rth["spot_sigma"], (100.0 - 98.0) / d)                               # ~ +1.76
        down = ex.expected_moves(replace(snap, prev_close=102.5), basket, ASOF, snap.contracts)
        self.assertAlmostEqual(down["spot_sigma"], (100.0 - 102.5) / d)                             # below: negative
        night = ex.expected_moves(snap, basket, TUE_CLOSE + timedelta(hours=3), snap.contracts)    # centred on price
        self.assertNotIn("spot_sigma", night)
        live = ex.expected_moves(replace(snap, prev_close=None), basket, ASOF, snap.contracts)     # no prior close
        self.assertNotIn("spot_sigma", live)
        # nothing else in the band moves: the same output with the new key taken out
        old = {k: v for k, v in rth.items() if k != "spot_sigma"}
        self.assertEqual(old["anchor"], 98.0)
        self.assertAlmostEqual(old["daily_points"], d)

    def test_index_options_preferred_over_converted_etf(self):
        # a converted ETF option sits closer to the money, but the band uses the index's own ATM IV
        snap, basket = self.mk(spot=100.4)
        etf = [replace(c, strike=100.4, group_strike=100.0, iv=0.15, symbol="X@IDX") for c in snap.contracts]
        em = ex.expected_moves(snap, basket, ASOF, snap.contracts + etf)
        self.assertAlmostEqual(em["daily_iv"], 0.20)
        self.assertAlmostEqual(ex.atm_iv(etf, "2026-10-21", 100.4), 0.15)      # ETF-only chain still works

    def test_atm_iv_uses_a_strike_quoted_on_both_sides(self):
        # nearest strike has only a (skewed) call left; the next one has both sides -> use the pair
        snap, _ = self.mk(spot=100.0)
        c0 = snap.contracts[0]
        mk = lambda k, typ, iv: replace(c0, strike=k, option_type=typ, iv=iv, symbol=f"{typ.value}{k}")
        cs = [mk(100.0, OptionType.CALL, 0.21), mk(101.0, OptionType.CALL, 0.19), mk(101.0, OptionType.PUT, 0.19)]
        self.assertAlmostEqual(ex.atm_iv(cs, c0.expiration.date().isoformat(), 100.0), 0.19)
        self.assertAlmostEqual(ex.atm_iv(cs[:1], c0.expiration.date().isoformat(), 100.0), 0.21)   # one side only: still a value

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
