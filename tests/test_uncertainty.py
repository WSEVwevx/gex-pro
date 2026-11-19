"""Phase 4 statistics (gexpro/uncertainty.py): session bootstrap, interval method, p-value, power, headline."""
import math
import random
import unittest

from gexpro import uncertainty as U


def data(n, real_p=0.6, base_p=0.3, seed=1):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        rn, bn = rng.randint(1, 3), 20
        out.append((sum(rng.random() < real_p for _ in range(rn)), rn, sum(rng.random() < base_p for _ in range(bn)), bn))
    return out


class TestPieces(unittest.TestCase):
    def test_diff_is_pooled_ratio(self):
        self.assertAlmostEqual(U.diff([(1, 2, 2, 10), (2, 2, 3, 10)]), 3 / 4 - 5 / 20)
        self.assertIsNone(U.diff([(0, 0, 1, 2)]))

    def test_resample_is_seeded_and_resamples_sessions(self):
        ss = data(15)
        self.assertEqual(U.resample(ss, 200, 5), U.resample(ss, 200, 5))
        one = [(1, 1, 0, 1)] * 10                                         # every session identical: no spread at all
        self.assertEqual(set(U.resample(one, 50, 1)), {1.0})

    def test_t_quantile_and_expanded_multiplier(self):
        for df, table in ((3, 3.182), (9, 2.262), (19, 2.093), (29, 2.045), (60, 2.000)):
            self.assertAlmostEqual(U.t975(df), table, delta=0.004)
        self.assertAlmostEqual(U.z_expanded(20), (20 / 19) ** 0.5 * U.t975(19))
        self.assertGreater(U.z_expanded(10), U.z_expanded(40))
        self.assertGreater(U.z_expanded(40), U.Z975)

    def test_quantile_interpolates(self):
        self.assertEqual(U._quantile([0.0, 1.0, 2.0, 3.0, 4.0], 0.5), 2.0)
        self.assertAlmostEqual(U._quantile([0.0, 10.0], 0.25), 2.5)

    def test_p_value_two_sided_smoothed(self):
        self.assertEqual(U.p_value([0.1] * 99), 2 / 100)                 # never exactly 0
        self.assertEqual(U.p_value([-1.0, 1.0] * 50), 1.0)
        self.assertAlmostEqual(U.p_value([-0.1] * 10 + [0.1] * 90), 2 * 11 / 101)

    def test_sessions_needed_scales_variance(self):
        ds = [-0.1, 0.1] * 500                                             # variance ~ 0.01
        var = sum(d * d for d in ds) / (len(ds) - 1)
        self.assertEqual(U.sessions_needed(ds, 0.05, 30), math.ceil(30 * (U.Z975 + U.Z80) ** 2 * var / 0.05 ** 2))
        self.assertIsNone(U.sessions_needed(ds, 0.0, 30))


class TestInterval(unittest.TestCase):
    def test_percentile_when_unbiased(self):
        ss = data(40)
        ds = U.resample(ss, 2000, 3)
        iv = U.interval(ss, ds, U.diff(ss))
        self.assertEqual(iv["method"], "expanded percentile")
        xs = sorted(ds)
        self.assertAlmostEqual(iv["lo"], U._quantile(xs, U.N.cdf(-U.z_expanded(40))))
        self.assertLess(iv["lo"], U._quantile(xs, 0.025))                  # wider than the plain percentile

    def test_bca_when_biased(self):
        ss = data(30)
        est = U.diff(ss)
        biased = [est + 0.01 * (i % 7 - 1) for i in range(1000)]          # most resamples above the estimate: z0 large
        iv = U.interval(ss, biased, est)
        self.assertEqual(iv["method"], "BCa")
        self.assertGreater(abs(iv["z0"]), U.BIAS_LIMIT)
        self.assertLessEqual(iv["lo"], iv["hi"])


class TestSummary(unittest.TestCase):
    def test_clear_edge_and_no_edge(self):
        strong = U.summarize(data(60, 0.8, 0.2), 2000)
        self.assertGreater(strong["interval"][0], 0)
        self.assertEqual(strong["headline"], "more rejections than the baseline (60 sessions)")
        self.assertEqual(strong["power_label"], "optimistic")
        none = U.summarize(data(25, 0.3, 0.3, seed=4), 2000)
        self.assertLessEqual(none["interval"][0], 0)
        self.assertGreaterEqual(none["interval"][1], 0)
        self.assertEqual(none["headline"], "no proven edge yet (25 sessions)")

    def test_unavailable_is_named(self):
        self.assertIn("unavailable", U.summarize([(0, 0, 1, 5)] * 5, 100))
        self.assertIn("one session", U.summarize([(1, 1, 1, 5)], 100)["unavailable"])
        sparse = [(1, 1, 1, 5)] + [(0, 0, 1, 5)] * 30                     # most resamples miss the one real touch
        self.assertIn("10%", U.summarize(sparse, 500)["unavailable"])

    def test_reproducible(self):
        self.assertEqual(U.summarize(data(30), 1000), U.summarize(data(30), 1000))


if __name__ == "__main__":
    unittest.main()
