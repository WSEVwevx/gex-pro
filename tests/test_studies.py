"""The Backtesting tab's file (gexpro/studies.py): sample-needed estimates, the verdict, and the cache that recomputes
only when its key changes and keeps the last good result, flagged, when a run fails."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gexpro import rules as R
from gexpro import studies as ST

D_RULES = R.definition()[0]


def lab_row(t, touches, small=True, **c):
    cell = {"sessions": 21, "touches": touches, **({"small": True} if small else {}), **c}
    return {"market": "NQ", "type": t, "all": cell, "no_roll_weeks": {"touches": touches}}


def split(name, **groups):
    return {"split": name, "market": "NQ", "status": "not enough data", "groups": {g: {"sessions": n} for g, n in groups.items()},
            "unavailable": {}}


class TestNeeds(unittest.TestCase):
    def test_trading_days_skip_weekends_and_holidays(self):
        self.assertEqual(ST.trading_days_after("2026-11-25", 1), "2026-11-27")        # Thanksgiving 11-26
        self.assertEqual(ST.trading_days_after("2026-11-20", 1), "2026-11-23")
        self.assertEqual(ST.trading_days_after("2026-11-20", 0), "2026-11-20")

    def test_needs_count_every_session_of_the_market(self):
        rows = [lab_row("ZG", 4), lab_row("CW", 2), lab_row("C1", 0)]
        tests = [split("regime", POSITIVE=1, NEGATIVE=17), split("zg_distance", near=5, far=16), split("vol_tercile", low=0, mid=5, high=16)]
        n = ST.needs("NQ", rows, tests, 21, 21 / 21, 1, "2026-11-18", D_RULES)
        self.assertEqual([(x["study"], x["have"], x["need"]) for x in n],
                         [("level_reaction", 21, 105), ("splits", 21, 84), ("rules", 1, 50)])   # 20x21/4, 20x21/5, 20+30/1
        self.assertIn("ZG", n[0]["basis"])
        self.assertIn("zg_distance", n[1]["basis"])
        self.assertEqual(n[0]["est_date"], ST.trading_days_after("2026-11-18", 84))
        self.assertFalse(n[2]["reached"])

    def test_nothing_touched_and_reached(self):
        n = ST.needs("NQ", [lab_row("ZG", 0)], [split("regime", POSITIVE=0, NEGATIVE=3)], 3, None, 0, "2026-11-18", D_RULES)
        self.assertEqual([x["need"] for x in n], [None, None, None])
        self.assertEqual(n[0]["basis"], "no level touched yet")
        r = ST.need_row("splits", 90, 84, "2026-11-18", "x")
        self.assertEqual((r["reached"], r["est_date"]), (True, None))


def fake_inputs(edge_level=False, survive=False):
    cell = {"sessions": 21, "touches": 25, "reject": 0.6, "baseline": 0.3, "difference": 0.3, "interval": [0.1, 0.5],
            "interval_method": "expanded percentile", "p_value": 0.01} if edge_level else {"sessions": 21, "touches": 4, "small": True}
    row = {"market": "NQ", "type": "ZG", "all": cell, "no_roll_weeks": {"touches": cell["touches"]}}
    lab = {"main": {"definition_sha256": "a" * 64, "seed": 1, "version": 2, "data_through": "2026-11-18",
                    "baseline_per_type": 1000, "bootstrap_reps": 10000, "table": [row]},
           "shift_up": {"table": [row]}, "shift_down": {"table": [row]}}
    test = dict(split("regime", POSITIVE=20, NEGATIVE=20), status="tested", p_value=0.01, survives=survive,
                verdict="difference found" if survive else "no difference found")
    sp = {"definition_sha256": "b" * 64, "version": 1, "registered": 14, "tested": 1, "survivors": ["regime:NQ"] if survive else [],
          "q": 0.1, "permutations": 10000, "tests": [test]}
    ru = {"rule": "fade_first_touch", "version": 1, "definition_sha256": "c" * 64, "tries": 8, "fees_round_turn_usd": 4.0,
          "data_from": "2026-11-18", "data_through": "2026-11-18",
          "markets": {"NQ": {"status": "not enough data", "oos_trades": 0, "sessions": 1}, "ES": {"status": "not enough data", "oos_trades": 0}}}
    sessions = [{"session": f"2026-11-{d:02d}", "market": "NQ", "roll_week": False} for d in (16, 17, 18)]
    return lab, sp, ru, sessions


class TestPayload(unittest.TestCase):
    def test_no_edge_and_counts(self):
        p = ST.payload(*fake_inputs(), {"NQ": 1})
        m = p["markets"]["NQ"]
        self.assertEqual(m["verdict"], {"edge": [], "text": "no proven edge yet (3 sessions)"})
        self.assertEqual(m["counts"], {"level_types": 1, "level_types_20": 0, "splits_registered": 1, "splits_tested": 1,
                                       "oos_trades": 0, "oos_needed": 30})
        self.assertEqual((m["data_from"], m["data_through"], m["archive_sessions"]), ("2026-11-16", "2026-11-18", 1))
        self.assertEqual(m["level_reaction"][0]["shifted"], {"+5": None, "-5": None})
        self.assertEqual(p["markets"]["ES"]["needs"], [])                     # no ES sessions: nothing to estimate
        self.assertEqual(p["definitions"], {"level_reaction": "a" * 64, "splits": "b" * 64, "rules": "c" * 64})

    def test_evidence_names_the_study(self):
        m = ST.payload(*fake_inputs(edge_level=True, survive=True), {"NQ": 1})["markets"]["NQ"]
        self.assertEqual(m["verdict"]["edge"], ["level ZG", "split regime"])
        self.assertEqual(m["level_reaction"][0]["shifted"], {"+5": 0.3, "-5": 0.3})


class TestCache(unittest.TestCase):
    def test_reuses_recomputes_and_keeps_the_last_good_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = Path(tmp)
            with mock.patch.object(ST, "key", return_value="k1"), mock.patch.object(ST, "compute", return_value={"n": 1}) as c:
                self.assertEqual(ST.current(st), {"n": 1, "key": "k1"})
                self.assertEqual(ST.current(st), {"n": 1, "key": "k1"})
                self.assertEqual(c.call_count, 1)                              # same key: the saved copy
            with mock.patch.object(ST, "key", return_value="k2"), mock.patch.object(ST, "compute", side_effect=OSError("git down")):
                got = ST.current(st)
                self.assertEqual((got["n"], got["key"], got["error"]), (1, "k1", "OSError: git down"))
            self.assertEqual(json.loads((st / "studies.json").read_text())["key"], "k1")   # the failure is not saved
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(ST, "key", side_effect=OSError("no git")):
                self.assertEqual(ST.current(Path(tmp)), {"unavailable": "the studies could not run: OSError: no git"})


class TestHealthRow(unittest.TestCase):
    def test_row_from_the_saved_result(self):
        from datetime import datetime, timezone
        from gexpro.health import status
        now = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            c = ST.StudiesComponent(Path(tmp))
            self.assertEqual(status(c.sources()[0], now), "waiting")
            (Path(tmp) / "studies.json").write_text(json.dumps({"computed_at": "2026-11-19T02:00:00+00:00"}))
            self.assertEqual(status(c.sources()[0], now), "ok")
            (Path(tmp) / "studies.json").write_text(json.dumps({"computed_at": "2026-11-15T02:00:00+00:00", "error": "OSError: x"}))
            row = c.sources()[0]
            self.assertEqual((status(row, now), row["error"]), ("failing", "OSError: x"))

if __name__ == "__main__":
    unittest.main()
