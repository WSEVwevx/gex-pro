"""The IV solver refuses prices that do not pin a vol down (stress test A2, 2026-11-10)."""
import unittest

from gexsys import pricing as p


class TestIVSolver(unittest.TestCase):
    def test_deep_itm_low_vol_is_refused_not_guessed(self):
        # the case that came back at 499%: K = 0.77 S, 52 days, true vol 2%; the price is all intrinsic
        s, k, t, r, q = 20000, 0.7684892495845768 * 20000, 0.1420955838984005, 0.04, 0.01
        px = p.bsm_price(s, k, t, r, q, 0.020000734, True)
        iv, why = p.implied_vol_status(px, s, k, t, r, q, True)
        self.assertIsNone(iv)
        self.assertIn("vol", why)

    def test_round_trip_is_exact_where_the_price_sets_the_vol(self):
        for k, t, v in ((20000, 30 / 365, 0.18), (21000, 7 / 365, 0.25), (19000, 1 / 365, 0.4), (20000, 2.0, 1.5)):
            for call in (True, False):
                px = p.bsm_price(20000, k, t, 0.04, 0.01, v, call)
                self.assertAlmostEqual(p.implied_vol(px, 20000, k, t, 0.04, 0.01, call), v, delta=1e-8)

    def test_impossible_prices_name_their_reason(self):
        s, k, t = 100.0, 90.0, 0.1
        self.assertEqual(p.implied_vol_status(0, s, k, t, 0, 0, True), (None, "no price"))
        self.assertEqual(p.implied_vol_status(100.0, s, k, t, 0, 0, True)[1], "at or above the no-arbitrage maximum")
        self.assertEqual(p.implied_vol_status(5.0, s, k, t, 0, 0, True)[1], "below intrinsic value")

    def test_quoted_mids_use_their_cent_precision(self):
        # 4% out of the money, one hour left, quoted at 0.01: half a cent moves the vol by more than 2 points
        s, k, t = 20000.0, 20800.0, 1 / (365 * 24)
        iv, why = p.implied_vol_status(0.01, s, k, t, 0.04, 0.0, True, p.QUOTE_TOL, p.QUOTE_MAX_VOL_ERR)
        self.assertIsNone(iv)
        self.assertIn("does not pin", why)
        # an at-the-money 30-day option is pinned to well under 2 points
        px = round(p.bsm_price(s, s, 30 / 365, 0.04, 0.0, 0.2, True), 2)
        self.assertAlmostEqual(p.implied_vol(px, s, s, 30 / 365, 0.04, 0.0, True, p.QUOTE_TOL, p.QUOTE_MAX_VOL_ERR), 0.2, delta=1e-4)


if __name__ == "__main__":
    unittest.main()
