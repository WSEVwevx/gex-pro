"""The phone as an instrument (2040 redesign, Phase 3): a one-thumb bottom bar with the paste and search, nothing under
it, iOS safe areas, a market swipe only on the price, and a headline that never widens the page."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "assets" / "terminal.css").read_text(encoding="utf-8")
HTML = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
PHONE = CSS[CSS.index("@media(max-width:820px){"):]


class BottomBar(unittest.TestCase):
    def test_places_search_and_the_paste(self):
        bar = re.search(r'<nav class="botbar" id="botbar".*?</nav>', HTML, re.S).group(0)
        self.assertEqual(re.findall(r'data-p="(\w+)"', bar), ["levels", "ladder", "heatmap"])
        self.assertIn('id="bbSearch"', bar)
        self.assertIn('id="bbCopy"', bar)

    def test_tap_targets_and_safe_area(self):
        btn = re.search(r"(?m)^\.botbar button\{[^}]*\}", CSS).group(0)
        self.assertGreaterEqual(int(re.search(r"min-height:(\d+)px", btn).group(1)), 44)
        self.assertIn("calc(var(--sp-1) + env(safe-area-inset-bottom,0px))", re.search(r"(?m)^\.botbar\{[^}]*\}", CSS).group(0))

    def test_only_on_phones(self):
        self.assertIn(".botbar{display:none;", CSS)
        self.assertIn(".botbar{display:flex}", PHONE)

    def test_the_current_page_is_marked(self):
        self.assertIn('document.querySelectorAll("#botbar [data-p]").forEach(b => b.dataset.p === p ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"));', JS)

    def test_search_opens_over_the_top_bar_and_closes(self):
        self.assertIn('$("bbSearch").onclick = () => { document.body.classList.add("cmd-open"); $("cmd").focus(); };', JS)
        self.assertIn("body.cmd-open .cmd{display:flex;position:fixed;", PHONE)
        self.assertEqual(JS.count('document.body.classList.remove("cmd-open")'), 3)       # blur, a command run, Esc


class Swipe(unittest.TestCase):
    def test_only_the_price_area_listens(self):
        self.assertEqual(re.findall(r'\$\("(\w+)"\)\.addEventListener\("touch(?:start|end)"', JS), ["lvHead", "lvHead"])

    def test_a_clear_sideways_swipe_only(self):
        self.assertIn("if(Math.abs(dx) >= 60 && Math.abs(dx) > 2 * Math.abs(dy)) setMarket(market === \"NQ\" ? \"ES\" : \"NQ\");", JS)
        self.assertIn("{passive: true}", JS)                        # never blocks the page's own scroll


class Width(unittest.TestCase):
    def test_the_phone_headline_lets_the_price_column_wrap(self):
        # 2026-11-21: "auto minmax(0,1fr)" sized the price column to its longest line and squeezed the regime to 41 px;
        # "Negative gamma" then overflowed and the phone zoomed the whole page out to 439 px
        head = re.search(r"\.lv-head\{display:grid;grid-template-columns:([^;]+);", PHONE).group(1)
        self.assertEqual(head, "minmax(0,1fr) auto")


if __name__ == "__main__":
    unittest.main()
