"""The OCC backup chain (gexsys/providers/occ.py): used only while Cboe refuses, labelled an estimate, never pasted
to TradingView and never graded."""
import io
import json
import re
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from gexpro.health import status
from gexsys import config as cfgmod
from gexsys.component import GexComponent
from gexsys.export import parse_payload
from gexsys.pipeline import backup_trim, run_once
from gexsys.providers.base import AuthError, ProviderUnavailable
from gexsys.providers.occ import FallbackProvider, OccProvider, curve_iv, last_close, parse_series, vol_curve

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 19, 22, 0, tzinfo=timezone.utc)          # Thursday evening, after the close


def occ_line(prod, y, m, d, strike, call, put):
    i, dec = int(strike), round((strike - int(strike)) * 1000)
    return "\t".join([prod, "", str(y), f"{m:02d}", f"{d:02d}", str(i), f"{dec:03d}", "C P", str(call), str(put), "25000"])


def vol_csv(close, day="11/19/2026"):
    return f"DATE,OPEN,HIGH,LOW,CLOSE\n11/18/2026,1,1,1,{close + 3}\n{day},1,1,1,{close}\n"


def yahoo(price, prev):
    ts = int(NOW.timestamp())
    return json.dumps({"chart": {"result": [{"meta": {"regularMarketPrice": price, "chartPreviousClose": prev,
                                                      "regularMarketTime": ts}}]}})


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(pages):
    def op(req, timeout=None):
        url = req.full_url
        for key, body in pages.items():
            if key in url:
                return Resp(body.encode())
        raise urllib.error.HTTPError(url, 404, "not found", {}, None)
    return op


def ndx_pages():
    ndx = "\n".join(["Product Symbol\tx\tYear", occ_line("NDX", 2026, 11, 20, 26000, 900, 1200),
                     occ_line("NDXP", 2026, 11, 20, 26500, 1500, 300), occ_line("NDX", 2026, 12, 18, 25000, 400, 2500),
                     occ_line("NDX", 2026, 12, 18, 27000, 2200, 100), occ_line("XND", 2026, 11, 20, 260, 9999, 9999)])
    qqq = "\n".join([occ_line("QQQ", 2026, 11, 20, 630, 50000, 40000), occ_line("QQQ", 2026, 12, 18, 650, 30000, 10000)])
    return {"symbol=NDX": ndx, "symbol=QQQ": qqq, "VIX1D_": vol_csv(14), "VIX9D_": vol_csv(16), "VIX_History": vol_csv(18),
            "VIX3M_": vol_csv(20), "VXN_": vol_csv(23), "%5ENDX": yahoo(26200, 26100), "chart/QQQ": yahoo(637, 635)}


class TestParsing(unittest.TestCase):
    def test_parse_series_reads_strike_decimals_and_skips_other_lines(self):
        text = "\n".join(["Product Symbol\tYear", occ_line("SPXW", 2026, 11, 20, 7212.5, 10, 0), "garbage\tline", ""])
        self.assertEqual(parse_series(text), [("SPXW", date(2026, 11, 20), 7212.5, 10.0, 0.0)])

    def test_last_close_takes_the_newest_date_as_a_decimal(self):
        text = "DATE,OPEN,HIGH,LOW,CLOSE\n11/19/2026,1,1,1,18.5\n11/17/2026,1,1,1,30\nbad,row\n11/18/2026,1,1,1,0\n"
        self.assertEqual(last_close(text), (date(2026, 11, 19), 0.185))
        self.assertIsNone(last_close("DATE,OPEN,HIGH,LOW,CLOSE\n"))

    def test_vol_curve_uses_only_points_dated_like_the_newest(self):
        d1, d0 = date(2026, 11, 19), date(2026, 11, 18)
        pts, newest = vol_curve({"VIX1D": (d0, 0.12), "VIX9D": (d1, 0.16), "VIX": (d1, 0.18)})
        self.assertEqual((pts, newest), ([(9.0, 0.16), (30.0, 0.18)], d1))
        with self.assertRaises(ProviderUnavailable):
            vol_curve({})


class TestCurve(unittest.TestCase):
    PTS = [(1.0, 0.14), (9.0, 0.16), (30.0, 0.18), (93.0, 0.20)]

    def test_total_variance_is_linear_between_points(self):
        # recomputed from the definition: w(d) = iv(d)^2 * d is a straight line between neighbouring points
        for (d0, v0), (d1, v1) in zip(self.PTS, self.PTS[1:]):
            for frac in (0.25, 0.5, 0.9):
                d = d0 + frac * (d1 - d0)
                w = curve_iv(self.PTS, d) ** 2 * d
                self.assertAlmostEqual(w, v0 * v0 * d0 + frac * (v1 * v1 * d1 - v0 * v0 * d0), places=12)

    def test_flat_beyond_the_ends_and_exact_at_the_points(self):
        self.assertEqual(curve_iv(self.PTS, 0.1), 0.14)
        self.assertEqual(curve_iv(self.PTS, 400), 0.20)
        for d, v in self.PTS:
            self.assertAlmostEqual(curve_iv(self.PTS, d), v, places=12)


class Fake:
    name, label = "cboe", "CBOE"

    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def fetch_snapshot(self, *a, **k):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class TestFallback(unittest.TestCase):
    def test_refused_uses_the_backup_and_says_so(self):
        backup = Fake(result="occ-snap")
        backup.label = "OCC"
        fb = FallbackProvider(Fake(error=AuthError("HTTP 403")), backup)
        self.assertEqual(fb.fetch_snapshot("NDX"), "occ-snap")
        self.assertEqual((fb.last_label, fb.refusal, fb.backup_error), ("OCC", "HTTP 403", None))
        self.assertEqual((fb.name, fb.label), ("cboe", "CBOE"))           # the worker key and history folder stay

    def test_cboe_working_never_touches_the_backup(self):
        backup = Fake(result="occ-snap")
        fb = FallbackProvider(Fake(result="cboe-snap"), backup)
        fb.refusal, fb.last_label = "old", "OCC"
        self.assertEqual(fb.fetch_snapshot("NDX"), "cboe-snap")
        self.assertEqual((backup.calls, fb.last_label, fb.refusal), (0, None, None))

    def test_both_failing_is_one_clear_error(self):
        backup = Fake(error=ProviderUnavailable("OCC down"))
        fb = FallbackProvider(Fake(error=AuthError("HTTP 403")), backup)
        fb.last_label = "OCC"                                             # it worked before
        with self.assertRaises(ProviderUnavailable) as cm:
            fb.fetch_snapshot("NDX")
        self.assertIn("Cboe refused", str(cm.exception))
        self.assertIn("OCC down", str(cm.exception))
        self.assertEqual((fb.backup_error, fb.last_label), ("OCC down", None))

    def test_a_refusal_is_not_asked_again_for_15_minutes(self):
        from unittest import mock
        primary, backup = Fake(error=AuthError("HTTP 403")), Fake(result="occ-snap")
        fb = FallbackProvider(primary, backup)
        with mock.patch("gexsys.providers.occ.time.time", return_value=1000.0):
            fb.fetch_snapshot("NDX")
        with mock.patch("gexsys.providers.occ.time.time", return_value=1000.0 + 899):
            self.assertEqual(fb.fetch_snapshot("NDX"), "occ-snap")
        self.assertEqual((primary.calls, backup.calls), (1, 2))
        primary.error, primary.result = None, "cboe-snap"
        with mock.patch("gexsys.providers.occ.time.time", return_value=1000.0 + 900):
            self.assertEqual(fb.fetch_snapshot("NDX"), "cboe-snap")
        self.assertEqual((primary.calls, fb.refusal, fb.primary_ok), (2, None, 1900.0))

    def test_other_errors_do_not_switch_to_the_backup(self):
        backup = Fake(result="occ-snap")
        fb = FallbackProvider(Fake(error=ProviderUnavailable("timed out")), backup)
        with self.assertRaises(ProviderUnavailable):
            fb.fetch_snapshot("NDX")
        self.assertEqual(backup.calls, 0)


class TestOccProvider(unittest.TestCase):
    def snap(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = OccProvider(cache_dir=tmp, opener=opener_for(ndx_pages()), clock=NOW.timestamp)
            return p.fetch_snapshot("NDX")

    def test_snapshot_is_labelled_and_uses_the_scaled_curve(self):
        s = self.snap()
        self.assertEqual((s.source, s.spot, s.prev_close), ("occ+vix", 26200.0, 26100.0))
        self.assertTrue(s.warnings[0].startswith("BACKUP ESTIMATE"))
        roots = {c.root for c in s.contracts}
        self.assertNotIn("XND", roots)                                   # only the standard roots
        self.assertTrue({"NDX", "NDXP"} <= roots)
        pts = [(1.0, 0.14), (9.0, 0.16), (30.0, 0.18), (93.0, 0.20)]
        scale = 0.23 / curve_iv(pts, 30)                                 # VXN / the SPX curve at 30 days
        dec = next(c for c in s.contracts if c.root == "NDX" and c.expiration.month == 12)
        days = (dec.expiration - NOW).total_seconds() / 86400
        self.assertAlmostEqual(dec.iv, scale * curve_iv(pts, days), places=12)

    def test_a_missing_curve_point_is_named(self):
        pages = dict(ndx_pages(), VIX_History=vol_csv(18, day="11/18/2026"))
        s = OccProvider(opener=opener_for(pages), clock=NOW.timestamp).fetch_snapshot("NDX")
        self.assertIn("no Nov 19 close for VIX;", " ".join(s.warnings))
        self.assertNotIn("no Nov 19 close", " ".join(self.snap().warnings))

    def test_a_refusal_from_occ_is_an_auth_error(self):
        def refuse(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 403, "forbidden", {}, None)
        with self.assertRaises(AuthError):
            OccProvider(opener=refuse, clock=NOW.timestamp).fetch_snapshot("NDX")

    def test_pipeline_trims_and_the_paste_still_parses(self):
        snap = self.snap()
        fb = FallbackProvider(Fake(error=AuthError("HTTP 403")), Fake(result=snap))
        fb.backup.label = "OCC"
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cfgmod.load(ROOT / "configs/free_nq_cboe.json")
            cfg.storage = {"root": tmp}
            r = run_once(cfg, fb)
        s = r["summary"]
        self.assertIn("estimate", s["backup"])
        self.assertIsNone(s["max_negative"])
        self.assertEqual(s["provider"], "OCC")
        p = parse_payload(r["pine"])
        self.assertTrue(p["complete"])
        self.assertEqual(p["prov"], "OCC")


class TestTrim(unittest.TestCase):
    def test_keeps_the_first_ranks_and_drops_the_rest(self):
        lv = lambda x: {"price": x}
        s = {"max_negative": lv(1), "ranked": {"call": [lv(1), lv(2)], "put": [lv(3), lv(4)]},
             "extras": {"nearest": {"zero_gamma": lv(5), "call_wall": lv(6), "put_wall": lv(7),
                                    "ranked": {"call": [lv(8), lv(9)], "put": [lv(10)], "abs": [lv(11)]},
                                    "ranked_etf": {"call": [], "put": [lv(12), lv(13)], "abs": [lv(14)]}}}}
        backup_trim(s)
        n = s["extras"]["nearest"]
        self.assertIsNone(s["max_negative"])
        self.assertEqual(s["ranked"], {"call": [lv(1)], "put": [lv(3)]})
        self.assertEqual((n["zero_gamma"], n["call_wall"], n["put_wall"]), (None, None, None))
        self.assertEqual(n["ranked"], {"call": [lv(8)], "put": [lv(10)], "abs": []})
        self.assertEqual(n["ranked_etf"], {"call": [], "put": [lv(12)], "abs": []})
        self.assertIn("backup", s)


def worker(fb, ok=True):
    import time
    return SimpleNamespace(cfg=SimpleNamespace(market="NQ", source="NDX"), label="CBOE", provider=fb,
                           last_success=time.time() if ok else None, failures=0, last_error=None,
                           health=lambda: {"status": "ok", "calc_status": "OK"}, published=None)


class TestHealthRows(unittest.TestCase):
    def rows(self, fb):
        g = GexComponent([])
        g.workers = {"NQ-CBOE": worker(fb)}
        now = datetime.now(timezone.utc)
        return {r["name"]: status(r, now) for r in g.sources()}

    def test_in_use_cboe_down_backup_partial(self):
        import time
        fb = FallbackProvider(Fake(), Fake())
        fb.refusal, fb.last_label, fb.backup_ok = "HTTP 403", "OCC", time.time()
        got = self.rows(fb)
        self.assertEqual(got["NQ options chain"], "down")
        self.assertEqual(got["NQ backup chain (estimate)"], "partial")
        fb.primary_ok = time.time() - 7200                                # Cboe worked before it refused
        self.assertEqual(self.rows(fb)["NQ options chain"], "failing")

    def test_a_fresh_process_reads_cboes_last_success_from_its_history(self):
        # each hosted build is a new process: without this the Cboe row said "no good copy yet" beside 16:14's levels
        import time
        from gexsys.storage import SnapshotStore
        fb = FallbackProvider(Fake(), Fake())
        fb.refusal, fb.last_label, fb.backup_ok = "HTTP 403", "OCC", time.time()
        with tempfile.TemporaryDirectory() as tmp:
            w = worker(fb)
            w.store, w.key = SnapshotStore(tmp), "NQ-CBOE"
            w.store.save("NQ-CBOE", {"asof": "2026-11-19T21:14:59+00:00", "status": "OK"})
            g = GexComponent([])
            g.workers = {"NQ-CBOE": w}
            row = next(r for r in g.sources() if r["name"] == "NQ options chain")
        self.assertEqual(row["last_ok"], "2026-11-19T21:14:59+00:00")
        self.assertEqual(status(row, datetime.now(timezone.utc)), "failing")

    def test_standby_is_waiting_and_cboe_ok(self):
        got = self.rows(FallbackProvider(Fake(), Fake()))
        self.assertEqual(got["NQ options chain"], "ok")
        self.assertEqual(got["NQ backup chain (estimate)"], "waiting")

    def test_workers_without_a_provider_still_report(self):
        w = worker(None)
        del w.provider
        g = GexComponent([])
        g.workers = {"NQ-CBOE": w}
        self.assertNotIn("NQ backup chain (estimate)", {r["name"] for r in g.sources()})


class TestNeverPastedNorGraded(unittest.TestCase):
    def test_a_backup_result_is_not_published(self):
        from gexsys.service import MarketWorker
        w = MarketWorker.__new__(MarketWorker)
        w.cfg = cfgmod.load(ROOT / "configs/free_nq_cboe.json")
        w.published = w.published_slot = None
        w.result = {"summary": {"backup": "estimate"}, "mapped": None, "pine": "GEX1;END"}
        w._save_published = lambda: self.fail("saved a backup paste")
        w._maybe_publish(datetime(2026, 11, 19, 15, 1, tzinfo=timezone.utc))
        self.assertIsNone(w.published)

    def test_the_open_plan_skips_backup_snapshots(self):
        from gexpro.context import pre_open
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "NQ-CBOE" / "20261120"
            day.mkdir(parents=True)
            s = {"asof": "2026-11-20T14:00:00+00:00", "status": "OK", "backup": "estimate",
                 "extras": {"expected_move": {"daily_points": 300}}}
            (day / "140000_000000.json").write_text(json.dumps(s), encoding="utf-8")
            w = SimpleNamespace(cfg=SimpleNamespace(market="NQ"), store=SimpleNamespace(root=Path(tmp)), key="NQ-CBOE")
            self.assertEqual(pre_open(SimpleNamespace(workers={"NQ-CBOE": w}), date(2026, 11, 20)), {"NQ": None})

    def test_the_site_says_it_is_an_estimate(self):
        js = (ROOT / "dashboard/assets/app.js").read_text(encoding="utf-8")
        self.assertTrue(re.search(r"s\.backup \?.*levels are an estimate.*TradingView paste keeps the last Cboe levels", js))


if __name__ == "__main__":
    unittest.main()
