import math
import unittest

from gexsys import pricing as p


class TestPricing(unittest.TestCase):
    def test_bsm_gamma_matches_finite_difference(self):
        for s, k, t, r, q, v in [(100, 100, 0.25, 0.04, 0.01, 0.2), (5800, 5900, 7 / 365, 0.04, 0.013, 0.14),
                                 (20000, 19500, 1 / 365, 0.04, 0.0, 0.25)]:
            fd = p.finite_diff_gamma(lambda x: p.bsm_price(x, k, t, r, q, v, True), s, 1e-4)
            self.assertAlmostEqual(p.bsm_gamma(s, k, t, r, q, v), fd, delta=abs(fd) * 1e-3)

    def test_black76_gamma_matches_finite_difference(self):
        f, k, t, r, v = 5860, 5850, 10 / 365, 0.04, 0.15
        fd = p.finite_diff_gamma(lambda x: p.black76_price(x, k, t, r, v, False), f, 1e-4)
        self.assertAlmostEqual(p.black76_gamma(f, k, t, r, v), fd, delta=abs(fd) * 1e-3)

    def test_hand_calculated_gamma(self):
        # S=K=100, T=1, r=q=0, vol=0.2: d1=0.1, gamma = phi(0.1)/(100*0.2) = 0.396953/20
        self.assertAlmostEqual(p.bsm_gamma(100, 100, 1, 0, 0, 0.2), 0.3969525 / 20, places=7)

    def test_put_call_parity(self):
        s, k, t, r, q, v = 100, 95, 0.5, 0.03, 0.01, 0.3
        c, pu = p.bsm_price(s, k, t, r, q, v, True), p.bsm_price(s, k, t, r, q, v, False)
        self.assertAlmostEqual(c - pu, s * math.exp(-q * t) - k * math.exp(-r * t), places=9)

    def test_implied_vol_round_trip(self):
        for is_call in (True, False):
            px = p.bsm_price(5800, 5750, 3 / 365, 0.04, 0.0, 0.17, is_call)
            self.assertAlmostEqual(p.implied_vol(px, 5800, 5750, 3 / 365, 0.04, 0.0, is_call), 0.17, places=5)

    def test_implied_vol_rejects_below_intrinsic(self):
        self.assertIsNone(p.implied_vol(1.0, 100, 90, 0.1, 0, 0, True))
        self.assertIsNone(p.implied_vol(None, 100, 90, 0.1, 0, 0, True))

    def test_american_call_no_dividend_equals_european(self):
        e = p.bsm_price(100, 100, 0.25, 0.04, 0.0, 0.2, True)
        a = p.crr_american(100, 100, 0.25, 0.04, 0.0, 0.2, True, steps=600)
        self.assertAlmostEqual(a, e, delta=0.02)

    def test_american_put_premium_and_gamma_error_bounded(self):
        s, k, t, r, v = 487, 487, 7 / 365, 0.04, 0.18
        self.assertGreaterEqual(p.crr_american(s, k, t, r, 0, v, False), p.bsm_price(s, k, t, r, 0, v, False) - 1e-6)
        fd_am = p.finite_diff_gamma(lambda x: p.crr_american(x, k, t, r, 0, v, False, steps=800), s, 5e-3)
        bs = p.bsm_gamma(s, k, t, r, 0, v)
        # documented approximation: European gamma within 5% for near-dated ATM ETF puts
        self.assertLess(abs(fd_am - bs) / bs, 0.05)

    def test_vanna_matches_finite_difference(self):
        s, k, t, r, q, v, h = 5800, 5850, 10 / 365, 0.04, 0.013, 0.15, 1e-4
        for call in (True, False):
            fd = (p.bsm_delta(s, k, t, r, q, v + h, call) - p.bsm_delta(s, k, t, r, q, v - h, call)) / (2 * h)
            self.assertAlmostEqual(p.bsm_vanna(s, k, t, r, q, v), fd, delta=abs(fd) * 1e-4 + 1e-9)

    def test_charm_matches_finite_difference(self):
        # charm = change in delta as calendar time passes (time to expiry shrinks)
        s, k, t, r, q, v, h = 20000, 20200, 5 / 365, 0.04, 0.007, 0.22, 1e-6
        for call in (True, False):
            fd = (p.bsm_delta(s, k, t - h, r, q, v, call) - p.bsm_delta(s, k, t + h, r, q, v, call)) / (2 * h)
            self.assertAlmostEqual(p.bsm_charm(s, k, t, r, q, v, call), fd, delta=abs(fd) * 1e-4 + 1e-6)

    def test_otm_call_delta_decays(self):
        # an out-of-the-money call loses delta as time passes: negative charm
        self.assertLess(p.bsm_charm(100, 110, 0.05, 0.0, 0.0, 0.2, True), 0)

    def test_zero_dte_time_floor(self):
        self.assertTrue(math.isfinite(p.bsm_gamma(100, 100, 0.0, 0, 0, 0.2)))


if __name__ == "__main__":
    unittest.main()
