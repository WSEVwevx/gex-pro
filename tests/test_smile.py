"""gexsys/smile.py: the previous session's per-contract IVs as a smile in time-scaled moneyness.

Synthetic rows only (shaped like LSE's /v3/options/chain rows; no LSE value may sit in the repo). Tolerances were
fixed before the first run: the fit is within 0.25 vol points of the true smile inside the data, and exact at bins.
"""
import math
import random
import unittest
from datetime import datetime, timedelta, timezone

from gexsys import engine, smile as S

UTC = timezone.utc
OPEN = datetime(2026, 11, 25, 14, 30, tzinfo=UTC)          # Wed 25 Nov 2026, 09:30 ET
CLOSE = datetime(2026, 11, 25, 21, 0, tzinfo=UTC)          # 16:00 ET
EXP = datetime(2026, 12, 2, 21, 0, tzinfo=UTC)             # a PM expiry a week later
R, Q = 0.04, 0.007


def truth(x):
    """The smile the synthetic market trades: skewed, curved, in time-scaled moneyness."""
    return 0.20 - 0.35 * x + 1.2 * x * x


def row(k, iv, s=21000.0, when=CLOSE - timedelta(minutes=10), typ=None, vol=10, **kw):
    t = (EXP - when).total_seconds() / S.YEAR_S
    f = s * math.exp((R - Q) * t)
    typ = typ or ("put" if k < f else "call")
    r = {"strike": k, "iv": iv, "greeks_underlying_price": s, "volume_today": vol, "contract_type": typ,
         "last_trade_at": when.isoformat().replace("+00:00", "Z"), "expiry": EXP.date().isoformat()}
    r.update(kw)
    return r


def market(seed=7, n_early=0):
    """OTM rows every 25 points across +-6%, each at the true IV for its own trade time and price."""
    rnd = random.Random(seed)
    rows = []
    for k in range(19750, 22275, 25):
        when = CLOSE - timedelta(minutes=rnd.randint(1, 59))
        s = 21000.0 + rnd.uniform(-15, 15)
        t = (EXP - when).total_seconds() / S.YEAR_S
        rows.append(row(k, truth(S.moneyness(k, s, t, R, Q)), s=s, when=when, vol=rnd.randint(1, 400)))
    for _ in range(n_early):
        rows.append(row(21000 + 25 * rnd.randint(-40, 40), 0.9, when=OPEN + timedelta(minutes=30)))
    return rows


class Rows(unittest.TestCase):
    def test_year_is_the_engines(self):
        self.assertEqual(S.YEAR_S, engine.YEAR_SECONDS)

    def test_each_filter(self):
        keep = row(20500, 0.25)
        pts = lambda rs: S.points(rs, EXP, OPEN, CLOSE, R, Q)
        self.assertEqual(len(pts([keep])), 1)
        for bad in (row(20500, 0.02), row(20500, 3.5), row(20500, 0.25, vol=0), row(20500, 0.25, typ="call"),
                    row(21500, 0.25, typ="put"), row(20500, 0.25, when=CLOSE + timedelta(minutes=1)),
                    row(20500, 0.25, when=OPEN - timedelta(minutes=1)), row(20500, 0.25, s=0),
                    row(20500, None), row(20500, 0.25, contract_type="x"), row(20500, 0.25, last_trade_at=None)):
            self.assertEqual(pts([bad]), [], bad)
        self.assertEqual(S.points([keep], CLOSE, OPEN, CLOSE, R, Q), [])        # expiring at P's close: says nothing later

    def test_moneyness_uses_the_rows_own_price_and_time(self):
        p = S.points([row(20500, 0.25, s=21010.0)], EXP, OPEN, CLOSE, R, Q)[0]
        t = (EXP - (CLOSE - timedelta(minutes=10))).total_seconds() / (365 * 86400)
        self.assertAlmostEqual(p.t, t, places=12)
        self.assertAlmostEqual(p.x, math.log(20500 / (21010.0 * math.exp((R - Q) * t))) / math.sqrt(t), places=12)
        self.assertTrue(p.late)

    def test_lse_time_and_type_spellings(self):
        self.assertEqual(S.stamp("2026-11-25T20:59:00Z"), datetime(2026, 11, 25, 20, 59, tzinfo=UTC))
        self.assertEqual(S.stamp("2026-11-25T15:59:00-05:00"), datetime(2026, 11, 25, 20, 59, tzinfo=UTC))
        self.assertEqual(S.stamp("2026-11-25 20:58:19.448381162"), datetime(2026, 11, 25, 20, 58, 19, 448381, tzinfo=UTC))
        self.assertIsNone(S.stamp("not a time"))
        self.assertIsNone(S.stamp(None))
        self.assertEqual([S.kind({"contract_type": v}) for v in ("call", "PUT", "C", "p", "", None)], ["C", "P", "C", "P", None, None])


class Fitting(unittest.TestCase):
    def test_recovers_the_true_smile(self):
        pts = S.points(market(), EXP, OPEN, CLOSE, R, Q)
        f, why = S.fit(EXP, pts, sigma_ref=0.20)
        self.assertEqual(why, "")
        self.assertEqual(f.window, "last hour")
        lo, hi = f.xs[0], f.xs[-1]
        worst = max(abs(f.iv(lo + (hi - lo) * i / 200) - truth(lo + (hi - lo) * i / 200)) for i in range(201))
        self.assertLess(worst * 100, 0.25)                      # vol points, inside the data
        self.assertLess(f.rms, 0.25)
        self.assertEqual(f.iv(lo - 1.0), f.ivs[0])               # flat beyond the data
        self.assertEqual(f.iv(hi + 1.0), f.ivs[-1])
        for x, v in zip(f.xs, f.ivs):
            self.assertAlmostEqual(f.iv(x), v, places=12)        # through every bin

    def test_a_stale_print_does_not_move_a_bin(self):
        rows = market()
        k = 20500
        good = S.fit(EXP, S.points(rows, EXP, OPEN, CLOSE, R, Q), 0.20)[0]
        rows.append(row(k, 0.95, vol=1))                          # one tiny print at a silly vol, same strike
        bad = S.fit(EXP, S.points(rows, EXP, OPEN, CLOSE, R, Q), 0.20)[0]
        x = S.points([row(k, 0.25)], EXP, OPEN, CLOSE, R, Q)[0].x
        self.assertLess(abs(bad.iv(x) - good.iv(x)) * 100, 0.25)

    def test_a_stale_print_beside_good_ones_is_trimmed_and_counted(self):
        rows = market()
        rows[40] = dict(rows[40], iv=0.90)                       # 70 vol points off, sharing its bin
        f, _ = S.fit(EXP, S.points(rows, EXP, OPEN, CLOSE, R, Q), 0.20)
        self.assertEqual((f.screened, f.outliers), (0, 1))       # trimmed inside its bin; counted, not in the RMS
        self.assertNotIn(0.90, f.ivs)
        self.assertLess(f.rms, 0.25)

    def test_a_lone_stale_bin_is_screened(self):
        b = [(x / 50, truth(x / 50), 1) for x in range(-10, 11)]
        bad = b[:7] + [(b[7][0], 0.90, 1)] + b[8:]               # a bin that is one stale print
        kept, n = S.screen(bad)
        self.assertEqual((n, kept), (1, b[:7] + b[8:]))
        end = [(b[0][0], 0.90, 1)] + b[1:]                       # at an end too
        self.assertEqual(S.screen(end), (b[1:], 1))

    def test_two_stale_bins_close_together_are_both_screened(self):
        # 2026-11-28: with a two-neighbour line, two spikes inflated every nearby miss and the median, and none went
        b = [(-0.3 + 0.02 * i, truth(-0.3 + 0.02 * i), 1) for i in range(30)]
        for spikes in ((10, 12), (0, 2), (28, 29), (10, 11, 12)):
            bad = [(x, 0.9 if i in spikes else v, w) for i, (x, v, w) in enumerate(b)]
            self.assertEqual(S.screen(bad), ([t for i, t in enumerate(b) if i not in spikes], len(spikes)), spikes)

    def test_the_screen_keeps_a_smooth_steep_wing(self):
        b = [(x / 50, truth(x / 50), 1) for x in range(-30, 31)]     # curvature of a steep real smile
        self.assertEqual(S.screen(b), (b, 0))

    def test_a_thin_last_hour_widens_to_the_session_and_says_so(self):
        rows = [r for i, r in enumerate(market()) if i % 30 == 0]                # 4 late rows: too thin
        early = [dict(r, last_trade_at=(OPEN + timedelta(hours=2)).isoformat()) for r in market(seed=8)]
        f, _ = S.fit(EXP, S.points(rows + early, EXP, OPEN, CLOSE, R, Q), 0.20)
        self.assertEqual(f.window, "session")

    def test_too_few_points_says_why(self):
        f, why = S.fit(EXP, S.points([row(20500, 0.25), row(21500, 0.18)], EXP, OPEN, CLOSE, R, Q), 0.20)
        self.assertIsNone(f)
        self.assertEqual(why, "2 usable rows in 2 bins (1 below the money, 1 above); 5 bins with 2 on each side are needed")

    def test_bins_are_a_tenth_of_a_standard_deviation(self):
        pts = [S.Point(x, 0.2, 1, 0.02, 1, True) for x in (0.0, 0.019, 0.021, -0.001)]
        self.assertEqual(len(S.bins(pts, 0.2)), 3)                # width 0.02: [-0.02,0) [0,0.02) [0.02,0.04)
        (x, iv, w), = S.bins([S.Point(0.001, 0.20, 1, 1, 1, True), S.Point(0.003, 0.21, 3, 1, 1, True)], 0.2)
        self.assertAlmostEqual(x, 0.0025, places=15)              # x and IV both volume-weighted means, same rows
        self.assertAlmostEqual(iv, 0.2075, places=15)
        self.assertEqual(w, 4)
        (x, iv, w), = S.bins([S.Point(0.001, 0.20, 5, 1, 1, True), S.Point(0.002, 0.21, 5, 1, 1, True),
                              S.Point(0.003, 0.60, 1, 1, 1, True)], 0.2)
        self.assertAlmostEqual((x, iv, w), (0.0015, 0.205, 10))   # the 0.60 print is 39 points off: dropped


class Pchip(unittest.TestCase):
    def test_monotone_data_stays_monotone(self):
        f = S.pchip([0, 1, 2, 3, 4], [0.30, 0.25, 0.24, 0.10, 0.09])
        ys = [f(i / 100) for i in range(401)]
        self.assertTrue(all(a >= b - 1e-15 for a, b in zip(ys, ys[1:])))

    def test_matches_a_known_value(self):
        # by hand: secants 1, -1, 1; interior slopes 0 (the secants change sign); the end slope is the three-point
        # estimate ((2h0 + h1) d0 - h0 d1) / (h0 + h1) = (3 + 1) / 2 = 2, kept (same sign as d0, |2| <= 3|d0|).
        # At x = 0.5 (t = 0.5): h s0 (t^3 - 2t^2 + t) + y1 (-2t^3 + 3t^2) = 2 x 0.125 + 0.5 = 0.75
        self.assertAlmostEqual(S.pchip([0, 1, 2, 3], [0, 1, 0, 1])(0.5), 0.75, places=12)

    def test_two_points_is_a_line(self):
        self.assertAlmostEqual(S.pchip([0, 2], [1, 3])(0.5), 1.5, places=12)


class Surface(unittest.TestCase):
    def flat(self, v):
        return S.Fit(EXP, "last hour", [-1, 1], [v, v], 10, 0, 0, lambda x: v)

    def test_total_variance_between_neighbours(self):
        fits = [(0.02, self.flat(0.20)), (0.06, self.flat(0.30))]
        want = math.sqrt((0.04 * 0.02 + (0.09 * 0.06 - 0.04 * 0.02) * 0.5) / 0.04)
        self.assertAlmostEqual(S.surface_iv(fits, 0.04, 0.0), want, places=12)
        self.assertAlmostEqual(want, 0.278388, places=6)

    def test_beyond_the_ends_and_own_fit(self):
        fits = [(0.02, self.flat(0.20)), (0.06, self.flat(0.30))]
        self.assertEqual(S.surface_iv(fits, 0.10, 0.0), 0.30)
        self.assertEqual(S.surface_iv(fits, 0.01, 0.0), 0.20)
        self.assertEqual(S.surface_iv(fits, 0.04, 0.0, own=self.flat(0.5)), 0.5)
        self.assertIsNone(S.surface_iv([], 0.04, 0.0))

    def test_an_expiry_nearing_narrows_in_strikes(self):
        # the same strike is further from the money, in x, with less time left: the smile is carried in x
        self.assertGreater(abs(S.moneyness(20500, 21000, 1 / 365, R, Q)), abs(S.moneyness(20500, 21000, 2 / 365, R, Q)))


if __name__ == "__main__":
    unittest.main()
