"""The Heatmap (2040 redesign, Phase 5): a candle with no saved GEX gets a hatched ground that says so, never an old
snapshot's colour; the chart library gets rgb() colours (it cannot parse the OKLCH tokens); hidden controls stay hidden."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "assets" / "terminal.css").read_text(encoding="utf-8")


def gaps(times, cols):
    fn = "function hmGaps(times, cols){" + JS.split("function hmGaps(times, cols){", 1)[1].split("\n}\n", 1)[0] + "\n}"
    src = "const HM_GAP_S = 5400;\n" + fn + f"\nconsole.log(JSON.stringify(hmGaps({json.dumps(times)}, {json.dumps(cols)})))"
    return json.loads(subprocess.run(["node"], input=src, capture_output=True, encoding="utf-8", check=True).stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class NoSavedGex(unittest.TestCase):
    T = [k * 300 for k in range(40)]                              # 5-minute candles over 3h15

    def test_a_long_silence_is_one_run(self):
        # one snapshot at the first candle: candles 0..18 are within 90 min (18 x 300 = 5,400 s), 19.. are not
        self.assertEqual(gaps(self.T, [{"_bar": 0, "t": 0}]), [[19, 39]])

    def test_a_new_snapshot_ends_the_run(self):
        # the snapshot at candle 20 (6,000 s) covers to 11,400 s (candle 38); candle 39 is late again
        self.assertEqual(gaps(self.T, [{"_bar": 0, "t": 0}, {"_bar": 6000, "t": 6000}]), [[19, 19], [39, 39]])

    def test_before_the_first_snapshot_is_not_a_gap(self):
        self.assertEqual(gaps(self.T, [{"_bar": 3000, "t": 3000}]), [[29, 39]])

    def test_the_threshold_matches_the_atlas_and_the_tooltip(self):
        self.assertIn("const HM_GAP_S = 5400;", JS)
        self.assertIn("if(times[k] - c.t > HM_GAP_S) continue;", JS)        # no colour in the heat image
        self.assertIn("if(p.time - col.t > HM_GAP_S){", JS)                 # the tooltip says so
        self.assertIn("no GEX saved for this time", JS)
        self.assertIn('const txt = "no saved GEX";', JS)


class ChartColours(unittest.TestCase):
    def test_the_chart_library_never_gets_a_raw_token(self):
        # 2026-11-21: the OKLCH tokens (PR 48) made lightweight-charts throw "Cannot parse color" and the Heatmap was blank
        for fn in ("function hmColors(){", "function renderStockChart(c){"):
            body = JS.split(fn, 1)[1].split("\n}\n", 1)[0]
            self.assertNotRegex(body, r'cssVar\("--(panel|page|ink\d?|good|bad|line)"\)', fn)
        self.assertIn('hmChart.addCandlestickSeries({upColor: lcVar("--good"), downColor: lcVar("--bad")', JS)

    def test_rgb_comes_from_a_painted_pixel(self):
        self.assertIn("RGB_PX.fillRect(0, 0, 1, 1); return [...RGB_PX.getImageData(0, 0, 1, 1).data.slice(0, 3)];", JS)
        self.assertIn('const lcVar = n => `rgb(${rgbOf(cssVar(n)).join(",")})`;', JS)


class Hidden(unittest.TestCase):
    def test_hidden_always_hides(self):
        # 2026-11-21: ".seg{display:flex}" beat the hidden attribute, so the density buttons showed on every page
        self.assertIn("[hidden]{display:none!important}", CSS)
        self.assertLess(CSS.index("[hidden]{display:none!important}"), CSS.index(".seg{display:flex;"))


if __name__ == "__main__":
    unittest.main()
