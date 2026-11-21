"""Net DEX is a model, and the page says so (2026-11-21): the verifier matched ES +$2,902B to the dollar, but about
$2,150B of it is matched SPX call/put pairs (box spreads) that the "dealers long calls, short puts" convention counts
as a full long delta. The number stays (the engine is unchanged); its label and help say what it is."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
LIB = (ROOT / "dashboard" / "assets" / "library.js").read_text(encoding="utf-8")


class NetDexLabel(unittest.TestCase):
    def test_the_card_says_modelled(self):
        self.assertIn("<span>modelled dealer delta, $</span>", JS)
        self.assertNotIn("<span>dealer delta, $</span>", JS)

    def test_both_help_entries_carry_the_caveat(self):
        self.assertEqual(JS.count("<p>Net DEX: It is a model, not a measurement: it assumes dealers are long every call and short every put"), 2)
        self.assertIn("box spreads", JS)

    def test_the_glossary_says_modelled(self):
        self.assertIn("On this site it is modelled (dealers long every call, short every put)", LIB)


if __name__ == "__main__":
    unittest.main()
