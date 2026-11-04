import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gexpro.health import HealthComponent, collect, status

NOW = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)
ago = lambda h: (NOW - timedelta(hours=h)).isoformat()


class Fake:
    def __init__(self, name, rows=None, boom=False):
        self.name, self.rows, self.boom = name, rows or [], boom

    def sources(self):
        if self.boom:
            raise RuntimeError("cache unreadable")
        return self.rows


class TestStatus(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(status({"last_ok": ago(0.1), "fresh_h": 1}, NOW), "ok")
        self.assertEqual(status({"last_ok": ago(3), "fresh_h": 1}, NOW), "late")
        self.assertEqual(status({"last_ok": ago(0.1), "note": "backup in use"}, NOW), "partial")
        self.assertEqual(status({"last_ok": ago(0.1), "error": "HTTP 429"}, NOW), "failing")   # older copy still shown
        self.assertEqual(status({"last_ok": None, "error": "HTTP 429"}, NOW), "down")
        self.assertEqual(status({"last_ok": None}, NOW), "waiting")

    def test_weekly_report_date(self):
        # the CFTC report is a bare date; 8 days old is normal for a weekly report
        self.assertEqual(status({"last_ok": "2026-10-27", "fresh_h": 11 * 24}, NOW), "ok")
        self.assertEqual(status({"last_ok": "2026-10-20", "fresh_h": 11 * 24}, NOW), "late")


class TestCollect(unittest.TestCase):
    def test_worst_and_broken_check(self):
        out = collect([Fake("a", [{"name": "Quotes", "last_ok": ago(0.1)}]), Fake("b", boom=True), object()], now=NOW)
        self.assertEqual([r["name"] for r in out["sources"]], ["Quotes", "b"])     # components without sources() skipped
        self.assertEqual(out["sources"][0]["age_h"], 0.1)
        self.assertIn("cache unreadable", out["sources"][1]["error"])
        self.assertEqual(out["worst"], "down")

    def test_hosted_file(self):
        with tempfile.TemporaryDirectory() as d:
            got = HealthComponent([Fake("a", [{"name": "Quotes", "last_ok": datetime.now(timezone.utc).isoformat()}])]).build_static(Path(d), Path(d))
            self.assertEqual(got, {"sources": "ok"})
            self.assertEqual(json.loads((Path(d) / "sources.json").read_text())["sources"][0]["status"], "ok")

    def test_every_component_reports(self):
        from gexpro.components import default_components
        comps = default_components([])
        self.assertIn("/api/sources", comps[-1].routes())
        for c in comps[:-1]:
            self.assertTrue(callable(getattr(c, "sources", None)), f"{c.name} has no sources()")


if __name__ == "__main__":
    unittest.main()
