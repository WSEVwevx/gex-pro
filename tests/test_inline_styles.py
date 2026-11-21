"""Phase 6 of the 2040 redesign: static inline styles live in terminal.css as classes; only data-driven ones (a colour
from a variable, a width or position in %, a custom property) stay inline. Every class app.js uses for colour exists."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "assets" / "terminal.css").read_text(encoding="utf-8")


class InlineStyles(unittest.TestCase):
    def test_the_count_does_not_grow(self):
        lines = [l for l in JS.splitlines() if re.search(r"style=|\.style\b", l)]
        self.assertLessEqual(len(lines), 57, "a new inline style: use a class in terminal.css unless the value is data")

    def test_no_static_colour_or_display_toggle(self):
        self.assertNotRegex(JS, r'style="color:var\(--[a-z0-9]+\)"')         # a fixed colour is a class
        self.assertNotIn(".style.opacity", JS)                                 # tooltips go through tipAt
        self.assertNotIn('.style.display = ', JS)                              # toggles use the hidden attribute

    def test_tooltips_show_with_a_class(self):
        self.assertIn('const tipAt = (el, x, y) => { el.classList.add("on");', JS)
        self.assertIn(".tip.on{opacity:1}", CSS)


class ColourClasses(unittest.TestCase):
    def test_every_colour_class_used_exists(self):
        used = set(re.findall(r'\bc-(pos|neg|zg|ink2|ink3|good|bad|warn|mp)\b', JS))
        for k in used:
            self.assertRegex(CSS, r"\.c-%s(\.c-%s)?\{color:var\(--%s\)" % (k, k, k), k)

    def test_they_beat_a_containers_bold_colour(self):
        # 2026-11-21 review: ".tk b{color:var(--ink2)}" outranked ".c-pos" and the ticker's walls lost their colour
        self.assertIn(".tk b{", CSS)
        for k in ("pos", "neg", "good", "bad"):
            self.assertIn(f".c-{k}.c-{k}{{color:var(--{k})}}", CSS)


if __name__ == "__main__":
    unittest.main()
