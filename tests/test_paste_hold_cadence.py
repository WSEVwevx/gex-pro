"""The Indicator page's paste card says the paste is on hold while the levels are the OCC estimate (sweep, 28 Nov 2026:
it read "A new paste every 30 minutes" beside a Nov 19 paste)."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Cadence(unittest.TestCase):
    def test_the_card_text_follows_the_hold(self):
        js = (ROOT / "dashboard/assets/app.js").read_text(encoding="utf-8")
        html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
        self.assertIn('id="indCadence"', html)
        self.assertIn('$("indCadence").textContent = held ? "On hold while the levels are an OCC estimate', js)
        self.assertIn("w.result.summary.backup", js)


if __name__ == "__main__":
    unittest.main()
