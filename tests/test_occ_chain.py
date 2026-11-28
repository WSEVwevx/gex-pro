"""The options chain (gexsys/providers/occ.py): OCC open interest + one implied vol per expiry from the VIX-family
daily closes (Yahoo) + Yahoo prices. The vol date is the last completed session by marketcal, so holidays, early
closes and DST weeks never break a market; the levels are an estimate, not pasted to TradingView and not graded."""
import io
import json
import re
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from gexpro.health import status
from gexsys import config as cfgmod, marketcal
from gexsys.component import GexComponent
from gexsys.export import parse_payload
from gexsys.pipeline import backup_trim, run_once
from gexsys.providers.base import AuthError, ProviderUnavailable
from gexsys.providers.occ import (OccProvider, curve_iv, daily_closes, parse_series, pick_close, vol_curve,
                                  vol_date)

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 19, 22, 0, tzinfo=timezone.utc)          # Thursday 17:00 ET, after the close
UTC = timezone.utc


def occ_line(prod, y, m, d, strike, call, put):
    i, dec = int(strike), round((strike - int(strike)) * 1000)
    return "\t".join([prod, "", str(y), f"{m:02d}", f"{d:02d}", str(i), f"{dec:03d}", "C P", str(call), str(put), "25000"])


def chart(closes: dict, tz="America/New_York"):
    """A Yahoo daily chart: {date: close (percent) or None}, each bar stamped at its 09:30 ET open."""
    days = sorted(closes)
    stamps = [int(datetime.combine(d, marketcal.RTH_OPEN, marketcal.NY).timestamp()) for d in days]
    return json.dumps({"chart": {"result": [{"meta": {"exchangeTimezoneName": tz}, "timestamp": stamps,
                                             "indicators": {"quote": [{"close": [closes[d] for d in days]}]}}]}})


def vol(close, day=date(2026, 11, 19)):
    return chart({day - timedelta(days=1): close + 3, day: close})


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


def ndx_pages(**vols):
    ndx = "\n".join(["Series Search Results for NDX", "Product Symbol\tx\tYear", occ_line("NDX", 2026, 11, 20, 26000, 900, 1200),
                     occ_line("NDXP", 2026, 11, 20, 26500, 1500, 300), occ_line("NDX", 2026, 12, 18, 25000, 400, 2500),
                     occ_line("NDX", 2026, 12, 18, 27000, 2200, 100), occ_line("XND", 2026, 11, 20, 260, 9999, 9999)]) + "\n"
    qqq = "\n".join(["Series Search Results for QQQ", occ_line("QQQ", 2026, 11, 20, 630, 50000, 40000),
                     occ_line("QQQ", 2026, 12, 18, 650, 30000, 10000)]) + "\n"
    v = {"VIX1D": vol(14), "VIX9D": vol(16), "VIX": vol(18), "VIX3M": vol(20), "VXN": vol(23)} | vols
    return {"symbol=NDX": ndx, "symbol=QQQ": qqq, "%5ENDX": yahoo(26200, 26100), "chart/QQQ": yahoo(637, 635),
            **{f"%5E{n}?": body for n, body in v.items()}}


def et(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=marketcal.NY)


class TestParsing(unittest.TestCase):
    def test_parse_series_reads_strike_decimals_and_skips_other_lines(self):
        rows = parse_series("header\n" + occ_line("SPXW", 2026, 11, 20, 6750.5, 10, 20) + "\nfooter\t1\n")
        self.assertEqual(rows, [("SPXW", date(2026, 11, 20), 6750.5, 10.0, 20.0)])

    def test_daily_closes_are_dated_in_the_exchange_zone_as_decimals(self):
        # ^VIX is dated in Chicago: a bar stamped 02:00 CT (08:00 UTC) belongs to that Chicago day
        raw = json.dumps({"chart": {"result": [{"meta": {"exchangeTimezoneName": "America/Chicago"},
                                                "timestamp": [1795593600, 1795680000],      # 25 and 26 Nov, 08:00 UTC
                                                "indicators": {"quote": [{"close": [28.290000915527344, None]}]}}]}})
        self.assertEqual(daily_closes(raw), {date(2026, 11, 25): 0.2829})     # float32 noise undone; no close, no row
        self.assertEqual(daily_closes("<html>refused</html>"), {})
        self.assertEqual(daily_closes(json.dumps({"chart": {"result": []}})), {})

    def test_vol_curve_keeps_every_series_with_a_close(self):
        d = date(2026, 11, 19)
        pts = vol_curve({"VIX1D": (d, 0.14), "VIX": (d - timedelta(days=1), 0.18), "VXN": (d, 0.23)})
        self.assertEqual(pts, [(1.0, 0.14), (30.0, 0.18)])                  # VXN is not a curve point
        with self.assertRaises(ProviderUnavailable):
            vol_curve({"VXN": (d, 0.23)})


class TestVolDate(unittest.TestCase):
    """The session whose closes are used: the last completed one by marketcal, 30 minutes after its bell."""

    def test_thanksgiving_and_its_early_close(self):
        self.assertEqual(vol_date(et(2026, 11, 26, 12, 0)), date(2026, 11, 25))      # holiday: the day before
        self.assertEqual(vol_date(et(2026, 11, 27, 12, 0)), date(2026, 11, 25))      # Friday before its 13:00 close
        self.assertEqual(vol_date(et(2026, 11, 27, 13, 29)), date(2026, 11, 25))     # the VIX family still settling
        self.assertEqual(vol_date(et(2026, 11, 27, 13, 30)), date(2026, 11, 27))     # early close + 30 min

    def test_good_friday(self):
        self.assertEqual(vol_date(et(2027, 3, 26, 12, 0)), date(2027, 3, 25))        # Good Friday 2027: closed
        self.assertEqual(vol_date(et(2027, 3, 29, 9, 0)), date(2027, 3, 25))         # Monday pre-open

    def test_both_dst_weeks(self):
        # 16:30 ET is 21:30 UTC after the November change and 20:30 UTC after the March one
        self.assertEqual(vol_date(datetime(2026, 11, 2, 21, 29, tzinfo=UTC)), date(2026, 10, 30))
        self.assertEqual(vol_date(datetime(2026, 11, 2, 21, 30, tzinfo=UTC)), date(2026, 11, 2))
        self.assertEqual(vol_date(datetime(2027, 3, 15, 20, 29, tzinfo=UTC)), date(2027, 3, 12))
        self.assertEqual(vol_date(datetime(2027, 3, 15, 20, 30, tzinfo=UTC)), date(2027, 3, 15))

    def test_pick_close_takes_that_day_or_the_session_before_and_nothing_older(self):
        h = {date(2026, 11, 24): 0.30, date(2026, 11, 25): 0.31, date(2026, 11, 26): 0.99}   # 26 Nov: a holiday row
        self.assertEqual(pick_close(h, date(2026, 11, 27)), (date(2026, 11, 25), 0.31))     # the holiday row is skipped
        self.assertEqual(pick_close({date(2026, 11, 25): 0.31}, date(2026, 11, 27)), (date(2026, 11, 25), 0.31))
        self.assertEqual(pick_close(h, date(2026, 11, 25)), (date(2026, 11, 25), 0.31))
        self.assertIsNone(pick_close({date(2026, 11, 20): 0.3}, date(2026, 11, 25)))     # a week old: not used


class TestCurve(unittest.TestCase):
    PTS = [(1.0, 0.14), (9.0, 0.16), (30.0, 0.18), (93.0, 0.20)]

    def test_total_variance_is_linear_between_points(self):
        w0, w1 = 0.16 ** 2 * 9, 0.18 ** 2 * 30
        days = 20.0
        self.assertAlmostEqual(curve_iv(self.PTS, days) ** 2 * days, w0 + (w1 - w0) * (days - 9) / 21, places=12)

    def test_flat_beyond_the_ends_and_exact_at_the_points(self):
        self.assertEqual(curve_iv(self.PTS, 0.3), 0.14)
        self.assertEqual(curve_iv(self.PTS, 400), 0.20)
        for d, v in self.PTS:
            self.assertAlmostEqual(curve_iv(self.PTS, d), v, places=12)


class TestOccProvider(unittest.TestCase):
    def snap(self, pages=None, now=NOW):
        with tempfile.TemporaryDirectory() as tmp:
            p = OccProvider(cache_dir=tmp, opener=opener_for(pages or ndx_pages()), clock=now.timestamp)
            return p.fetch_snapshot("NDX"), p

    def test_snapshot_is_labelled_and_uses_the_scaled_curve(self):
        s, p = self.snap()
        self.assertEqual((s.source, s.spot, s.prev_close), ("occ+vix", 26200.0, 26100.0))
        self.assertTrue(s.warnings[0].startswith("estimate: OCC open interest"))
        self.assertIn("Nov 19 VIX-family closes scaled by VXN", s.warnings[0])
        self.assertEqual(p.vol_date, date(2026, 11, 19))
        roots = {c.root for c in s.contracts}
        self.assertNotIn("XND", roots)                                   # only the standard roots
        self.assertTrue({"NDX", "NDXP"} <= roots)
        scale = 0.23 / curve_iv(TestCurve.PTS, 30)                       # VXN / the SPX curve at 30 days
        dec = next(c for c in s.contracts if c.root == "NDX" and c.expiration.month == 12)
        days = (dec.expiration - NOW).total_seconds() / 86400
        self.assertAlmostEqual(dec.iv, scale * curve_iv(TestCurve.PTS, days), places=12)
        self.assertEqual([d for d, _ in s.vol_points], [1.0, 9.0, 30.0, 93.0])       # the expected move reads this curve itself
        self.assertAlmostEqual(curve_iv(s.vol_points, days), dec.iv, places=12)      # same curve as the contracts' IVs

    def test_one_series_a_day_late_uses_the_session_before_and_says_so(self):
        s, _ = self.snap(ndx_pages(VIX=chart({date(2026, 11, 18): 21})))
        self.assertIn("no Nov 19 close yet for VIX (Nov 18): the session before is used", " ".join(s.warnings))
        self.assertNotIn("close yet", " ".join(self.snap()[0].warnings))

    def test_vxn_is_scaled_against_vix_of_its_own_session(self):
        # verifier, 2026-11-28: a Nov 25 VXN over a Nov 27 VIX lifted every NDX vol by 19%
        s, _ = self.snap(ndx_pages(VXN=chart({date(2026, 11, 18): 25})))                # VXN a day late; VIX has Nov 18 (21)
        self.assertAlmostEqual(s.vol_points[2][1], 0.18 * 0.25 / 0.21, places=12)
        with self.assertRaisesRegex(ProviderUnavailable, "no VXN and VIX close from one session"):
            self.snap(ndx_pages(VXN=chart({date(2026, 11, 18): 25}), VIX=chart({date(2026, 11, 19): 18})))
        # VIX itself missing, every other close from VXN's session: the curve at 30 days stands in
        s, _ = self.snap(ndx_pages(VIX=chart({date(2026, 11, 10): 21})))
        pts = [(1.0, 0.14), (9.0, 0.16), (93.0, 0.20)]
        self.assertAlmostEqual(s.vol_points[0][1], 0.14 * 0.23 / curve_iv(pts, 30), places=12)

    def test_a_missing_curve_point_is_named(self):
        s, _ = self.snap(ndx_pages(VIX=chart({date(2026, 11, 10): 21})))           # too old: missing
        self.assertIn("no Nov 19 close for VIX; the vol curve interpolates across it", " ".join(s.warnings))

    def test_every_series_missing_is_unavailable(self):
        old = chart({date(2026, 11, 10): 20})
        with self.assertRaisesRegex(ProviderUnavailable, "no VIX-family close for Nov 19"):
            self.snap(ndx_pages(VIX1D=old, VIX9D=old, VIX=old, VIX3M=old))
        with self.assertRaisesRegex(ProviderUnavailable, "no VXN close for Nov 19"):
            self.snap(ndx_pages(VXN=old))

    def test_thanksgiving_replay_reads_the_25th_and_ignores_the_holiday_row(self):
        # as Yahoo answered on 27 Nov: ^VIX carries a 26 Nov (holiday) row; ^VXN has no final 27 Nov close yet
        days = {date(2026, 11, 24): 26.4, date(2026, 11, 25): 28.3, date(2026, 11, 27): 23.8}
        vols = {n: chart(days) for n in ("VIX1D", "VIX9D", "VIX3M")}
        vols["VIX"] = chart(days | {date(2026, 11, 26): 99.0}, tz="America/Chicago")
        vols["VXN"] = chart({date(2026, 11, 24): 36.4, date(2026, 11, 25): 38.5, date(2026, 11, 27): None})
        for now, vd in ((et(2026, 11, 26, 12, 0), date(2026, 11, 25)), (et(2026, 11, 27, 18, 0), date(2026, 11, 27))):
            s, p = self.snap(ndx_pages(**vols), now=now)
            self.assertEqual(p.vol_date, vd)
            pts = dict(s.vol_points)
            # NDX / S&P vol from one session (25 Nov: VXN has no 27 Nov close), applied to that day's curve
            self.assertAlmostEqual(pts[30.0], 0.385 if vd.day == 25 else 0.238 * 0.385 / 0.283, places=12)
            self.assertAlmostEqual(pts[1.0], pts[30.0], places=12)         # VIX = VIX1D that day: never the 99 holiday row
            text = " ".join(s.warnings)
            self.assertIn(f"{vd:%b %d} VIX-family closes", text)
            if vd.day == 27:
                self.assertIn("no Nov 27 close yet for VXN (Nov 25): the session before is used", text)
                self.assertIn("the NDX scale is VXN / VIX of Nov 25, the last session with both", text)
            else:
                self.assertNotIn("close yet", text)

    def test_an_etf_with_a_wrong_price_is_not_used_and_says_so(self):
        s, _ = self.snap(dict(ndx_pages(), **{"chart/QQQ": yahoo(100, 99)}))
        self.assertFalse(any(c.root == "QQQ" for c in s.contracts))
        self.assertIn("QQQ options not used (price ratio 262.00 outside 38-45)", " ".join(s.warnings))
        self.assertTrue(any(c.root == "QQQ" for c in self.snap()[0].contracts))

    def test_a_cut_off_or_foreign_occ_file_is_refused(self):
        whole = ndx_pages()["symbol=NDX"]
        for bad in (whole[:-40], "<html>busy</html>\n", whole.replace("for NDX", "for SPX")):
            with self.assertRaisesRegex(ProviderUnavailable, "the OCC NDX file is incomplete or not a series list"):
                self.snap(dict(ndx_pages(), **{"symbol=NDX": bad}))
        s, _ = self.snap(dict(ndx_pages(), **{"symbol=QQQ": ndx_pages()["symbol=QQQ"][:-30]}))     # the ETF's: left out, said
        self.assertIn("QQQ options not used (the OCC QQQ file is incomplete", " ".join(s.warnings))

    def test_negative_open_interest_is_flagged_not_dropped(self):
        from gexsys.normalize import normalize
        pages = ndx_pages()
        pages["symbol=NDX"] = pages["symbol=NDX"].replace("\t400\t2500\t", "\t-400\t2500\t")
        s, _ = self.snap(pages)
        self.assertTrue(any(c.open_interest == -400 for c in s.contracts))
        self.assertTrue(any("bad oi" in w for w in normalize(s).warnings))

    def test_a_refusal_from_occ_is_an_auth_error(self):
        def refuse(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 403, "forbidden", {}, None)
        with self.assertRaises(AuthError):
            OccProvider(opener=refuse, clock=NOW.timestamp).fetch_snapshot("NDX")

    def test_the_provider_reads_no_cboe_host(self):
        seen = []

        def op(req, timeout=None):
            seen.append(req.full_url)
            return opener_for(ndx_pages())(req, timeout)
        OccProvider(opener=op, clock=NOW.timestamp).fetch_snapshot("NDX")
        self.assertTrue(seen)
        self.assertEqual({u.split("/")[2] for u in seen}, {"marketdata.theocc.com", "query1.finance.yahoo.com"})

    def test_pipeline_trims_and_the_paste_still_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = OccProvider(cache_dir=None, opener=opener_for(ndx_pages()), clock=NOW.timestamp)
            cfg = cfgmod.load(ROOT / "configs/free_nq.json")
            cfg.storage = {"root": tmp}
            r = run_once(cfg, prov)
        s = r["summary"]
        self.assertIn("estimate", s["backup"])
        self.assertIsNone(s["max_negative"])
        self.assertEqual(s["provider"], "OCC")
        p = parse_payload(r["pine"])
        self.assertTrue(p["complete"])
        self.assertEqual(p["prov"], "OCC")

    def test_the_configs_use_it(self):
        from gexsys.config import make_provider
        for m in ("nq", "es"):
            cfg = cfgmod.load(ROOT / f"configs/free_{m}.json")
            self.assertIsInstance(make_provider(cfg), OccProvider)
        self.assertFalse((ROOT / "gexsys/providers/cboe.py").exists())


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


def worker(est=True, ok=True, published=None):
    import time
    return SimpleNamespace(cfg=SimpleNamespace(market="NQ", source="NDX"), label="OCC", key="NQ-OCC",
                           last_success=time.time() if ok else None, failures=0, last_error=None,
                           result={"summary": {"backup": "estimate"} if est else {}},
                           health=lambda: {"status": "ok", "calc_status": "OK"}, published=published)


class TestHealthRows(unittest.TestCase):
    def rows(self, w):
        g = GexComponent([])
        g.workers = {"NQ-OCC": w}
        now = datetime.now(timezone.utc)
        return {r["name"]: (status(r, now), r) for r in g.sources()}

    def test_the_chain_row_names_its_sources_and_the_paste_is_on_hold(self):
        got = self.rows(worker(published={"slot_et": "2026-11-19 16:30", "published_at": "2026-11-19T21:30:00+00:00"}))
        st, row = got["NQ options chain"]
        self.assertEqual(st, "ok")
        self.assertIn("OCC open interest + VIX-family closes + VXN (Yahoo)", row["provider"])
        self.assertIn("one implied vol per expiry", row["detail"])
        self.assertNotIn("NQ backup chain (estimate)", got)
        st, row = got["NQ TradingView paste"]
        self.assertEqual(st, "partial")
        self.assertIn("on hold: estimates are not pasted; the paste on the site is still the 2026-11-19 16:30 ET one", row["note"])

    def test_a_failing_chain_is_red(self):
        w = worker(ok=False)
        w.failures, w.last_error = 2, "ProviderUnavailable: no VXN close"
        self.assertEqual(self.rows(w)["NQ options chain"][0], "down")

    def test_no_row_mentions_cboe(self):
        self.assertNotIn("cboe", json.dumps([r for _, r in self.rows(worker()).values()]).lower())


class TestRetiredKey(unittest.TestCase):
    def test_the_last_paste_and_result_carry_over_once(self):
        from gexsys.service import MarketWorker
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pub = {"slot_et": "2026-11-19 16:30", "published_at": "2026-11-19T21:30:00+00:00", "payload": "GEX1;END"}
            (root / "published_NQ-CBOE.json").write_text(json.dumps(pub), encoding="utf-8")
            (root / "last_good_NQ-CBOE.json").write_text(json.dumps({"summary": {"status": "OK"}}), encoding="utf-8")
            cfg = cfgmod.load(ROOT / "configs/free_nq.json")
            cfg.storage = {"root": tmp}
            w = MarketWorker(cfg)
            self.assertEqual(w.key, "NQ-OCC")
            self.assertEqual(w.published_slot.strftime("%Y-%m-%d %H:%M"), "2026-11-19 16:30")
            self.assertIn("restored from the previous run", w.result["summary"]["warnings"][-1])
            self.assertTrue((root / "published_NQ-CBOE.json").exists())          # the old files stay
            (root / "published_NQ-OCC.json").write_text(json.dumps(dict(pub, slot_et="2026-11-30 10:00")), encoding="utf-8")
            self.assertEqual(MarketWorker(cfg).published_slot.strftime("%H:%M"), "10:00")   # never over a newer one


class TestNeverPastedNorGraded(unittest.TestCase):
    def test_an_estimate_is_not_published(self):
        from gexsys.service import MarketWorker
        w = MarketWorker.__new__(MarketWorker)
        w.cfg = cfgmod.load(ROOT / "configs/free_nq.json")
        w.published = w.published_slot = None
        w.result = {"summary": {"backup": "estimate"}, "mapped": None, "pine": "GEX1;END"}
        w._save_published = lambda: self.fail("saved an estimate paste")
        w._maybe_publish(datetime(2026, 11, 19, 15, 1, tzinfo=timezone.utc))
        self.assertIsNone(w.published)

    def test_the_open_plan_skips_estimate_snapshots(self):
        from gexpro.context import pre_open
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "NQ-OCC" / "20261120"
            day.mkdir(parents=True)
            s = {"asof": "2026-11-20T14:00:00+00:00", "status": "OK", "backup": "estimate",
                 "extras": {"expected_move": {"daily_points": 300}}}
            (day / "140000_000000.json").write_text(json.dumps(s), encoding="utf-8")
            w = SimpleNamespace(cfg=SimpleNamespace(market="NQ"), store=SimpleNamespace(root=Path(tmp)), key="NQ-OCC")
            self.assertEqual(pre_open(SimpleNamespace(workers={"NQ-OCC": w}), date(2026, 11, 20)), {"NQ": None})

    def test_the_site_names_the_source_quietly(self):
        js = (ROOT / "dashboard/assets/app.js").read_text(encoding="utf-8")
        self.assertTrue(re.search(r"s\.backup \?.*OCC open interest \+ VIX-family vols.*TradingView paste keeps its last published levels", js))
        self.assertIn('Options <b>${bk ? "last close OI" : rt ? "real time" : "15-min delayed"}</b>', js)
        self.assertIn('${s.backup ? "OCC open interest, one vol per expiry" : "15-min delayed"}', js)
        self.assertIn('Next paste <b>${bk ? "on hold"', js)                       # no paste is published from an estimate
        self.assertIn('Math.abs(x) < 0.5 * 10 ** -d ? ""', js)                 # no "-0.00 pts"
        for f in ("dashboard/assets/app.js", "dashboard/assets/library.js", "dashboard/v2/core.js", "dashboard/v2/levels.js"):
            self.assertNotIn("cboe", (ROOT / f).read_text(encoding="utf-8").lower(), f)


if __name__ == "__main__":
    unittest.main()
