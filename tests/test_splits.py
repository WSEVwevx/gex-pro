"""Study splits v1 (gexpro/splits.py): every split input, the permutation test and Benjamini-Hochberg."""
import random
import unittest
from datetime import date, timedelta

from gexpro import splits as S


def sess(d, market="NQ", regime="NEGATIVE", ref=100.0, zg=110.0, em=40.0, roll=False):
    return {"session": d, "market": market, "regime": regime, "plan": {"ref": ref, "zg": zg, "em": em}, "roll_week": roll}


def ev(day, hh, title="CPI m/m", country="USD", impact="High"):
    return {"title": title, "country": country, "impact": impact, "time": f"{day}T{hh:02d}:30:00+00:00"}


class TestDefinition(unittest.TestCase):
    def test_constants_match_the_text(self):
        d, sha = S.definition()
        self.assertEqual(len(sha), 64)
        self.assertEqual([x["id"] for x in d["splits"]], list(S.SPLITS))
        self.assertEqual({x["id"]: x["groups"] for x in d["splits"]}, S.SPLITS)
        self.assertEqual(d["registered_tests"], len(S.SPLITS) * len(S.MARKETS))
        t = d["test"]
        self.assertIn(f"{S.PERMS:,} permutations, seed {S.SEED}", t["null"])
        self.assertEqual(t["min_group_sessions"], S.MIN_GROUP)
        self.assertIn(f"q = {S.Q:.2f}", t["multiple_testing"])


class TestInputs(unittest.TestCase):
    def test_tercile_cutoffs_and_minimum(self):
        h = [float(x) for x in range(1, 10)]                   # q1 = 3.667, q2 = 6.333
        self.assertEqual([S.tercile(v, h, 9) for v in (3.6, 3.7, 6.3, 6.4)], ["low", "mid", "mid", "high"])
        self.assertIsNone(S.tercile(5.0, h, 10))

    def test_vol_uses_the_previous_trading_day_and_252_earlier_closes(self):
        d0 = date(2025, 1, 2)
        closes = {(d0 + timedelta(days=i)).isoformat(): float(i) for i in range(400)}
        mon = date(2025, 11, 24)                                # previous trading day: Friday 11-21
        closes["2025-11-21"], closes["2025-11-24"] = 1e9, -1e9  # the session's own close must not be used
        self.assertEqual(S.vol_label(mon, closes), ("high", ""))
        short = {k: v for k, v in closes.items() if k >= "2025-06-01"}
        self.assertEqual(S.vol_label(mon, short), (None, "fewer than 252 earlier closes"))
        self.assertEqual(S.vol_label(date(2026, 6, 1), closes), (None, "no vol-index close for the previous trading day"))

    def test_zero_gamma_distance(self):
        self.assertEqual(S.zg_label({"ref": 100, "zg": 119.9, "em": 40}), ("near", ""))
        self.assertEqual(S.zg_label({"ref": 100, "zg": 80, "em": 40}), ("far", ""))
        self.assertEqual(S.zg_label({"ref": 100, "zg": None, "em": 40})[0], None)

    def test_event_day_usd_high_same_et_day_and_named(self):
        d = date(2026, 11, 19)
        cal = {"events": [ev("2026-11-19", 13), ev("2026-11-19", 14, "FOMC Member Speaks", impact="Medium"),
                          ev("2026-11-20", 13, "Federal Funds Rate"),              # 08:30 ET on the 20th: another day
                          ev("2026-11-19", 9, "CPI y/y", country="EUR")]}
        self.assertEqual(S.event_label(d, cal), ("event", "", ["CPI"]))
        late = {"events": [ev("2026-11-20", 2, "Non-Farm Employment Change")]}  # 21:30 ET on the 19th
        self.assertEqual(S.event_label(d, late), ("event", "", ["NFP"]))
        quiet = {"events": [ev("2026-11-18", 13)]}
        self.assertEqual(S.event_label(d, quiet)[0], "no_event")
        last_week = {"events": [ev("2026-11-13", 13)]}
        self.assertEqual(S.event_label(d, last_week), (None, "the saved calendar is for another week", []))
        self.assertEqual(S.event_label(d, None)[0], None)

    def test_opex_week_holiday_adjusted(self):
        self.assertEqual(S.opex_label(date(2026, 11, 16)), "opex_week")     # third Friday 11-20
        self.assertEqual(S.opex_label(date(2026, 11, 23)), "other")
        self.assertEqual(S.opex_label(date(2025, 4, 14)), "opex_week")      # Good Friday 4-18: expiry Thursday 4-17
        self.assertEqual(S.opex_label(date(2025, 4, 21)), "other")

    def test_zero_dte_share_and_trailing_cutoffs(self):
        snap = {"by_dte_bucket": {"0DTE": {"abs": 25.0}, "1DTE": {"abs": 25.0}, "2-7D": {"abs": 50.0}}}
        self.assertEqual(S.zero_dte_share(snap), 0.25)
        self.assertEqual(S.zero_dte_share({"by_dte_bucket": {"1DTE": {"abs": 5.0}}}), 0.0)
        self.assertIsNone(S.zero_dte_share({}))
        shares = {(date(2026, 1, 1) + timedelta(days=i)).isoformat(): i / 100 for i in range(70)}
        lab = S.dte_labels(shares)
        self.assertEqual(lab["2026-01-01"][0], None)                # the first day: no earlier sessions
        last = max(shares)
        self.assertEqual(lab[last][0], "high")                                 # cutoffs from earlier days only
        self.assertEqual(sum(v[0] is None for v in lab.values()), S.DTE_MIN)


class TestStatistics(unittest.TestCase):
    def test_counts_pool_types_and_skip_dependent(self):
        real = [{"cat": "touch", "outcome": "reject", "session": "a", "market": "NQ", "type": "ZG"},
                {"cat": "touch", "outcome": "break", "session": "a", "market": "NQ", "type": "CW"},
                {"cat": "touch", "outcome": "reject", "session": "a", "market": "NQ", "type": "C1", "dependent": True},
                {"cat": "untouched", "session": "b", "market": "NQ", "type": "ZG"}]
        rand = [{"cat": "touch", "outcome": "stall", "session": "a", "market": "NQ", "type": "ZG"}]
        self.assertEqual(S.counts(real, rand), {("a", "NQ"): (1, 2, 0, 1)})

    def test_statistic(self):
        g1, g2 = [(1, 1, 0, 2)] * 3, [(0, 1, 0, 2)]                            # d = 1 and 0; bar = 0.75
        self.assertAlmostEqual(S.statistic([g1, g2]), 3 * 0.25 ** 2 + 0.75 ** 2)
        self.assertIsNone(S.statistic([g1, [(0, 0, 1, 2)]]))

    def test_permutation_separates_and_is_seeded(self):
        rng = random.Random(3)
        mk = lambda p: (sum(rng.random() < p for _ in range(3)), 3, sum(rng.random() < 0.3 for _ in range(20)), 20)
        strong = [[mk(0.9) for _ in range(25)], [mk(0.1) for _ in range(25)]]
        same = [[mk(0.4) for _ in range(25)], [mk(0.4) for _ in range(25)]]
        self.assertLess(S.permutation_p(strong, 999, 1), 0.01)
        self.assertGreater(S.permutation_p(same, 999, 1), 0.05)
        self.assertEqual(S.permutation_p(same, 300, 7), S.permutation_p(same, 300, 7))

    def test_benjamini_hochberg(self):
        p = {"a": 0.001, "b": 0.02, "c": 0.03, "d": 0.2, "e": 0.9}            # cutoffs 0.02 0.04 0.06 0.08 0.10
        self.assertEqual(S.bh(p), {"a", "b", "c"})
        self.assertEqual(S.bh({"a": 0.5, "b": 0.6}), set())
        self.assertEqual(S.bh({"a": 0.04, "b": 0.05}, 0.10), {"a", "b"})      # step-up: b passes, so a does too


class TestRun(unittest.TestCase):
    def test_not_enough_data_shows_n_only_and_registers_all(self):
        ss = [sess(f"2026-11-{d:02d}") for d in (16, 17, 18)]
        r = S.run(ss, {}, {}, {}, {}, perms=50)
        self.assertEqual((r["registered"], r["tested"], r["survivors"]), (14, 0, []))
        t = r["tests"][0]
        self.assertEqual((t["id"], t["status"], t["seed"]), ("regime:NQ", "not enough data", S.SEED))
        self.assertEqual(t["groups"], {"POSITIVE": {"sessions": 0}, "NEGATIVE": {"sessions": 3}})
        self.assertEqual(r["tests"][1]["id"], "regime:ES")
        self.assertEqual(r["tests"][-1]["seed"], S.SEED + 13)
        ev_t = next(x for x in r["tests"] if x["id"] == "event_day:NQ")
        self.assertEqual(sum(ev_t["unavailable"].values()), 3)

    def test_a_real_difference_survives_with_intervals(self):
        rng = random.Random(5)
        ss, c = [], {}
        d = date(2025, 1, 6)
        while len(ss) < 60:
            if d.weekday() < 5:
                pos = len(ss) % 2 == 0
                s = sess(d.isoformat(), regime="POSITIVE" if pos else "NEGATIVE")
                p = 0.85 if pos else 0.15
                c[(s["session"], "NQ")] = (sum(rng.random() < p for _ in range(3)), 3, sum(rng.random() < 0.3 for _ in range(20)), 20)
                ss.append(s)
            d += timedelta(days=1)
        r = S.run(ss, c, {}, {}, {}, perms=500)
        t = r["tests"][0]
        self.assertEqual((t["status"], t["survives"], t["verdict"]), ("tested", True, "difference found"))
        self.assertIn("interval", t["groups"]["POSITIVE"])
        self.assertIn("regime:NQ", r["survivors"])
        zg = next(x for x in r["tests"] if x["id"] == "zg_distance:NQ")       # all sessions "near": one empty group
        self.assertEqual(zg["status"], "not enough data")


if __name__ == "__main__":
    unittest.main()
