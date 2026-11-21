"""The design system (docs/style.md): every colour, space and radius on the site comes from a token in terminal.css."""
import math
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "dashboard" / "assets" / "terminal.css").read_text(encoding="utf-8")
TOKEN_BLOCKS = re.compile(r':root(\[data-theme="light"\])?\{[^}]*\}')
RULES = TOKEN_BLOCKS.sub("", CSS)                     # everything but the two token blocks


def colour(v):
    """(r, g, b, alpha), 0..1 sRGB, for hex, rgb()/rgba() or oklch(); None for anything else."""
    v = v.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return tuple(int(v[i:i + 2], 16) / 255 for i in (1, 3, 5)) + (1.0,)
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", v)
    if m:
        return tuple(int(m.group(i)) / 255 for i in (1, 2, 3)) + (float(m.group(4) or 1),)
    m = re.fullmatch(r"oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*(?:/\s*([\d.]+)\s*)?\)", v)
    if not m:
        return None
    L, C, h = (float(m.group(i)) for i in (1, 2, 3))
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))      # OKLab, then linear sRGB (Ottosson 2020)
    l_, m_, s_ = (L + .3963377774 * a + .2158037573 * b, L - .1055613458 * a - .0638541728 * b,
                  L - .0894841775 * a - 1.2914855480 * b)
    l, mm, s = l_ ** 3, m_ ** 3, s_ ** 3
    lin = (4.0767416621 * l - 3.3077115913 * mm + .2309699292 * s, -1.2684380046 * l + 2.6097574011 * mm - .3413193965 * s,
           -.0041960863 * l - .7034186147 * mm + 1.7076147010 * s)
    enc = lambda x: 12.92 * x if x <= .0031308 else 1.055 * x ** (1 / 2.4) - .055
    return tuple(min(1.0, max(0.0, enc(max(0.0, x)))) for x in lin) + (float(m.group(4) or 1),)


def lum(c):
    lin = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in c[:3]]
    return .2126 * lin[0] + .7152 * lin[1] + .0722 * lin[2]


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
        self.assertEqual(re.findall(r"\b(?:oklch|oklab|lch|lab|hsla?|hwb|color)\([^)]*\)", RULES), [])

    def test_every_colour_token_exists_in_both_themes(self):
        blocks = [m.group(0) for m in TOKEN_BLOCKS.finditer(CSS)]
        dark, light = blocks[0], next(b for b in blocks if b.startswith(':root[data-theme="light"]'))
        names = lambda block: set(re.findall(r"(--[a-z0-9-]+):", block))
        themed = {"--page", "--panel", "--panel2", "--raise", "--ink", "--ink2", "--ink3", "--ink4", "--pos", "--neg", "--zg", "--warn", "--card-shadow"}
        self.assertLessEqual(themed, names(dark))
        self.assertLessEqual(themed, names(light))

    def test_every_text_tier_reads_on_every_surface(self):
        ratio = lambda a, b: (max(lum(a), lum(b)) + .05) / (min(lum(a), lum(b)) + .05)
        blocks = [m.group(0) for m in TOKEN_BLOCKS.finditer(CSS)]
        for block in (blocks[0], next(b for b in blocks if b.startswith(':root[data-theme="light"]'))):
            tok = {k: colour(v) for k, v in re.findall(r"(--[a-z0-9-]+):([^;]+);", block)}
            for ink in ("--ink", "--ink2", "--ink3", "--ink4", "--good", "--warn", "--bad", "--prompt", "--bad-fg", "--high-fg"):
                for surface in ("--page", "--panel", "--panel2", "--raise"):
                    self.assertIsNotNone(tok[ink], ink)
                    self.assertEqual(tok[ink][3], 1.0, ink)           # text is opaque: translucency would hide a failure
                    self.assertGreaterEqual(ratio(tok[ink], tok[surface]), 4.5, (ink, surface, block[:30]))
            self.assertGreaterEqual(ratio(tok["--backup-ink"], tok["--backup-bg"]), 4.5, block[:30])

    def test_the_oklch_reader_matches_known_colours(self):
        # white, black, and the published OKLCH of pure red and pure blue (CSS Color 4), each within 1/255 per channel
        for v, rgb in (("oklch(1 0 0)", (1, 1, 1)), ("oklch(0 0 0)", (0, 0, 0)),
                       ("oklch(0.62796 0.25768 29.2339)", (1, 0, 0)), ("oklch(0.45201 0.31321 264.052)", (0, 0, 1))):
            for g, e in zip(colour(v)[:3], rgb):
                self.assertAlmostEqual(g, e, delta=1 / 255, msg=v)

    def test_every_colour_token_parses(self):
        # a colour token is hex, rgb()/rgba() or oklch(), or built from other tokens: nothing the contrast test can't read
        skip = ("--fs-", "--sp-", "--r-", "--t-", "--ease", "--sans", "--mono", "--top", "--nav", "--mq", "--card-shadow", "--fg-rgb")
        for block in (m.group(0) for m in TOKEN_BLOCKS.finditer(CSS)):
            for name, v in re.findall(r"(--[a-z0-9-]+):([^;]+);", block):
                if not name.startswith(skip):
                    self.assertTrue(colour(v) is not None or v.strip().startswith(("var(", "rgba(var(", "color-mix(")), (name, v))

    def test_surfaces_ink_and_states_are_oklch(self):
        blocks = [m.group(0) for m in TOKEN_BLOCKS.finditer(CSS)]
        for block in (blocks[0], next(b for b in blocks if b.startswith(':root[data-theme="light"]'))):
            tok = dict(re.findall(r"(--[a-z0-9-]+):([^;]+);", block))
            for name in ("--page", "--panel", "--panel2", "--raise", "--ink", "--ink2", "--ink3", "--ink4", "--good", "--warn", "--bad",
                         "--backup-bg", "--backup-ink", "--backup-hatch"):
                self.assertTrue(tok[name].strip().startswith("oklch("), (name, tok[name]))

    def test_no_inline_styles_in_the_page(self):
        html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'<[^>]*\sstyle="[^"]*"', html), [])

    def test_phone_tables_keep_numbers_on_one_line(self):
        phone = CSS[CSS.index("@media(max-width:820px){"):]
        self.assertIn(".trk-table td.m,.trk-table td:first-child,.trk-table th,.tm{white-space:nowrap}", phone)
        self.assertIn(":has(>table.trk-table){overflow-x:auto}", phone)       # a wide table scrolls in its own box, not the page

    def test_past_news_events_stay_readable(self):
        self.assertNotRegex(CSS, r"\.ev\.past\{[^}]*opacity")                # a fade drops text below 4.5:1
        self.assertIn(".ev.past,.ev.past :is(.tm,.cur,.fp,.fp b,.imp){color:var(--ink3)}", CSS)   # ink3 is in the contrast test

    def test_phone_level_history_tags_sit_under_their_number(self):
        phone = CSS[CSS.index("@media(max-width:820px){"):]
        self.assertIn("#lhTable td.m>.trk-tag,#lhTable td.m>.dim{display:block;width:fit-content;margin:2px 0 0 auto}", phone)
        self.assertIn('class="trk-log" id="lhTable"', (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8"))

    def test_phone_post_list_is_shorter_than_the_screen(self):
        phone = CSS[CSS.index("@media(max-width:820px){"):]
        self.assertIn(".posts{max-height:60vh}", phone)

    def test_level_history_date_labels_start_inside_the_chart(self):
        js = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn('g += `<text x="${Math.max(cx, pl + 16)}" y="${H - 8}" text-anchor="middle"', js)

    def test_cards_have_no_border(self):
        card = re.search(r"\n\.card\{[^}]*\}", CSS).group(0)
        self.assertIn("border:0", card)
        self.assertIn("box-shadow:var(--card-shadow)", card)


if __name__ == "__main__":
    unittest.main()
