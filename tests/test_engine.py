import unittest
from datetime import datetime, timedelta, timezone

from gexsys import engine as eng
from gexsys import pricing
from gexsys.models import SourceKind
from tests.util import ASOF, chain, contract


class TestHandCalculations(unittest.TestCase):
    def test_single_call_usd_per_1pct(self):
        # 1000 OI * 0.002 gamma * 100 mult * 5000^2 * 0.01 = $50,000,000 per 1%
        r = eng.compute(chain([contract(5000, "C", oi=1000, gamma=0.002)], spot=5000.0))
        self.assertAlmostEqual(r.totals["net"], 50_000_000.0, places=3)

    def test_units_are_consistent(self):
        c = [contract(5000, "C", oi=1000, gamma=0.002)]
        pt = eng.compute(chain(c, spot=5000.0), eng.EngineConfig(unit="usd_per_point")).totals["net"]
        dl = eng.compute(chain(c, spot=5000.0), eng.EngineConfig(unit="delta_per_point")).totals["net"]
        self.assertAlmostEqual(dl, 200.0)            # 200 underlying units of delta per point
        self.assertAlmostEqual(pt, 1_000_000.0)      # $1M per point
        self.assertAlmostEqual(eng.convert_units(pt, "usd_per_point", "usd_per_1pct", 5000.0), 50_000_000.0)

    def test_futures_multiplier(self):
        # ES option: M = $50/pt.  100 OI * 0.001 * 50 * 5800 = $29,000 per point
        r = eng.compute(chain([contract(5800, "C", oi=100, gamma=0.001, mult=50)], spot=5800.0,
                              kind=SourceKind.FUTURES), eng.EngineConfig(unit="usd_per_point"))
        self.assertAlmostEqual(r.totals["net"], 29_000.0)

    def test_call_put_aggregation_and_signs(self):
        cs = [contract(100, "C", oi=10, gamma=0.05), contract(100, "P", oi=4, gamma=0.05),
              contract(105, "C", oi=2, gamma=0.03)]
        r = eng.compute(chain(cs), eng.EngineConfig(unit="delta_per_point"))
        self.assertAlmostEqual(r.by_strike[100.0]["call"], 50.0)
        self.assertAlmostEqual(r.by_strike[100.0]["put"], -20.0)
        self.assertAlmostEqual(r.by_strike[100.0]["net"], 30.0)
        self.assertAlmostEqual(r.totals["call"], 56.0)
        self.assertAlmostEqual(r.totals["gross"], 76.0)
        short = eng.compute(chain(cs), eng.EngineConfig(unit="delta_per_point", positioning="dealer_short_all"))
        self.assertAlmostEqual(short.totals["net"], -76.0)
        custom = eng.compute(chain(cs), eng.EngineConfig(unit="delta_per_point", positioning="custom",
                                                         call_sign=-1, put_sign=1))
        self.assertAlmostEqual(custom.totals["net"], -56.0 + 20.0)

    def test_invalid_settings_raise(self):
        for bad in (dict(positioning="magic"), dict(unit="eur"), dict(positioning="custom"),
                    dict(grid_pct=0), dict(expirations=["2026-13-01"])):
            with self.assertRaises(eng.ConfigError):
                eng.compute(chain([contract(100, "C", gamma=0.01)]), eng.EngineConfig(**bad))


class TestFiltering(unittest.TestCase):
    def test_expiration_filters(self):
        zero = ASOF.replace(hour=20)          # 16:00 ET same day
        cs = [contract(100, "C", gamma=0.01, exp=zero), contract(100, "C", gamma=0.01, days=10),
              contract(100, "C", gamma=0.01, days=60), contract(100, "C", gamma=0.01, days=-1)]
        r = eng.compute(chain(cs), eng.EngineConfig(max_dte=45))
        self.assertEqual(len(r.basket), 2)
        r = eng.compute(chain(cs), eng.EngineConfig(max_dte=45, include_0dte=False))
        self.assertEqual(r.basket, [(ASOF + timedelta(days=10)).date().isoformat()])
        explicit = (ASOF + timedelta(days=60)).date().isoformat()
        r = eng.compute(chain(cs), eng.EngineConfig(expirations=[explicit]))
        self.assertEqual(r.basket, [explicit])
        self.assertEqual(r.excluded["expired_or_outside_basket"], 3)

    def test_zero_and_missing_oi(self):
        cs = [contract(100, "C", oi=0, gamma=0.01), contract(100, "P", oi=None, gamma=0.01),
              contract(101, "C", oi=5, gamma=0.01)]
        r = eng.compute(chain(cs))
        self.assertEqual(r.excluded["zero_or_missing_oi"], 2)
        self.assertEqual(r.totals["contracts_used"], 1)

    def test_all_oi_missing_is_unavailable_not_fabricated(self):
        r = eng.compute(chain([contract(100, "C", oi=None, gamma=0.01)]))
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertIsNone(r.zero_gamma)
        self.assertIsNone(r.totals["net"])

    def test_missing_greeks(self):
        # gamma missing but IV present -> model gamma; no IV and no quotes -> the same expiration's
        # nearest-strike IV; nothing to borrow (only contract in its expiration) -> excluded
        cs = [contract(100, "C", gamma=None, iv=0.2), contract(104, "C", gamma=None, iv=None),
              contract(101, "C", gamma=None, iv=None, days=14)]
        r = eng.compute(chain(cs))
        self.assertEqual(r.excluded["missing_greeks"], 1)
        self.assertEqual(len(r.rows), 2)
        self.assertEqual(r.rows[0].gamma_quality.value, "CALC")
        self.assertAlmostEqual(r.rows[0].gamma, pricing.bsm_gamma(100, 100, 7 / 365, 0, 0, 0.2), places=10)
        self.assertEqual(r.rows[1].iv, 0.2)                                    # borrowed from strike 100
        self.assertAlmostEqual(r.rows[1].gamma, pricing.bsm_gamma(100, 104, 7 / 365, 0, 0, 0.2), places=10)
        self.assertTrue(any("nearest strike's IV" in w for w in r.warnings))

    def test_rounded_vendor_gamma_not_used_when_recomputing(self):
        # Cboe rounds gamma to 4 decimals (0.0002 on a deep-ITM 0DTE put whose true gamma is ~0.000005);
        # with recompute_greeks="always" that vendor number must never reach the totals
        lone = contract(130, "P", gamma=0.0002, iv=None, days=1)
        r = eng.compute(chain([lone, contract(100, "C", gamma=0.01, iv=0.2)]), eng.EngineConfig(recompute_greeks="always"))
        self.assertEqual([x.contract.strike for x in r.rows], [100.0])
        r2 = eng.compute(chain([lone, contract(100, "C", gamma=0.01, iv=0.2)]))          # missing_only keeps vendor
        self.assertEqual(len(r2.rows), 2)

    def test_missing_greeks_solved_from_quotes(self):
        px = pricing.bsm_price(100, 100, 7 / 365, 0, 0, 0.25, True)
        r = eng.compute(chain([contract(100, "C", gamma=None, iv=None, bid=px - 0.01, ask=px + 0.01)]))
        self.assertAlmostEqual(r.rows[0].iv, 0.25, places=3)

    def test_implausible_far_exposure_refused(self):
        # near-the-money OI missing (a broken or blanked feed): only deep strikes carry OI -> refuse, don't fabricate
        cs = [contract(100, "C", oi=0, gamma=0.05), contract(100, "P", oi=0, gamma=0.05),
              contract(80, "P", oi=5000, gamma=0.01), contract(125, "C", oi=5000, gamma=0.01)]
        r = eng.compute(chain(cs))
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertTrue(any("implausible" in w for w in r.warnings))

    def test_missing_spot_unavailable(self):
        r = eng.compute(chain([contract(100, "C", gamma=0.01)], spot=None))
        self.assertEqual(r.status, "UNAVAILABLE")

    def test_stale_spot_flagged(self):
        r = eng.compute(chain([contract(100, "C", gamma=0.01)], spot_time=ASOF - timedelta(hours=2)))
        self.assertEqual(r.status, "DEGRADED")
        self.assertTrue(any("stale" in w for w in r.warnings))

    def test_time_to_expiry_across_dst(self):
        asof = datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc)   # Fri 16:00 EDT
        exp = datetime(2026, 11, 2, 21, 0, tzinfo=timezone.utc)     # Mon 16:00 EST (after fall-back)
        r = eng.compute(chain([contract(100, "C", gamma=0.01, exp=exp)]), asof=asof)
        self.assertAlmostEqual(r.rows[0].t_years * 365 * 24, 73.0, places=6)


class TestZeroGamma(unittest.TestCase):
    def test_single_crossing_verified_independently(self):
        cs = [contract(95, "P", oi=1000, gamma=None, iv=0.2), contract(105, "C", oi=1000, gamma=None, iv=0.2)]
        snap = chain(cs)
        r = eng.compute(snap, eng.EngineConfig(grid_pct=0.08, grid_steps=401))
        self.assertEqual(len(r.zero_gamma_crossings), 1)
        zg = r.zero_gamma
        self.assertTrue(95 < zg < 105)
        t = 7 / 365
        net = 1000 * 100 * (pricing.bsm_gamma(zg, 105, t, 0, 0, 0.2) - pricing.bsm_gamma(zg, 95, t, 0, 0, 0.2))
        scale = 1000 * 100 * pricing.bsm_gamma(zg, 105, t, 0, 0, 0.2)
        self.assertLess(abs(net) / scale, 0.01)

    def test_multiple_crossings_nearest_selected(self):
        cs = [contract(92, "P", oi=3000, iv=0.1, gamma=None, days=3), contract(100, "C", oi=3000, iv=0.1, gamma=None, days=3),
              contract(108, "P", oi=3000, iv=0.1, gamma=None, days=3)]
        r = eng.compute(chain(cs, spot=101.0), eng.EngineConfig(grid_pct=0.12, grid_steps=481))
        self.assertGreaterEqual(len(r.zero_gamma_crossings), 2)
        self.assertEqual(r.zero_gamma, min(r.zero_gamma_crossings, key=lambda x: abs(x - 101)))
        self.assertIn("crossings", r.zero_gamma_status)

    def test_no_crossing(self):
        r = eng.compute(chain([contract(100, "C", gamma=None, iv=0.2), contract(110, "C", gamma=None, iv=0.2)]))
        self.assertIsNone(r.zero_gamma)
        self.assertTrue(r.zero_gamma_status.startswith("NO CROSSING"))

    def test_low_coverage_refuses_zero_gamma(self):
        cs = [contract(95, "P", oi=1000, gamma=0.05, iv=None), contract(105, "C", oi=10, gamma=None, iv=0.2)]
        r = eng.compute(chain(cs))
        self.assertIsNone(r.zero_gamma)
        self.assertTrue(r.zero_gamma_status.startswith("UNAVAILABLE"))

    def test_find_crossings_interpolation(self):
        self.assertEqual(eng.find_crossings([(0, -1.0), (1, 1.0)]), [0.5])
        self.assertEqual(eng.find_crossings([(0, 1.0), (1, 2.0)]), [])
        self.assertEqual(eng.find_crossings([(0, 0.0), (1, 2.0)]), [0])


class TestExpectedMove(unittest.TestCase):
    def test_atm_strike_needs_both_sides(self):
        # the nearest strike has only a (skewed) call; the next one has a call and a put -> that pair sets the IV
        snap = chain([contract(100, "C", iv=0.30), contract(101, "C", iv=0.20), contract(101, "P", iv=0.20)], spot=100.0)
        em = eng.compute(snap, asof=ASOF).expected_move
        self.assertEqual(em["atm_strike"], 101.0)
        self.assertAlmostEqual(em["atm_iv"], 0.20)


class TestRegimeAndDiff(unittest.TestCase):
    def test_regime(self):
        c = eng.EngineConfig()
        self.assertEqual(eng.classify_regime(10, 100, 100, None, c), "POSITIVE")
        self.assertEqual(eng.classify_regime(-10, 100, 100, None, c), "NEGATIVE")
        self.assertEqual(eng.classify_regime(1, 100, 100, None, c), "INDETERMINATE")
        self.assertEqual(eng.classify_regime(50, 100, 100, 100.05, c), "INDETERMINATE")

    def test_diff(self):
        a = {"zero_gamma": {"price": 100}, "regime": "POSITIVE", "net": 5, "abs_by_strike": {"100": 1, "105": 1}}
        b = {"zero_gamma": {"price": 98}, "regime": "NEGATIVE", "net": -5, "abs_by_strike": {"100": 2}}
        d = eng.diff(a, b)
        self.assertEqual(d["zero_gamma"], -2)
        self.assertTrue(d["regime_changed"])
        self.assertAlmostEqual(d["concentration_shift"], 0.5)
        self.assertEqual(d["net_change"], -10)


if __name__ == "__main__":
    unittest.main()
