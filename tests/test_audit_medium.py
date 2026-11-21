"""Medium and low defects from the hosted audit of 2026-11-20: pages that ignored the market switch, a label cut off
the Bias chart, heatmap day labels drawn on top of each other, placeholder heights from before the redesign, and four
labels under 4.5:1."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "assets" / "terminal.css").read_text(encoding="utf-8")
HTML = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")


class MarketSwitch(unittest.TestCase):
    def test_track_backtest_and_studies_follow_the_site_market(self):
        fn = JS.split("function setMarket(m){", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("trkM = btM = stM = m;", fn)
        for k in ('store.set("gex.trkm", m)', 'store.set("gex.btm", m)', 'store.set("gex.stm", m)',
                  'if(trk && page === "track") renderTrack();', 'if(studies && page === "backtest") renderStudies();'):
            self.assertIn(k, fn)


class Charts(unittest.TestCase):
    def test_a_bias_label_too_long_for_the_margin_uses_short_names(self):
        self.assertIn("const fits = t => t.length * 6.4 <= padR - 12;", JS)
        self.assertIn("return fits(t) ? t : `${names.map(n => SHORT[n] || n).join(\" · \")} ${num(p,0)}`;", JS)
        # the ES label of 2026-11-20 does not fit the 132 px desktop margin in full, and does in short
        self.assertGreater(len("Call wall · Abs gamma 7,017") * 6.4, 132 - 12)
        self.assertLessEqual(len("CW · AG 7,017") * 6.4, 132 - 12)

    def test_heatmap_day_labels_never_overlap_each_other_or_the_gex_label(self):
        self.assertIn("if(x0 >= 0 && x0 >= labEnd + 8 * hr && x1 <= gexX - 8 * hr){ ctx.fillText(txt, x0, fs + 2 * vr); labEnd = x1; }", JS)
        self.assertIn("const gexX = gx0 != null && hm._profile && W / hr - gx0 - 6 >= 50 ? gx0 * hr : Infinity;", JS)


class Heights(unittest.TestCase):
    def test_every_page_reserves_at_least_one_height_per_card(self):
        m = re.search(r"const DEFAULT_H = \{wide: (\{.*?\}),\s+narrow: (\{.*?\})\};", JS, re.S)
        idx = [(x.start(), x.group(1)) for x in re.finditer(r'<div id="(\w+View)"', HTML)] + [(len(HTML), None)]
        for block in m.groups():
            got = {k: v.split(",") for k, v in re.findall(r"(\w+View):\[([\d,]+)\]", block)}
            for (s, view), (e, _) in zip(idx, idx[1:]):
                self.assertGreaterEqual(len(got[view]), len(re.findall(r'class="card\b', HTML[s:e])), view)

    def test_the_heights_say_when_they_were_measured(self):
        self.assertIn("every page re-measured 2026-11-20 after the redesign", JS)


class Contrast(unittest.TestCase):
    def test_small_coloured_labels_use_ink(self):
        self.assertIn(".plan-sc em{font-style:normal;font:700 var(--fs-xs) var(--mono);color:var(--ink2);", CSS)
        self.assertIn('<span class="tag" style="border-color:${R[2]}">', JS)
        self.assertIn('<span class="tag" style="border-color:${col}">', JS)
        self.assertNotRegex(JS, r'class="tag" style="color:')
        self.assertIn("// ink: --em text read 4.4:1 in light", JS)


class Times(unittest.TestCase):
    def test_the_screener_future_says_when_it_was_fetched(self):
        self.assertIn('${market} future${scr.fetched ? ` · fetched ${etTime(scr.fetched)} ET` : ""}', JS)


if __name__ == "__main__":
    unittest.main()
