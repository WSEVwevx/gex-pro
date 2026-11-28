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
        # a weekly report fetched just now is late when the report itself is old, and on time otherwise
        self.assertEqual(status({"last_ok": ago(1), "data_asof": "2026-10-20", "fresh_h": 11 * 24}, NOW), "late")
        self.assertEqual(status({"last_ok": ago(1), "data_asof": "2026-11-03", "fresh_h": 11 * 24}, NOW), "ok")

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


class Peek:
    def __init__(self, out):
        self.out = out

    def peek(self):
        return self.out

    def get(self):
        raise AssertionError("the health check must not fetch")


class TestFeedRows(unittest.TestCase):
    def rows(self, **kw):
        from feeds.component import FeedsComponent
        parts = dict(calendar=Peek(None), posts=Peek(None), quotes=Peek(None), screener=Peek(None), positioning=Peek(None))
        parts.update({k: Peek(v) for k, v in kw.items()})
        return {r["name"]: r for r in FeedsComponent(**parts).sources()}

    def test_never_fetches_and_waits_before_first_load(self):
        r = self.rows()
        self.assertEqual(status(r["Economic calendar"], NOW), "waiting")
        self.assertEqual(status(r["Big trader positioning"], NOW), "waiting")

    def test_quotes_that_never_arrived_are_down(self):
        r = self.rows(quotes={"fetched": ago(0), "ok_at": None, "quotes": []})
        self.assertEqual(status(r["Ticker quotes"], NOW), "down")

    def test_oldest_positioning_report_counts(self):
        r = self.rows(positioning={"markets": {"ES": {"asof": "2026-10-27"}, "NQ": {"asof": "2026-10-13"}}, "fetched_at": ago(1)})
        self.assertEqual(status(r["Big trader positioning"], NOW), "late")

    def test_positioning_worked_is_the_fetch_time_not_the_report_date(self):
        r = self.rows(positioning={"markets": {"ES": {"asof": "2026-11-03"}, "NQ": {"asof": "2026-11-03"}}, "fetched_at": ago(2)})
        row = r["Big trader positioning"]
        self.assertEqual((row["last_ok"], row["data_asof"], status(row, NOW)), (ago(2), "2026-11-03", "ok"))
        self.assertTrue(row["detail"].endswith("latest positions Nov 3"))
        old = self.rows(positioning={"markets": {"ES": {"asof": "2026-11-03"}, "NQ": {"asof": "2026-11-03"}}})
        self.assertEqual(status(old["Big trader positioning"], NOW), "waiting")       # a copy saved before fetch times

    def test_bundled_weights_are_a_backup_not_late(self):
        scr = {"fetched": ago(0), "stocks": [{"stale": False}], "weights_asof": "2026-10-25", "weights_source": "slickcharts.com (bundled fallback)"}
        self.assertEqual(status(self.rows(screener=scr)["Index weights"], NOW), "partial")


class TestGexRow(unittest.TestCase):
    def test_failing_chain_stays_red_after_stale(self):
        import time
        from types import SimpleNamespace
        from gexsys.component import GexComponent
        w = SimpleNamespace(cfg=SimpleNamespace(market="NQ", source="NDX"), label="OCC", last_success=time.time() - 3600,
                            failures=4, last_error="URLError: timed out", health=lambda: {"status": "stale", "calc_status": "OK"}, published=None)
        g = GexComponent([])
        g.workers = {"NQ-OCC": w}
        row = g.sources()[0]
        self.assertEqual(row["error"], "URLError: timed out")
        self.assertEqual(status(row, datetime.now(timezone.utc)), "failing")


class TestBasisRow(unittest.TestCase):
    def test_carry_fallback_shows_as_partial(self):
        # Yahoo's minute bars failing used to switch the website to the carry model (~20 NQ points off) silently
        import time
        from types import SimpleNamespace
        from gexsys.component import GexComponent
        g = GexComponent([])
        for mode, want in (("measured NQ=F / ^NDX basis (15-minute median to 11-17 16:00 ET)", "ok"),
                           ("carry-model fair value for NQZ6 (r 4.00%, dividend 0.70%) - measured basis unavailable", "partial")):
            w = SimpleNamespace(cfg=SimpleNamespace(market="NQ", source="NDX"), label="OCC", last_success=time.time(), failures=0,
                                last_error=None, health=lambda: {"status": "ok", "calc_status": "OK"}, published=None,
                                result={"mapped": {"mapping": {"futures_ref_mode": mode}}})
            g.workers = {"NQ-OCC": w}
            row = next(r for r in g.sources() if r["name"] == "NQ futures basis")
            self.assertEqual(status(row, datetime.now(timezone.utc)), want)
            self.assertEqual(row["detail"], mode)


class TestPasteRow(unittest.TestCase):
    def test_old_paste_is_late_while_the_futures_trade(self):
        import time
        from types import SimpleNamespace
        from unittest import mock
        from gexsys.component import GexComponent
        old = (datetime.now(timezone.utc) - timedelta(hours=44)).isoformat()      # 2026-11-08: Friday's paste on Sunday night
        w = SimpleNamespace(cfg=SimpleNamespace(market="NQ", source="NDX"), label="OCC", last_success=time.time(), failures=0,
                            last_error=None, health=lambda: {"status": "ok", "calc_status": "OK"},
                            published={"slot_et": "2026-11-06 23:00", "published_at": old})
        g = GexComponent([])
        g.workers = {"NQ-OCC": w}
        for state, want in (("ETH", "late"), ("CLOSED", "ok")):
            with mock.patch("gexsys.marketcal.session_state", return_value=state):
                row = next(r for r in g.sources() if r["name"] == "NQ TradingView paste")
            self.assertEqual(status(row, datetime.now(timezone.utc)), want, state)


    def test_the_paste_on_hold_while_the_levels_are_an_estimate_is_not_working(self):
        """20 Nov 2026: the site still offered Thursday's 16:30 paste while estimates were not pasted, and the row said
        "Working"."""
        import time
        from types import SimpleNamespace
        from unittest import mock
        from gexsys.component import GexComponent
        w = SimpleNamespace(cfg=SimpleNamespace(market="NQ", source="NDX"), label="OCC", last_success=time.time(), failures=0,
                            last_error=None, health=lambda: {"status": "ok", "calc_status": "OK"},
                            result={"summary": {"backup": "OCC open interest + VIX-family vols: an estimate"}},
                            published={"slot_et": "2026-11-19 16:30", "published_at": (datetime.now(timezone.utc) - timedelta(hours=29)).isoformat()})
        g = GexComponent([])
        g.workers = {"NQ-OCC": w}
        for state in ("CLOSED", "ETH"):                  # never "late" for a paste that is on hold by design
            with mock.patch("gexsys.marketcal.session_state", return_value=state):
                rows = {r["name"]: r for r in g.sources()}
            paste = rows["NQ TradingView paste"]
            self.assertEqual(status(paste, datetime.now(timezone.utc)), "partial", state)
        self.assertEqual(paste["note"], "on hold: estimates are not pasted; the paste on the site is still the 2026-11-19 16:30 ET one")
        self.assertIn("Heatmap", rows["NQ options chain"]["pages"])                   # every snapshot is saved, so drawn there
        self.assertIn("Heatmap", rows["NQ options chain"]["pages"])


if __name__ == "__main__":
    unittest.main()
