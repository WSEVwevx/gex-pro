"""The site's frame (docs/style.md): one row of pages, the paste always reachable on a phone, the backup label kept short."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "dashboard" / "assets" / "terminal.css").read_text(encoding="utf-8")
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
PHONE = CSS[CSS.index("@media(max-width:820px){"):]


class Shell(unittest.TestCase):
    def test_pages_are_one_row_that_never_wraps(self):
        side = re.search(r"\n\.side\{[^}]*\}", CSS).group(0)
        for piece in ("overflow-x:auto", "white-space:nowrap", "grid-area:side"):
            self.assertIn(piece, side)
        self.assertNotIn("flex-wrap:wrap", side)
        self.assertIn('grid-template-areas:"mq" "top" "side" "area"', CSS)

    def test_every_page_keeps_its_tab_and_code(self):
        for p in ("levels", "ladder", "heatmap", "screener", "bias", "track", "backtest", "briefings", "news", "indicator", "library", "glossary", "health"):
            self.assertRegex(HTML, rf'<button role="tab" data-p="{p}"[^>]*>.*?<kbd>[A-Z?]+</kbd>', p)   # the codes stay for the command line

    def test_the_paste_is_pinned_on_a_phone(self):
        # the paste is in the phone's bottom bar (2040 redesign): fixed, above the home indicator, with its date
        bar = re.search(r"(?m)^\.botbar\{[^}]*\}", CSS).group(0)
        self.assertIn("position:fixed", bar)
        self.assertIn("bottom:0", bar)
        self.assertIn("env(safe-area-inset-bottom", bar)
        self.assertIn(".botbar{display:flex}", PHONE)
        self.assertIn('<button type="button" id="bbCopy" class="bb-copy"><b>Copy paste</b><span id="bbCopyT">', HTML)
        self.assertIn('$("bbCopyT").textContent = anyPub ? slotTxt(ws.find(w=>w.published).published.slot_et)', JS)
        self.assertRegex(PHONE, r"\.area\{[^}]*padding:0 var\(--sp-4\) calc\(88px \+ env\(safe-area-inset-bottom,0px\)\)")   # the last line is never under the bar

    def test_the_short_backup_label_keeps_what_matters(self):
        line = next(l for l in JS.splitlines() if "s && s.backup ?" in l)
        short = re.sub(r'<span class="bn-more">.*?</span>', "", line)
        for words in ("OCC open interest + VIX-family vols.", "One implied vol per expiry (no skew)", "the TradingView paste keeps its last published levels."):
            self.assertIn(words, short)
        self.assertIn(".banner .bn-more{display:none}", PHONE)


if __name__ == "__main__":
    unittest.main()
