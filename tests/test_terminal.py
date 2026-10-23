"""Terminal additions: IV term structure and skew, the levels timeline, asset serving, versioned links."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from gexsys import engine as eng
from gexsys import pricing
from gexsys.extras import term_structure
from gexsys.service import MarketWorker
from tests.test_integration import _Empty, app, synth_cfg
from tests.util import chain, contract


class TestTermStructure(unittest.TestCase):
    def snap(self):
        cs = []
        for days in (7, 30):
            for k in range(80, 121, 2):
                skewed = 0.20 + (100 - k) * 0.004               # downside strikes richer: positive skew
                cs += [contract(k, "C", oi=100, iv=skewed, days=days), contract(k, "P", oi=100, iv=skewed, days=days)]
        return chain(cs, spot=100.0)

    def test_atm_wings_and_skew(self):
        s = self.snap()
        res = eng.compute(s, eng.EngineConfig(max_dte=45))
        rows = term_structure(s, res)
        self.assertEqual([r["dte"] for r in rows], [7.0, 30.0])
        for r in rows:
            self.assertAlmostEqual(r["atm_iv"], 0.20)                       # strike 100
            self.assertLess(r["put25_strike"], 100)
            self.assertGreater(r["call25_strike"], 100)
            self.assertGreater(r["skew_pts"], 0)
            t = r["dte"] / 365                                               # the chosen wings really are ~25 delta
            dp = pricing.bsm_delta(100, r["put25_strike"], t, 0.0, 0.0, r["put25_iv"], False)
            dc = pricing.bsm_delta(100, r["call25_strike"], t, 0.0, 0.0, r["call25_iv"], True)
            self.assertTrue(0.15 < abs(dp) < 0.35 and 0.15 < dc < 0.35, (dp, dc))
        self.assertGreater(rows[1]["put25_strike"] and 100 - rows[1]["put25_strike"], 100 - rows[0]["put25_strike"])  # wider wings further out


class TestTimeline(unittest.TestCase):
    def test_each_good_refresh_adds_one_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = MarketWorker(synth_cfg(tmp))
            w.step()
            w.step()
            rows = w.timeline(hours=24 * 365 * 10)
            self.assertEqual(len(rows), 2)
            self.assertEqual(set(rows[0]), {"t", "ref", "zg", "cw", "pw", "ag", "net", "regime"})
            self.assertAlmostEqual(rows[-1]["ref"], w.result["mapped"]["futures_equiv_of_ref"])  # latest row, futures prices
            self.assertEqual(MarketWorker(synth_cfg(tmp)).timeline(hours=24 * 365 * 10), rows)    # survives a restart


class TestAssets(unittest.TestCase):
    def test_served_with_types_and_no_path_tricks(self):
        from gexpro.server import make_handler
        with tempfile.TemporaryDirectory() as tmp:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app({"NQ": MarketWorker(synth_cfg(tmp))})))
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            try:
                with urllib.request.urlopen(base + "/assets/app.js") as r:
                    self.assertIn("javascript", r.headers["Content-Type"])
                    self.assertIn(b"function setPage", r.read())
                with urllib.request.urlopen(base + "/assets/terminal.css") as r:
                    self.assertIn("text/css", r.headers["Content-Type"])
                for bad in ("/assets/../gexpro/server.py", "/assets/%2e%2e/README.md", "/assets/nope.exe", "/assets/"):
                    with self.assertRaises(urllib.error.HTTPError) as cm:
                        urllib.request.urlopen(base + bad)
                    self.assertEqual(cm.exception.code, 404, bad)
                with urllib.request.urlopen(base + "/") as r:
                    page = r.read().decode()
                for src in ("assets/app.js", "assets/terminal.css"):
                    self.assertIn(src, page)
                with urllib.request.urlopen(base + "/api/timeline") as r:
                    self.assertIn("NQ", json.loads(r.read()))
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_hosted_build_versions_and_copies_assets(self):
        from gexpro import site
        from gexsys.component import GexComponent
        from feeds.component import FeedsComponent
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            site.build([GexComponent([synth_cfg(tmp)]), FeedsComponent(_Empty(), _Empty())], out, Path(tmp) / "state")
            html = (out / "index.html").read_text(encoding="utf-8")
            self.assertRegex(html, r'"assets/app\.js\?v=[0-9a-f]{10}"')
            self.assertRegex(html, r'"assets/terminal\.css\?v=[0-9a-f]{10}"')
            self.assertLess(html.index("window.GEX_STATIC = true"), html.index("assets/app.js"))   # flag first
            self.assertTrue((out / "assets" / "app.js").exists() and (out / "data" / "timeline.json").exists())


if __name__ == "__main__":
    unittest.main()
