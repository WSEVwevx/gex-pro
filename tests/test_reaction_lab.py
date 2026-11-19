"""Study level_reaction v1 (gexpro/reaction_lab.py): every rule of studies/level_reaction/v1.json on hand-made bars."""
import json
import unittest

from gexpro import reaction_lab as L

RULES = L.definition()[0]["rules"]


def sess(bars, levels, open_=100.0, em=40.0, prev=99.0, market="NQ", session="2026-11-10"):
    """em 40 -> tol = max(0.5, 2.0) = 2.0, k x tol = 8."""
    return {"session": session, "market": market, "regime": "NEGATIVE", "open": open_, "em": em, "prev_close": prev,
            "levels": levels, "bars": bars, "roll_week": False, "has_paste": True}


def flat(n, p=100.0):
    return [[m, p + 0.5, p - 0.5, p] for m in range(n)]


class TestDefinition(unittest.TestCase):
    def test_locked_values(self):
        d, sha = L.definition()
        self.assertEqual((d["version"], RULES["k"], d["statistics"]["min_n"]), (2, 4, 20))
        self.assertEqual(len(sha), 64)

    def test_paste_levels_first_three_in_written_order(self):
        p = "GEX1;mkt=NQ;R=C28590.00:2.4,C27150.00:2.1,C27730.00:1.5,C27900.00:0.8,P27000.00:6.8,P26550.00:4.8,A27775.00:5.8;x0=0DTE"
        self.assertEqual(L.paste_levels(p), {"C1": 28590.0, "C2": 27150.0, "C3": 27730.0, "P1": 27000.0, "P2": 26550.0})

    def test_session_input_maps_with_the_0930_ratio(self):
        s = L.session_input({"session": "2026-11-10", "market": "ES", "plan": {"zg": 100.0, "cw": None, "em": 10.0, "regime": "X"}},
                            {"ratio": 1.01, "index_open": 200.0, "bars": [], "close_min": 390}, None, 190.0)
        self.assertAlmostEqual(s["levels"]["ZG"], 101.0)
        self.assertEqual(set(s["levels"]), {"ZG"})
        self.assertAlmostEqual(s["open"], 202.0)
        self.assertAlmostEqual(s["prev_close"], 191.9)
        self.assertAlmostEqual(s["em"], 10.1)


class TestLoad(unittest.TestCase):
    def files(self):
        def one(d, m, em=40.0, status="graded", close=100.0):
            return json.dumps({"session": d, "market": m, "status": status, "plan": {"zg": 110.0, "em": em, "regime": "X"},
                               "outcome": {"close": close}}).encode()
        mins = json.dumps({"ratio": 1.0, "index_open": 100.0, "bars": [[0, 101, 99, 100]], "close_min": 390}).encode()
        return {"sessions/2026-11-06_NQ.json": one("2026-11-06", "NQ", close=95.0),           # Friday, no minutes
                "sessions/2026-11-09_NQ.json": one("2026-11-09", "NQ"),                        # Monday
                "minutes/2026-11-09_NQ.json": mins, "pastes/2026-11-09_NQ.txt": b"R=C120.00:1,P80.00:1",
                "sessions/2026-11-10_NQ.json": one("2026-11-10", "NQ", em=None), "minutes/2026-11-10_NQ.json": mins,
                "sessions/2026-11-11_NQ.json": one("2026-11-11", "NQ", status="missed"),
                "sessions/2026-11-12_NQ.json": one("2026-11-12", "NQ"), "minutes/2026-11-12_NQ.json": mins}

    def test_previous_trading_day_paste_and_skips(self):
        skipped = []
        ss = L.load(files=self.files(), skipped=skipped)
        self.assertEqual([s["session"] for s in ss], ["2026-11-09", "2026-11-12"])
        self.assertEqual(ss[0]["prev_close"], 95.0)                       # Monday's previous close is Friday's
        self.assertEqual(set(ss[0]["levels"]), {"ZG", "C1", "P1"})
        self.assertIsNone(ss[1]["prev_close"])                            # Wednesday was missed
        self.assertEqual(skipped, ["2026-11-06_NQ: no 1-minute record", "2026-11-10_NQ: the plan has no expected move",
                                   "2026-11-12_NQ: the previous trading day has no graded close (levels counted as no_prior_close)"])

    def test_constants_match_the_definition_text(self):
        d = L.definition()[0]
        self.assertIn(f"{L.DRAWS} random levels", d["baseline"]["draws"])
        self.assertIn(f"seed {L.SEED}", d["baseline"]["draws"])
        self.assertIn(f"{L.REPS:,} session resamples, seed {L.SEED}", d["statistics"]["interval"])


class TestClassify(unittest.TestCase):
    def test_tol(self):
        self.assertEqual(L.tol_of(sess([], {}, em=4.0), RULES), 0.5)          # 2 ticks beats 0.05 x 4
        self.assertEqual(L.tol_of(sess([], {}), RULES), 2.0)

    def test_at_open_gap_through_untouched(self):
        s = sess(flat(10), {})
        self.assertEqual(L.classify(101.5, s, RULES)["cat"], "at_open")
        self.assertEqual(L.classify(110.0, sess(flat(10), {}, prev=120.0), RULES)["cat"], "gap_through")
        self.assertEqual(L.classify(110.0, s, RULES), {"cat": "untouched", "side": "above"})
        self.assertEqual(L.classify(110.0, sess(flat(10), {}, prev=None), RULES)["cat"], "no_prior_close")

    def test_touch_then_reject(self):
        bars = flat(3) + [[3, 108.5, 104, 107], [4, 107, 101.5, 102]] + flat(100)[5:]
        r = L.classify(110.0, sess(bars, {}), RULES)                         # touch: high >= 108; reject: low <= 102
        self.assertEqual((r["minute"], r["outcome"], r["minutes_to_resolution"], r["bucket"]), (3, "reject", 1, "09:30-10:30"))

    def test_the_touch_bar_itself_cannot_reject(self):
        bars = flat(3) + [[3, 108.5, 101.0, 107]] + [[m, 107.5, 106.5, 107] for m in range(4, 100)]
        self.assertEqual(L.classify(110.0, sess(bars, {}), RULES)["outcome"], "stall")

    def test_break_on_a_close_beyond_tol(self):
        bars = flat(3) + [[3, 109, 105, 108], [4, 113, 108, 112.5]] + [[m, 113, 112, 112.5] for m in range(5, 100)]
        r = L.classify(110.0, sess(bars, {}), RULES)
        self.assertEqual((r["outcome"], r["minutes_to_resolution"]), ("break", 1))

    def test_same_bar_reject_and_break_is_a_break(self):
        bars = flat(3) + [[3, 108.5, 104, 107], [4, 113, 101, 112.5]] + flat(100)[5:]
        self.assertEqual(L.classify(110.0, sess(bars, {}), RULES)["outcome"], "break")

    def test_level_below_mirrors(self):
        bars = flat(3) + [[3, 96, 91.5, 93], [4, 98.5, 94, 98]] + flat(100)[5:]
        r = L.classify(90.0, sess(bars, {}), RULES)                          # touch: low <= 92; reject: high >= 98
        self.assertEqual((r["side"], r["outcome"]), ("below", "reject"))

    def test_stall_after_60_minutes(self):
        bars = flat(3) + [[m, 108.5, 104, 107] for m in range(3, 100)]
        self.assertEqual(L.classify(110.0, sess(bars, {}), RULES)["outcome"], "stall")

    def test_excursions_and_horizon_past_close(self):
        bars = flat(3) + [[3, 108.5, 104, 107]] + [[m, 109, 100, 105] for m in range(4, 40)]
        r = L.classify(110.0, sess(bars, {}), RULES)
        self.assertEqual(r["excursions"][15], {"away": 10.0, "through": -1.0, "away_em": 0.25, "through_em": -0.025})
        self.assertIsNone(r["excursions"][60])                               # 3 + 60 > the last minute (39)

    def test_time_buckets(self):
        self.assertEqual([L.bucket(m) for m in (0, 59, 60, 329, 330, 389)],
                         ["09:30-10:30", "09:30-10:30", "10:30-15:00", "10:30-15:00", "15:00-close", "15:00-close"])


class TestClustersAndBaseline(unittest.TestCase):
    def test_cluster_keeps_the_first_in_order(self):
        rows = L.session_levels(sess(flat(10), {"C1": 110.0, "CW": 111.0, "PW": 80.0}), RULES)
        self.assertEqual({r["type"]: bool(r.get("dependent")) for r in rows}, {"CW": False, "PW": False, "C1": True})

    def test_baseline_is_seeded_and_avoids_real_levels(self):
        ss = [sess(flat(50, 100), {"ZG": 100.0 + 10 * (i + 1), "PW": 90.0 - 7 * i}, session=f"2026-11-{10 + i}") for i in range(3)]
        a = L.baseline(ss, [], RULES, 50, 7)
        self.assertEqual(a, L.baseline(ss, [], RULES, 50, 7))
        self.assertEqual(len(a), 100)
        one = [sess(flat(50), {"ZG": 110.0})]                                 # every draw lands on the real level
        self.assertEqual(L.baseline(one, [], RULES, 5, 7), [])
        for r in a:
            s = next(x for x in ss if x["session"] == r["session"])
            self.assertTrue(all(abs(r["level"] - v) > 2.0 for v in s["levels"].values()))

    def test_small_cells_have_no_rate(self):
        c = L.cell([{"cat": "touch", "outcome": "reject", "session": "d"}], [], {"min_n": 20}, 1, 10)
        self.assertTrue(c["small"])
        self.assertNotIn("reject", c)

    def test_per_session_counts(self):
        real = [{"cat": "touch", "outcome": "reject", "session": "a"}, {"cat": "touch", "outcome": "break", "session": "a"},
                {"cat": "untouched", "session": "b"}]
        rand = [{"cat": "touch", "outcome": "reject", "session": "b"}, {"cat": "touch", "outcome": "stall", "session": "z"}]
        self.assertEqual(L.per_session(real, rand), [(1, 2, 0, 0), (0, 0, 1, 1)])

    def test_cell_baseline_is_paired_and_subtracts(self):
        real = [{"cat": "touch", "outcome": "reject" if i % 2 else "break", "session": f"d{i % 10}"} for i in range(20)]
        rand = [{"cat": "touch", "outcome": "reject" if i % 4 == 0 else "stall", "session": f"d{i % 10}"} for i in range(40)]
        rand += [{"cat": "touch", "outcome": "reject", "session": "other"}] * 50     # a day without the level: ignored
        c = L.cell(real, rand, {"min_n": 20}, 1, 500)
        self.assertEqual((c["reject"], c["baseline"]), (0.5, 0.25))
        self.assertAlmostEqual(c["difference"], c["reject"] - c["baseline"])

if __name__ == "__main__":
    unittest.main()
