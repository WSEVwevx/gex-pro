"""Done means (redesign 2040): at most 8 font sizes. Every CSS font size is a --fs-* token, and the canvas and
chart-library text reads the smallest token instead of a number of its own."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "dashboard" / "assets" / "terminal.css").read_text(encoding="utf-8")
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")


class TypeScale(unittest.TestCase):
    def test_eight_steps(self):
        steps = re.findall(r"--fs-([a-z0-9]+):([\d.]+)px", CSS)
        self.assertEqual(len(steps), 8, steps)

    def test_no_raw_size_in_css(self):
        body = CSS.split("--fs-x3:", 1)[1]                                   # after the scale's own definition
        self.assertEqual(re.findall(r"font-size:\s*[\d.]+(?:px|rem|em)", body), [])
        self.assertEqual(re.findall(r"font:[^;}]*?\b[\d.]+px", body), [])

    def test_canvas_and_chart_text_use_the_token(self):
        self.assertNotRegex(JS, r"fontSize:\s*\d")
        self.assertNotRegex(JS, r"Math\.round\(10\.5 \* vr\)")
        self.assertEqual(JS.count('parseFloat(cssVar("--fs-xs")) || 10.5'), 3)


class Colours(unittest.TestCase):
    def test_no_raw_colour_outside_the_tokens(self):
        html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        body = html.split('<meta name="theme-color"', 1)[1].split(">", 1)[1]   # the browser's theme-color must be literal
        self.assertNotRegex(body, r'#[0-9a-fA-F]{3,6}"|rgba?\(\d')
        self.assertNotIn('"#a78bfa"', JS)


if __name__ == "__main__":
    unittest.main()
