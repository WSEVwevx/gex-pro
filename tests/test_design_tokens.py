"""The design system (docs/style.md): every colour, space and radius on the site comes from a token in terminal.css."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "dashboard" / "assets" / "terminal.css").read_text(encoding="utf-8")
TOKEN_BLOCKS = re.compile(r':root(\[data-theme="light"\])?\{[^}]*\}')
RULES = TOKEN_BLOCKS.sub("", CSS)                     # everything but the two token blocks


class DesignTokens(unittest.TestCase):
    def test_a_4px_spacing_scale(self):
        got = dict(re.findall(r"--sp-(\d):(\d+)px", CSS))
        self.assertEqual(sorted(got), [str(i) for i in range(1, 9)])
        self.assertTrue(all(int(v) % 4 == 0 for v in got.values()), got)
        self.assertEqual([int(got[str(i)]) for i in range(1, 9)], sorted(int(v) for v in got.values()))

    def test_three_radii_and_nothing_else(self):
        self.assertEqual(sorted(set(re.findall(r"--r-(\d):", CSS))), ["1", "2", "3"])
        for decl in re.findall(r"border-radius:([^;}]+)", RULES):
            for part in decl.split():
                self.assertRegex(part, r"^(var\(--r-[123]\)|0|50%|999px)$", decl)   # circles and pills are shapes, not radii

    def test_no_colour_outside_the_tokens(self):
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", RULES), [])
        self.assertEqual(re.findall(r"rgba?\((?!var\()[^)]*\)", RULES), [])

    def test_every_colour_token_exists_in_both_themes(self):
        blocks = [m.group(0) for m in TOKEN_BLOCKS.finditer(CSS)]
        dark, light = blocks[0], next(b for b in blocks if b.startswith(':root[data-theme="light"]'))
        names = lambda block: set(re.findall(r"(--[a-z0-9-]+):", block))
        themed = {"--page", "--panel", "--panel2", "--raise", "--ink", "--ink2", "--ink3", "--ink4", "--pos", "--neg", "--zg", "--warn", "--card-shadow"}
        self.assertLessEqual(themed, names(dark))
        self.assertLessEqual(themed, names(light))

    def test_every_text_tier_reads_on_every_surface(self):
        def lum(h):
            c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
            return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
        ratio = lambda a, b: (max(lum(a), lum(b)) + .05) / (min(lum(a), lum(b)) + .05)
        blocks = [m.group(0) for m in TOKEN_BLOCKS.finditer(CSS)]
        for block in (blocks[0], next(b for b in blocks if b.startswith(':root[data-theme="light"]'))):
            tok = dict(re.findall(r"(--[a-z0-9]+):(#[0-9a-fA-F]{6});", block))
            for ink in ("--ink", "--ink2", "--ink3", "--ink4"):
                for surface in ("--page", "--panel", "--panel2", "--raise"):
                    self.assertGreaterEqual(ratio(tok[ink], tok[surface]), 4.5, (ink, surface, block[:30]))

    def test_no_inline_styles_in_the_page(self):
        html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'<[^>]*\sstyle="[^"]*"', html), [])

    def test_phone_tables_keep_numbers_on_one_line(self):
        phone = CSS[CSS.index("@media(max-width:820px){"):]
        self.assertIn(".trk-table td.m,.trk-table td:first-child,.trk-table th,.tm{white-space:nowrap}", phone)
        self.assertIn(":has(>table.trk-table){overflow-x:auto}", phone)       # a wide table scrolls in its own box, not the page

    def test_cards_have_no_border(self):
        card = re.search(r"\n\.card\{[^}]*\}", CSS).group(0)
        self.assertIn("border:0", card)
        self.assertIn("box-shadow:var(--card-shadow)", card)


if __name__ == "__main__":
    unittest.main()
