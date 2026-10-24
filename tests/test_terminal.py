"""Website plumbing: asset serving and versioned asset links in the hosted build."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from gexsys.service import MarketWorker
from tests.test_integration import _Empty, app, synth_cfg


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
                for src in ("assets/app.js", "assets/terminal.css", "assets/library.js"):
                    self.assertIn(src, page)
                with urllib.request.urlopen(base + "/api/all") as r:
                    self.assertIn("workers", json.loads(r.read()))
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
            self.assertRegex(html, r'"assets/library\.js\?v=[0-9a-f]{10}"')            # the Library's lessons
            self.assertLess(html.index("window.GEX_STATIC = true"), html.index("assets/app.js"))   # flag first
            self.assertTrue((out / "assets" / "app.js").exists() and (out / "data" / "all.json").exists())



class TestScriptNames(unittest.TestCase):
    def test_no_two_functions_share_a_name(self):
        """A second `function x()` silently replaces the first in the browser (it blanked the Levels list once)."""
        import re
        js = (Path(__file__).resolve().parent.parent / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
        names = re.findall(r"(?:^|\n)\s*(?:async\s+)?function\s+(\w+)\s*\(", js)
        self.assertEqual(sorted({n for n in names if names.count(n) > 1}), [])


if __name__ == "__main__":
    unittest.main()
