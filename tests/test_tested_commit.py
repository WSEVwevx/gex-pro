"""The deploy gate: the website builds only the newest commit whose tests passed (.github/scripts/tested_commit.py)."""
import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("tested_commit", Path(__file__).resolve().parent.parent / ".github" / "scripts" / "tested_commit.py")
tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tc)


def runs(table):
    return lambda sha: table.get(sha, [])


class TestChoose(unittest.TestCase):
    def test_head_passed(self):
        self.assertEqual(tc.choose(["c", "b"], runs({"c": ["success"]}))[0], "c")

    def test_failed_head_falls_back_to_last_good(self):
        sha, log = tc.choose(["c", "b", "a"], runs({"c": ["failure"], "b": [None], "a": ["success"]}))
        self.assertEqual(sha, "a")
        self.assertIn("skip c: tests failure", log)
        self.assertIn("skip b: still testing", log)

    def test_untested_head_waits_for_its_tests(self):
        # a push starts a website run at once, before its tests finish: the previous good commit is built meanwhile
        self.assertEqual(tc.choose(["new", "old"], runs({"old": ["success"]}))[0], "old")

    def test_a_rerun_that_passed_counts(self):
        self.assertEqual(tc.choose(["c"], runs({"c": ["failure", "success"]}))[0], "c")

    def test_gate_just_added_builds_head(self):
        sha, log = tc.choose(["c", "b"], runs({}))
        self.assertEqual(sha, "c")
        self.assertIn("gate just added", log[-1])

    def test_tested_but_none_passed_builds_nothing(self):
        sha, log = tc.choose(["c", "b"], runs({"c": ["failure"], "b": ["cancelled"]}))
        self.assertIsNone(sha)
        self.assertIn("live site stays", log[-1])


if __name__ == "__main__":
    unittest.main()
