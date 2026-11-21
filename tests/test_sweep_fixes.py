"""Defects from the ui-auditor sweep of 2026-11-21 (after PRs 51-58), each held by a test."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "assets" / "terminal.css").read_text(encoding="utf-8")
HTML = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Ages(unittest.TestCase):
    def test_never_sixty_minutes(self):
        fn = next(l for l in JS.splitlines() if l.startswith("function ago(iso){"))
        cases = [0.5, 1.2, 59.4, 59.7, 60, 119.6, 1679.8]
        src = fn + f"\nconsole.log(JSON.stringify({json.dumps(cases)}.map(m => ago(new Date(Date.now() - m * 60000).toISOString()))))"
        got = json.loads(subprocess.run(["node"], input=src, capture_output=True, encoding="utf-8", check=True).stdout)
        self.assertEqual(got, ["just now", "1 min ago", "59 min ago", "1 h 0 min ago", "1 h 0 min ago", "2 h 0 min ago", "28 h 0 min ago"])


class Heatmap(unittest.TestCase):
    def test_the_profile_leaves_room_for_candles_on_a_phone(self):
        self.assertIn('const hmGexW = () => Math.min(190, Math.round(Math.max(300, $("hmChart").clientWidth - 80) * 0.38));', JS)
        fn = JS.split("function renderHeatmap(){", 1)[1].split("\n}\n", 1)[0]
        self.assertNotRegex(fn, r"\b190\s*[*/]|[*/-]\s*190\b")              # every use goes through hmGexW()

    def test_the_first_view_waits_for_a_size(self):
        self.assertIn('else if($("hmChart").clientWidth < 100){', JS)
        self.assertIn("ro0.disconnect(); renderHeatmap();", JS)

    def test_the_axis_labels_are_not_called_now(self):
        self.assertNotIn("= now", HTML)
        self.assertIn("labels on the price axis: the newest saved snapshot", HTML)


class Access(unittest.TestCase):
    def test_the_closed_drawer_is_out_of_the_tab_order(self):
        self.assertRegex(HTML, r'<aside class="explain" id="explain" aria-hidden="true" inert ')
        self.assertIn('$("explain").inert = false;', JS)
        self.assertIn('$("explain").inert = true;', JS)

    def test_live_table_values_use_text_strength_colours(self):
        self.assertIn('<span class="ld-v ${pos ? "pos" : "neg"}">', JS)
        for k in ("pos", "neg"):
            self.assertIn(f".ld-v.{k}{{color:color-mix(in oklch,var(--{k}) 82%,var(--ink))}}", CSS)

    def test_a_missing_level_is_not_in_its_level_colour(self):
        self.assertIn('away(v), v == null ? "" : color);', JS)

    def test_the_bottom_bar_date_fits(self):
        self.assertIn('.published.slot_et).replace(/^[A-Z][a-z]{2}, /, "")', JS)


if __name__ == "__main__":
    unittest.main()
