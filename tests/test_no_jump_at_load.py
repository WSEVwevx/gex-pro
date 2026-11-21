"""CLS 0 on a warm load (redesign 2040, Phase 7, measured 2026-11-21 in headless Chrome at 1366 and 375: 0.10 -> 0).
Each cause found is held here:
1. cards remembered their heights by position, and the Levels order moved them after saving: the next load gave
   Level history the plan's 1,273 px. Heights are now keyed by each card's place in the page as written;
2. the area painted before app.js reserved heights and set the order: it stays invisible until then;
3. the backup banner and the headline grew after the data came: they keep their last height;
4. the top bar's clock and paste date, and the market tabs, changed width once filled;
5. the level history chart was an empty 150 px svg before its 230 px drawing."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "assets" / "terminal.css").read_text(encoding="utf-8")
HTML = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")


class NoJumpAtLoad(unittest.TestCase):
    def test_heights_follow_the_card_not_its_position(self):
        self.assertIn('v.querySelectorAll(".card").forEach((c, i) => { c.dataset.ci = i; })', JS)
        self.assertIn('(c.dataset.ci ?? [...v.querySelectorAll(".card")].indexOf(c))', JS)
        self.assertLess(JS.index("c.dataset.ci = i"), JS.index("\nreserve();"))
        self.assertLess(JS.index("\nreserve();"), JS.index("orderLevels(cal0 ?"))        # reserved before the order moves cards

    def test_the_area_shows_once_laid_out(self):
        head = HTML.split("</script>", 1)[0]
        self.assertIn('document.documentElement.classList.add("booting");', head)
        self.assertIn('setTimeout(function(){ document.documentElement.classList.remove("booting"); }, 1500);', head)
        self.assertIn(".booting .area{visibility:hidden}", CSS)
        self.assertLess(JS.index("orderLevels(cal0 ?"), JS.index('if(Object.keys(cardH).length) document.documentElement.classList.remove("booting");'))

    def test_a_first_visit_waits_for_the_first_draw(self):
        # final audit 2026-11-21: with no saved heights the banner (0 -> 59 px) and headline (138 -> 144) pushed the
        # plan down 71 px as the data arrived
        self.assertIn('if(Object.keys(cardH).length) document.documentElement.classList.remove("booting");', JS)
        fn = JS.split("function render(){", 1)[1][:200]
        self.assertTrue(fn.lstrip().startswith('document.documentElement.classList.remove("booting");'))

    def test_dollar_amounts_say_dollars(self):
        # final audit: Net DEX read "+220.37B" beside "-$3.24B"
        self.assertIn('(x < 0 ? "-" : "+") + "$" + (', JS)

    def test_banner_and_headline_keep_their_height(self):
        self.assertIn('<div id="banner" data-reserve></div>', HTML)
        self.assertIn('id="lvHead" data-reserve>', HTML)
        self.assertIn('document.querySelectorAll("[id$=View] .card, [data-reserve]")', JS)
        self.assertIn('...[...document.querySelectorAll("[data-reserve]")].filter(e => e.offsetParent)', JS)   # a hidden one would save 0

    def test_the_bars_keep_their_width(self):
        self.assertIn("@media(min-width:1181px){.topbar .clock{min-width:248px}#copyAll{min-width:296px}.pagebar{min-height:50px}}", CSS)
        self.assertIn('data-m="NQ">NQ</button><button role="tab" aria-selected="false" data-m="ES">ES</button></div>', HTML)

    def test_the_level_history_chart_has_its_height_before_drawing(self):
        h = re.search(r'const svg = \$\("lhChart"\), W = .*?, H = (\d+),', JS).group(1)
        self.assertIn(f"#lhChart{{height:{h}px}}", CSS)


if __name__ == "__main__":
    unittest.main()
