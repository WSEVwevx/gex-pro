"""Decision 001, C2: the chart library stays off the first screen's critical path.

Measured 23 Nov 2026 (local gzip copy, 375 px, Slow 4G, cold, n=5): without the synchronous script tag the median LCP
fell from 2,692 to 2,096 ms and the layout shift went from up to 0.295 to 0. These tests keep the tag out and make
sure every chart user loads the library first.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
LIB = "lightweight-charts-4.2.0.js"


def body(name):
    """The source of a top-level function in app.js, up to the next top-level declaration."""
    m = re.search(r"^(?:async )?function " + name + r"\(.*?(?=^(?:async )?function |^const |^let |^window\.)", JS, re.S | re.M)
    assert m, name
    return m.group(0)


class LazyChartLibrary(unittest.TestCase):
    def test_no_script_tag_on_the_first_screen(self):
        self.assertNotIn(LIB, HTML)
        self.assertNotIn("LightweightCharts", HTML)

    def test_the_file_is_still_shipped(self):
        self.assertTrue((ROOT / "dashboard" / "assets" / LIB).is_file())
        self.assertIn(f'"assets/{LIB}"', JS)

    def test_heatmap_waits_for_the_library(self):
        self.assertIn("await needCharts()", body("loadHeatmap"))

    def test_stock_chart_waits_for_the_library(self):
        opener = body("openStockChart")
        self.assertIn("await needCharts()", opener)
        self.assertLess(opener.index("await needCharts()"), opener.index("renderStockChart("))

    def test_every_library_user_is_behind_the_loader(self):
        # renderHeatmap returns early without the library; renderStockChart is only reached from openStockChart
        self.assertIn("!window.LightweightCharts) return", body("renderHeatmap"))
        callers = re.findall(r"(?<!function )renderStockChart\(c\)", JS)
        self.assertEqual(len(callers), 2)  # openStockChart, and the range buttons inside renderStockChart itself
        self.assertIn("if(!LC){", body("renderStockChart"))

    def test_a_failed_load_can_be_retried_and_says_so(self):
        loader = body("needCharts")
        self.assertIn("lcPending = null", loader)
        self.assertIn("window.LightweightCharts ? done(true) : fail()", loader)  # a 200 without the library is retried too
        self.assertIn("could not load", JS[JS.index("const LC_FAIL"):][:120])
        self.assertNotIn("it comes from unpkg.com", JS)  # the old message named a CDN the library no longer comes from


if __name__ == "__main__":
    unittest.main()
