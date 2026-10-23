"""Integration tests: config -> pipeline -> storage -> alerts -> HTTP service, plus export round trip."""
import json
import tempfile
import threading
import unittest
import urllib.request
from glob import glob
from http.server import ThreadingHTTPServer
from pathlib import Path

from gexsys import config as cfgmod
from gexsys import engine as eng
from gexsys.alerts import AlertConfig, AlertEngine
from gexsys.export import parse_payload, pine_payload
from gexsys.pipeline import run_once
from gexsys.providers.synthetic import SyntheticProvider, make_chain
from gexsys.replay import sensitivity, stability
from gexsys.service import MarketWorker, make_handler
from gexsys.storage import SnapshotStore

ROOT = Path(__file__).resolve().parent.parent


def synth_cfg(tmp, **extra):
    d = {"market": "NQ", "source": "NDX", "provider": {"name": "synthetic", "live_clock": False},
         "futures_ref": {"mode": "synthetic_basis", "factor": 1.01}, "storage": {"root": tmp}}
    d.update(extra)
    return cfgmod.from_dict(d)


class TestConfig(unittest.TestCase):
    def test_example_configs_validate(self):
        files = glob(str(ROOT / "configs" / "*.json"))
        self.assertGreaterEqual(len(files), 4)
        for f in files:
            cfgmod.load(f)

    def test_rejects_typos_and_invalid_combos(self):
        base = {"market": "NQ", "source": "NDX", "provider": {"name": "synthetic"}}
        for bad in ({**base, "engin": {}}, {**base, "engine": {"max_dt": 3}}, {**base, "source": "SPX"},
                    {**base, "source": "QQQ", "mapping": {"method": "offset"}},
                    {**base, "source": "NQ_FOP", "provider": {"name": "cboe"}},
                    {**base, "provider": {"name": "cboe"}, "futures_ref": {"mode": "synthetic_basis"}},
                    {**base, "provider": {"name": "tradier"}}):
            with self.assertRaises(eng.ConfigError):
                cfgmod.from_dict(bad)


class TestPipeline(unittest.TestCase):
    def test_run_twice_produces_delta_and_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = synth_cfg(tmp)
            prov = cfgmod.make_provider(c)
            store = SnapshotStore(tmp)
            r1 = run_once(c, prov, store)
            self.assertIsNone(r1["delta"])
            self.assertEqual(r1["mapped"]["mapping"]["method"], "ratio")
            r2 = run_once(c, prov, store)
            self.assertIsNotNone(r2["delta"])
            self.assertGreaterEqual(len(list(store.iter_summaries("NQ-SYNTHETIC"))), 1)
            self.assertIn("snapshots", stability(store.iter_summaries("NQ-SYNTHETIC")))

    def test_no_futures_ref_means_live_mapping_in_pine(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = synth_cfg(tmp, futures_ref={"mode": "none"})
            r = run_once(c, cfgmod.make_provider(c))
            self.assertIsNone(r["mapped"])
            self.assertIn("TradingView", r["summary"]["mapping_note"])
            self.assertIn("fac=0;", r["pine"])

    def test_futures_options_csv_identity(self):
        c = cfgmod.from_dict({"market": "MES", "source": "ES_FOP", "provider": {
            "name": "csv", "path": str(ROOT / "tests" / "data" / "es_fop_sample.csv")},
            "engine": {"max_dte": 120, "min_profile_coverage": 0.5}})
        prov = cfgmod.make_provider(c)
        # the fixture is dated 2026-10-20; pin "now" so expirations are in the future
        snap = prov.fetch_snapshot("ES_FOP")
        res = eng.compute(snap, c.engine, asof=snap.spot_time)
        self.assertNotEqual(res.status, "UNAVAILABLE")
        self.assertGreater(sum(1 for r in res.rows if r.gamma_quality.value == "CALC"), 0)


class TestExport(unittest.TestCase):
    def test_round_trip(self):
        s = {"asof": "2026-10-20T15:00:00+00:00", "ref_price": 5800.0, "ref_quality": "DL", "positioning": "conventional",
             "unit": "usd_per_1pct", "net": 1.5e9, "regime": "POSITIVE", "status": "OK",
             "zero_gamma": {"price": 5750.0}, "zero_gamma_status": "ESTIMATE", "call_wall": {"price": 5900.0},
             "put_wall": {"price": 5700.0}, "max_positive": {"price": 5850.0}, "max_negative": {"price": 5650.0},
             "expected_move": {"one_sigma_points": 40.0}, "basket": ["2026-10-20", "2026-11-20"],
             "concentrations": [{"price": 5850.0, "sign": "+", "share": 0.2}, {"price": 5650.0, "sign": "-", "share": 0.1}]}
        p = pine_payload(s, "ES", "SPX", "ratio", delta={"zero_gamma": -5.0, "prev_regime": "NEGATIVE"})
        d = parse_payload(p)
        self.assertEqual(d["zg"], "5750.00")
        self.assertEqual(d["netb"], "1.5000")
        self.assertEqual(d["preg"], "NEG")
        self.assertEqual(d["tv"], "SP:SPX")
        self.assertEqual(d["levels"][1], (5650.0, "-", 0.1))
        self.assertNotIn("e+", p)
        self.assertNotIn("e-", p.replace("model=", "").replace("ref=", ""))

    def test_synthetic_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = synth_cfg(tmp)
            d = parse_payload(run_once(c, cfgmod.make_provider(c))["pine"])
            self.assertEqual((d["q"], d["oi"], d["gk"]), ("SYN", "SYN", "SYN"))


class TestAlerts(unittest.TestCase):
    def test_regime_change_shift_and_cooldown(self):
        sent, t = [], [1000.0]
        a = AlertEngine(AlertConfig(level_shift_ticks=10, cooldown_s=600), clock=lambda: t[0],
                        sender=lambda url, e: sent.append(e))
        prev = {"regime": "POSITIVE", "zero_gamma": {"price": 20000.0}}
        cur = {"regime": "NEGATIVE", "zero_gamma": {"price": 20010.0}}
        ev = a.evaluate("NQ", prev, cur, 0.25)
        self.assertEqual({e["type"] for e in ev}, {"regime_change", "level_shift"})
        self.assertEqual(a.evaluate("NQ", prev, cur, 0.25), [])          # cooldown
        t[0] += 601
        self.assertEqual(len(a.evaluate("NQ", prev, cur, 0.25)), 2)
        self.assertEqual(a.stale_check("NQ", t[0] - 5000)[0]["type"], "data_stale")


class TestService(unittest.TestCase):
    def test_http_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = MarketWorker(synth_cfg(tmp))
            w.step()
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler({"NQ": w}))
            th = threading.Thread(target=httpd.serve_forever, daemon=True)
            th.start()
            base = f"http://127.0.0.1:{httpd.server_address[1]}"

            def get(path):
                with urllib.request.urlopen(base + path) as resp:
                    return resp.read().decode()
            try:
                self.assertTrue(json.loads(get("/health"))["ok"])
                self.assertIn("profile", json.loads(get("/api/levels?market=NQ")))
                self.assertTrue(get("/api/pine?market=NQ").startswith("GEX1;"))
                self.assertIn("<title>", get("/"))
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_provider_down_keeps_last_result_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = MarketWorker(synth_cfg(tmp))
            w.step()
            good = w.result

            def boom(*a, **k):
                raise ConnectionError("provider disconnected")
            w.provider.fetch_snapshot = boom
            w.step()
            self.assertIs(w.result, good)
            self.assertEqual(w.health()["status"], "degraded")
            self.assertIn("disconnected", w.health()["last_error"])


class TestIndicatorSource(unittest.TestCase):
    def test_info_tracks_the_file(self):
        from gexsys.indicator import info
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.pine"
            f.write_text('//@version=6\nindicator("GEX PRO - NQ / ES")\nx = input.int(1, "a")\n', encoding="utf-8")
            a = info(f, with_changes=False)
            self.assertEqual((a["name"], a["pine_version"], a["lines"], a["inputs"]), ("GEX PRO - NQ / ES", 6, 4, 1))
            f.write_text(f.read_text(encoding="utf-8") + "// edit\n", encoding="utf-8")
            b = info(f, with_changes=False)
            self.assertNotEqual(a["version"], b["version"])            # any edit changes the version
            self.assertTrue(b["code"].endswith("// edit\n"))

    def test_service_and_site_serve_the_real_script(self):
        from gexsys.indicator import PINE
        code = PINE.read_text(encoding="utf-8")
        self.assertIn('indicator("GEX PRO', code)
        with tempfile.TemporaryDirectory() as tmp:
            w = MarketWorker(synth_cfg(tmp))
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler({"NQ": w}))
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_address[1]}/api/indicator") as r:
                    self.assertEqual(json.loads(r.read())["code"], code)
            finally:
                httpd.shutdown()
                httpd.server_close()


class TestSingleServer(unittest.TestCase):
    def test_second_server_on_the_same_port_is_refused(self):
        from gexsys.service import ExclusiveHTTPServer
        from http.server import BaseHTTPRequestHandler
        first = ExclusiveHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        try:
            with self.assertRaises(OSError):
                ExclusiveHTTPServer(("127.0.0.1", first.server_address[1]), BaseHTTPRequestHandler)
        finally:
            first.server_close()


class TestAlertsUseSameUnits(unittest.TestCase):
    def test_no_false_level_shift_from_futures_basis(self):
        # same chain twice, with a 1% futures basis: nothing moved, so no level-shift alert may fire
        with tempfile.TemporaryDirectory() as tmp:
            c = synth_cfg(tmp)
            sent = []
            a = AlertEngine(AlertConfig(level_shift_ticks=20, cooldown_s=0), sender=lambda url, e: sent.append(e))
            prov = SyntheticProvider(live_clock=False)
            prov._n = 0
            store = SnapshotStore(tmp)
            run_once(c, prov, store, a)
            prov._n = 0                                         # identical second snapshot
            r = run_once(c, prov, store, a)
            self.assertIsNotNone(r["mapped"])                    # levels really were mapped with a basis
            self.assertEqual([e for e in sent if e["type"] == "level_shift"], [])


class TestKeepLastGood(unittest.TestCase):
    def test_unusable_refresh_keeps_good_result_and_restart_restores_it(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as tmp:
            c = synth_cfg(tmp)
            w = MarketWorker(c)
            w.step()
            good = w.result
            self.assertEqual(good["summary"]["status"], "OK")
            real = w.provider.fetch_snapshot

            def blank(*a, **k):                  # e.g. a feed blanked overnight: every OI reset to 0
                s = real(*a, **k)
                return replace(s, contracts=[replace(x, open_interest=0.0) for x in s.contracts])
            w.provider.fetch_snapshot = blank
            w.step()
            self.assertIs(w.result, good)
            self.assertIn("unusable", w.health()["last_error"])
            w2 = MarketWorker(c)                 # restart: begins with the saved good result, marked
            self.assertEqual(w2.result["summary"]["status"], "OK")
            self.assertTrue(any("restored" in x for x in w2.result["summary"]["warnings"]))


class TestStaticSite(unittest.TestCase):
    def test_build_writes_site_and_keeps_state_between_runs(self):
        from unittest import mock
        from gexsys import site
        empty = {"posts": [], "events": [], "fetched_at": None}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(site.Calendar, "get", return_value=empty), \
                mock.patch.object(site.Posts, "get", return_value=empty):
            out, state = Path(tmp) / "site", Path(tmp) / "state"
            res = site.build([synth_cfg(tmp)], out, state)
            self.assertEqual(res["NQ-SYNTHETIC"][1], "OK")
            html = (out / "index.html").read_text(encoding="utf-8")
            from gexsys.indicator import PINE
            ind = json.loads((out / "data" / "indicator.json").read_text(encoding="utf-8"))
            self.assertEqual(ind["code"], PINE.read_text(encoding="utf-8"))        # the hosted page gets the script
            self.assertIn("window.GEX_STATIC = true", html.split("const $ =")[0])     # flag set before the app script
            d = json.loads((out / "data" / "all.json").read_text(encoding="utf-8"))
            self.assertTrue(d["static"])
            pub = d["workers"][0]["published"]
            self.assertIsNotNone(pub)                                                   # latest slot published
            self.assertTrue((out / "data" / "pine-published-NQ.txt").read_text().startswith("GEX1;"))
            site.build([synth_cfg(tmp)], out, state)                                    # a fresh run, same state
            d2 = json.loads((out / "data" / "all.json").read_text(encoding="utf-8"))
            self.assertEqual(d2["workers"][0]["published"]["published_at"], pub["published_at"])  # not re-published
            self.assertIsNotNone(d2["workers"][0]["result"]["delta"])                   # history carried over


class TestSensitivity(unittest.TestCase):
    def test_models_differ(self):
        out = sensitivity(make_chain("SPX"))
        self.assertEqual(set(out), {"conventional", "dealer_short_all", "dealer_long_all"})
        self.assertLess(out["dealer_short_all"]["net"], 0)
        self.assertGreater(out["dealer_long_all"]["net"], 0)


if __name__ == "__main__":
    unittest.main()
