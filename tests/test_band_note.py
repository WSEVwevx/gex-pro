"""Decision 001, C1: the page says when price sits outside the prior-close band (engine expected_move.spot_sigma).

On 2026-11-23 17:39 UTC NQ was +1.99 band widths above the prior-close band after a +7% day, and the page said
nothing. The note shows only past 1 band width, says the side by its sign, and never invents a figure.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
BANNED = ("buy", "sell", "should", "target", "will")


def notes(cases):
    lines = [re.search(r"^const %s = .*$" % n, JS, re.M).group(0) for n in ("num", "signed", "bandNote")]
    src = "\n".join(lines + [f"console.log(JSON.stringify({json.dumps(cases)}.map(bandNote)))"])
    return json.loads(subprocess.run(["node"], input=src, capture_output=True, encoding="utf-8", check=True).stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class BandNote(unittest.TestCase):
    def test_outside_above_and_below(self):
        up, down = notes([{"spot_sigma": 1.99}, {"spot_sigma": -1.79}])
        self.assertEqual(up, "price +2.0σ, outside the band")
        self.assertEqual(down, "price -1.8σ, outside the band")

    def test_silent_inside_or_unknown(self):
        self.assertEqual(notes([{"spot_sigma": 0.99}, {"spot_sigma": -1.0}, {}, None, {"spot_sigma": None}]), [""] * 5)

    def test_no_banned_words(self):
        for s in notes([{"spot_sigma": 3.2}, {"spot_sigma": -2.5}]):
            for w in BANNED:
                self.assertNotRegex(s.lower(), r"\b%s\b" % w)


class BandNoteIsShown(unittest.TestCase):
    def test_both_places_that_show_the_band_use_it(self):
        self.assertEqual(len(re.findall(r"bandNote\(em\) \? \" · \" \+ bandNote\(em\)", JS)), 2)   # key strip and plan


if __name__ == "__main__":
    unittest.main()
