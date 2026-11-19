"""Rule tester (gexpro/rules.py): every fill rule on hand-made bars, one position at a time, the walk-forward's
choice from earlier sessions only, and the refusal under 30 out-of-sample trades."""
import json
import random
import unittest
from datetime import date

from gexpro import reaction_lab as L
from gexpro import rules as R
from gexsys import marketcal

D, SHA = R.definition()
RULES = L.definition()[0]["rules"]
P = {"s": 2, "t": 1, "T": 30}
FLAT = [100, 101, 99, 100]


def sess(levels, ohlc, day="2026-11-18", market="NQ", em=100.0, roll=False):
    """open 100, previous close 100, tol = max(2 ticks, 0.05 x 100) = 5."""
    return {"session": day, "market": market, "regime": "NEGATIVE", "open": 100.0, "em": em, "prev_close": 100.0,
            "levels": levels, "ohlc": ohlc, "bars": [[b[0], b[2], b[3], b[4]] for b in ohlc], "roll_week": roll}


def bars(*rows):
    return [[i, *r] for i, r in enumerate(rows)]


def one(s, p=P, fees=4.0):
    trig = R.triggers(s, RULES)[0]
    return R.trade(s, trig, p, RULES, D, fees)


# short at CW 120: the touch is minute 1 (high 116 >= 115); entry = minute 2's open 114 - 1 tick = 113.75;
# s=2: stop 130, R 16.25; t=1: target 97.5
TOUCH = [[100, 101, 99, 100], [100, 116, 100, 114], [114, 115, 110, 111]]


class TestDefinition(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(len(SHA), 64)
        self.assertEqual(len(R.grid(D)), D["grid"]["points"])
        self.assertEqual(R.grid(D)[:2], [{"s": 2, "t": 1, "T": 30}, {"s": 2, "t": 1, "T": 60}])
        self.assertEqual((D["min_oos_trades"], D["walk_forward"]["min_train_sessions"]), (30, 20))
        self.assertEqual(D["units"]["fees_round_turn_usd"], 4.0)

    def test_every_rule_version_is_in_the_tries_log(self):
        log = json.loads(R.TRIES.read_text(encoding="utf-8"))["tries"]
        self.assertIn({"rule": D["rule"], "version": D["version"], "grid_points": D["grid"]["points"]},
                      [{k: x[k] for k in ("rule", "version", "grid_points")} for x in log])
        self.assertEqual(R.tries(), sum(x["grid_points"] for x in log))


class TestBars(unittest.TestCase):
    def test_rth_only_minutes_from_the_open(self):
        day = date(2026, 11, 27)                                            # early close 13:00
        o, c = marketcal.rth_open_dt(day).timestamp(), marketcal.rth_close_dt(day).timestamp()
        raw = {"bars": [[o - 60, 1, 1, 1, 1, 0], [o, 2, 3, 1, 2, 5], [o + 120, 2, 2, 2, 2, 0],
                        [o + 180, None, 2, 2, 2, 0], [c - 60, 4, 4, 4, 4, 0], [c, 5, 5, 5, 5, 0]]}
        self.assertEqual(R.rth_bars(raw, day), [[0, 2, 3, 1, 2], [2, 2, 2, 2, 2], [209, 4, 4, 4, 4]])

    def test_join_names_missing_days(self):
        skipped = []
        t = [{"session": "2026-11-18", "market": "NQ"}, {"session": "2026-11-17", "market": "NQ"}]
        o = marketcal.rth_open_dt(date(2026, 11, 18)).timestamp()
        got = R.join(t, {("2026-11-18", "NQ"): {"bars": [[o, 1, 2, 0, 1, 0]], "roll_week": True}}, skipped)
        self.assertEqual((len(got), got[0]["bars"], got[0]["roll_week"]), (1, [[0, 2, 0, 1]], True))
        self.assertEqual(skipped, ["2026-11-17_NQ: no archive bars"])


class TestFills(unittest.TestCase):
    def test_target_short(self):
        t = one(sess({"CW": 120.0}, bars(*TOUCH, [111, 112, 97, 98])))
        self.assertEqual((t["side"], t["entry"], t["stop"], t["R"], t["target"]), ("short", 113.75, 130.0, 16.25, 97.5))
        self.assertEqual((t["why"], t["exit"], t["pts"], t["usd"]), ("target", 97.75, 16.0, 16.0 * 20 - 4.0))
        self.assertAlmostEqual(t["r"], 16.0 / 16.25)

    def test_stop_uses_the_exact_level_not_the_rounded_one(self):
        t = one(sess({"CW": 120.004}, bars(*TOUCH, [111, 112, 97, 98])))
        self.assertAlmostEqual(t["stop"], 130.004, places=9)
        self.assertEqual(t["level"], 120.004)

    def test_stop_first_inside_one_bar(self):
        t = one(sess({"CW": 120.0}, bars(*TOUCH, [111, 131, 97, 98])))
        self.assertEqual((t["why"], t["exit"], t["pts"]), ("stop", 130.25, -16.5))

    def test_stop_gap_fills_at_the_worse_open(self):
        t = one(sess({"CW": 120.0}, bars(*TOUCH, [133, 135, 132, 133])))
        self.assertEqual((t["why"], t["exit"]), ("stop", 133.25))

    def test_target_gap_is_never_better(self):
        t = one(sess({"CW": 120.0}, bars(*TOUCH, [90, 92, 89, 91])))
        self.assertEqual((t["why"], t["exit"]), ("target", 97.75))

    def test_time_exit_at_the_next_bar_open(self):
        quiet = [[112, 113, 111, 112]] * 40
        t = one(sess({"CW": 120.0}, bars(*TOUCH, *quiet)))
        self.assertEqual((t["why"], t["entry_min"], t["exit_min"], t["exit"]), ("time", 2, 32, 112.25))

    def test_flat_by_the_close(self):
        t = one(sess({"CW": 120.0}, bars(*TOUCH, [112, 113, 111, 110])), {"s": 2, "t": 1, "T": 60})
        self.assertEqual((t["why"], t["exit_min"], t["exit"]), ("close", 3, 110.25))

    def test_long_mirror(self):
        rows = [[100, 101, 99, 100], [100, 100, 84, 86], [86, 90, 85, 89], [89, 103, 88, 102]]
        t = one(sess({"PW": 80.0}, bars(*rows)))                          # entry 86.25, stop 70, R 16.25, target 102.5
        self.assertEqual((t["side"], t["entry"], t["stop"], t["target"], t["why"], t["exit"]),
                         ("long", 86.25, 70.0, 102.5, "target", 102.25))

    def test_no_trade_cases(self):
        beyond = sess({"CW": 120.0}, bars(TOUCH[0], TOUCH[1], [131, 132, 129, 131]))
        self.assertEqual(one(beyond), {"skip": "entry at or beyond the stop"})
        last = sess({"CW": 120.0}, bars(TOUCH[0], TOUCH[1]))
        self.assertEqual(one(last), {"skip": "no RTH bar after the trigger"})

    def test_one_position_at_a_time(self):
        # CW 120 short from minute 2 to its target at minute 4; C1 128 (not within tol of CW) touched at 2: skipped
        rows = [[100, 101, 99, 100], [100, 116, 100, 114], [114, 126, 110, 112],
                [112, 112, 111, 111], [111, 112, 97, 98], [98, 99, 97, 98], [98, 99, 97, 98]]
        lv = {"CW": 120.0, "C1": 128.0}
        self.assertEqual([(t["type"], t["minute"]) for t in R.triggers(sess(lv, bars(*rows)), RULES)], [("CW", 1), ("C1", 2)])
        ts, _ = R.session_trades(sess(lv, bars(*rows)), P, RULES, D, 4.0)
        self.assertEqual([(t["type"], t["entry_min"], t["exit_min"]) for t in ts], [("CW", 2, 4)])
        rows[2], rows[5] = [114, 115, 110, 112], [98, 131, 97, 125]        # C1 now touched at 5, after CW's exit at 4
        ts, _ = R.session_trades(sess(lv, bars(*rows)), P, RULES, D, 4.0)
        self.assertEqual([(t["type"], t["entry_min"]) for t in ts], [("CW", 2), ("C1", 6)])

def fake(usd, r=None, session="s"):
    return {"usd": usd, "r": usd / 100 if r is None else r, "pts": usd / 20, "session": session}


class TestWalkForward(unittest.TestCase):
    def test_choose_best_mean_dollars_ties_first(self):
        train = [[[fake(10)], [fake(30)], [], [fake(30)]], [[fake(10)], [fake(-10)], [], [fake(10)]]]
        self.assertEqual(R.choose(train), 3)                               # means 10, 10, -, 20
        self.assertEqual(R.choose([[[], []]]), 0)

    def test_choices_use_earlier_sessions_only(self):
        rng = random.Random(1)
        def mk(i):
            hi = 116 + rng.random() * 30
            rows = [[100, 101, 99, 100], [100, hi, 100, 114]] + [[114 - k, 115 - k, 110 - k * rng.random() * 3, 113 - k]
                                                                    for k in range(70)]
            return sess({"CW": 120.0}, bars(*rows), day=f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}")
        ss = [mk(i) for i in range(26)]
        wf = R.walk_forward(ss, D, RULES, 4.0)
        self.assertEqual([o["trained_on"] for o in wf["oos"]], list(range(20, 26)))
        G = R.grid(D)
        per = [[R.session_trades(x, p, RULES, D, 4.0)[0] for p in G] for x in ss]
        self.assertEqual([o["grid"] for o in wf["oos"]], [G[R.choose(per[:k])] for k in range(20, 26)])
        self.assertNotEqual(wf["oos"][0]["grid"], G[0])                       # a real choice, not the default
        changed = ss[:-1] + [dict(ss[-1], ohlc=[[b[0], 500, 500, 1, 2] for b in ss[-1]["ohlc"]])]
        again = R.walk_forward(changed, D, RULES, 4.0)
        self.assertEqual([o["grid"] for o in wf["oos"]], [o["grid"] for o in again["oos"]])


class TestRun(unittest.TestCase):
    def test_roll_weeks_and_shifts_are_applied(self):
        rng, track, raw = random.Random(4), [], {}
        for m in R.MARKETS:
            for i in range(55):
                rows = [[100, 101, 99, 100], [100, 117, 100, 114]] + [
                    [114 - k * 0.5, 115 - k * 0.5, 112 - k * rng.random(), 113 - k * 0.5] for k in range(70)]
                x = sess({"CW": 120.0}, bars(*rows), day=f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", market=m)
                o = marketcal.rth_open_dt(date.fromisoformat(x["session"])).timestamp()
                raw[(x["session"], m)] = {"bars": [[o + 60 * b[0], *b[1:], 0] for b in x["ohlc"]], "roll_week": i % 5 == 0}
                track.append({k: v for k, v in x.items() if k not in ("ohlc", "bars", "roll_week")})
        res = R.run(track, raw, reps=200)
        nq = res["markets"]["NQ"]
        self.assertEqual((nq["status"], nq["oos_trades"], nq["roll_week_sessions"], nq["data_through"]),
                         ("tested", 35, 11, "2026-02-27"))
        self.assertEqual(nq["without_roll_weeks"]["oos_trades"], 35 - 7)          # i = 20, 25, ..., 50
        self.assertEqual(set(res["markets"]["ES"]["shifted"]), {"+1", "-1"})
        # CW + 5 = 125 needs a high of 120 to be touched and the highs stop at 117: no trades; CW - 5 = 115 trades
        self.assertEqual((nq["shifted"]["+5"]["oos_trades"], nq["shifted"]["-5"]["oos_trades"]), (0, 35))


class TestSummary(unittest.TestCase):
    def wf(self, per_session):
        return {"sessions": 20 + len(per_session), "skips": {},
                "oos": [{"session": f"d{i}", "roll_week": False, "grid": P, "trained_on": 20 + i, "in_sample_r": 0.5,
                         "trades": [fake(u, session=f"d{i}") for u in us]} for i, us in enumerate(per_session)]}

    def test_refuses_under_30_trades(self):
        r = R.summarize(self.wf([[10, -5]] * 14 + [[1]]), D, 8)
        self.assertEqual((r["status"], r["oos_trades"], r["reason"]), ("not enough data", 29, "29 of 30 out-of-sample trades"))
        self.assertNotIn("per_trade", r)

    def test_statistics(self):
        r = R.summarize(self.wf([[100, -50], [-50, -50], [200]] * 10), D, 8, reps=500)
        self.assertEqual((r["status"], r["oos_trades"], r["win_rate"]), ("tested", 50, 0.4))
        self.assertAlmostEqual(r["per_trade"]["usd"]["mean"], 1500 / 50)          # 10 x (50 - 100 + 200) over 50 trades
        self.assertEqual((r["avg_win"]["usd"], r["avg_loss"]["usd"]), (150.0, -50.0))
        self.assertEqual((r["max_drawdown_usd"], r["longest_losing_streak"]), (150.0, 3))
        self.assertEqual(r["equity"]["curve"][:3], [50.0, -50.0, 150.0])
        self.assertEqual((r["in_sample_r"], r["out_of_sample_r"]), (0.5, 0.3))
        self.assertEqual(r["p_adjusted"], round(min(1.0, r["per_trade"]["r"]["p_value"] * 8), 4))
        lo, hi = r["equity"]["lo"][-1], r["equity"]["hi"][-1]
        self.assertLess(lo, r["equity"]["curve"][-1])
        self.assertGreater(hi, r["equity"]["curve"][-1])

    def test_drawdown_and_streak(self):
        self.assertEqual(R.max_drawdown([10, -5, -20, 30, -40]), 40.0)
        self.assertEqual(R.losing_streak([-1, 2, -1, -1, -1, 0, -1]), 3)


if __name__ == "__main__":
    unittest.main()
