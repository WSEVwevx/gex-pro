"""Two expirations can share a date: the AM-settled monthly (SPX, NDX) and the PM-settled root (SPXW, NDXP).
The final audit (2026-11-21) found the Live table's tooltips listing 2026-12-18 twice with nothing to tell them apart."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ExpiryNames(unittest.TestCase):
    def settle(self, tags):
        line = next(l for l in JS.splitlines() if l.startswith("const ldSettle = "))
        src = line + f"\nconsole.log(JSON.stringify({json.dumps(tags)}.map(ldSettle)))"
        return json.loads(subprocess.run(["node"], input=src, capture_output=True, encoding="utf-8", check=True).stdout)

    def test_the_tags_from_the_ladder(self):
        # gexsys/ladder.py: tag = ("M" if monthly) + (" AM" if AM-settled)
        self.assertEqual(self.settle(["M AM", "M", "", None]),
                         [", AM-settled monthly (settles on the opening prints)", ", PM-settled (settles on the close)", "", ""])

    def test_the_tooltip_uses_it(self):
        self.assertIn('e.date + ldSettle(e.tag))}: net GEX', JS)


if __name__ == "__main__":
    unittest.main()
