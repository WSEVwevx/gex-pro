"""The sentence under the Levels price (2040 redesign, Phase 4): fixed templates, never a banned word, and every number
the same as the key-level tiles show (distance in points and in expected moves, from the same price)."""
import itertools
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
BANNED = ("buy", "sell", "should", "target", "will")


def _src(name):
    head = f"function {name}(o){{"
    return head + JS.split(head, 1)[1].split("\n}\n", 1)[0] + "\n}"


def say(cases):
    num = re.search(r"^const num = .*$", JS, re.M).group(0)
    gamma = "const SAY_GAMMA = " + JS.split("const SAY_GAMMA = ", 1)[1].split(";\n", 1)[0] + ";"
    src = "\n".join([num, gamma, _src("stateSentence"), f"console.log(JSON.stringify({json.dumps(cases)}.map(stateSentence)))"])
    return json.loads(subprocess.run(["node"], input=src, capture_output=True, encoding="utf-8", check=True).stdout)


BASE = {"m": "NQ", "regime": "NEGATIVE", "ref": 25099.91, "zg": None, "zgStatus": "NO CROSSING within +/-5.0% of reference",
        "emd": 1254.4, "cw": 28881.5, "pw": 24770.0}


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Templates(unittest.TestCase):
    def test_no_crossing(self):
        self.assertEqual(say([BASE])[0],
                         "NQ has no zero-gamma crossing within ±5.0% of the price; modeled dealer gamma is negative throughout "
                         "that range, where hedging tends to add to moves. The put wall, 24,770.00, is 330 pts (0.3σ) below; "
                         "the call wall, 28,881.50, is 3,782 pts (3.0σ) above.")

    def test_an_earlier_sessions_reading_is_past_tense_with_its_day(self):
        got = say([dict(BASE, past="Wed, Nov 25"), dict(BASE, zgStatus="", past="Wed, Nov 25")])
        self.assertEqual(got[0], "As of Wed, Nov 25, NQ had no zero-gamma crossing within ±5.0% of the price; modeled dealer "
                                 "gamma was negative throughout that range, where hedging tends to add to moves. The put wall, "
                                 "24,770.00, was 330 pts (0.3σ) below; the call wall, 28,881.50, was 3,782 pts (3.0σ) above.")
        self.assertTrue(got[1].startswith("As of Wed, Nov 25, zero gamma for NQ was unavailable;"), got[1])
        self.assertNotRegex(got[0], r"\b(is|has)\b")

    def test_a_crossing_and_its_side(self):
        below, above = say([{**BASE, "zg": 25510.25, "regime": "NEGATIVE"}, {**BASE, "zg": 24600.0, "regime": "POSITIVE"}])
        self.assertTrue(below.startswith("NQ is 410 pts (0.3σ) below zero gamma (25,510.25); modeled dealer gamma is negative, "
                                         "where hedging tends to add to moves."), below)
        self.assertTrue(above.startswith("NQ is 500 pts (0.4σ) above zero gamma (24,600.00); modeled dealer gamma is positive, "
                                         "where hedging tends to lean against moves."), above)

    def test_on_a_level_reads_at(self):
        s = say([{**BASE, "zg": 25100.2, "pw": 25099.6}])[0]
        self.assertIn("NQ is at zero gamma (25,100.20)", s)
        self.assertIn("The put wall, 25,099.60, is at the price;", s)

    def test_missing_parts_say_unavailable(self):
        a, b, c = say([{**BASE, "zgStatus": "UNAVAILABLE", "regime": "UNAVAILABLE"}, {**BASE, "cw": None, "pw": None},
                       {**BASE, "emd": None}])
        self.assertTrue(a.startswith("Zero gamma for NQ is unavailable; modeled dealer gamma is unavailable."), a)
        self.assertIn("The put wall is unavailable; the call wall is unavailable.", b)
        self.assertIn("is 330 pts below", c)                     # no expected move: no σ, nothing invented
        self.assertNotIn("σ", c)

    def test_an_estimate_reads_like_any_reading(self):
        # the owner's call (27 Nov 2026): the levels are known to be an estimate; the source line names it, not the sentence
        a, b = say([{**BASE, "backup": True}, BASE])
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("NQ has no zero-gamma crossing"), a)

    def test_no_banned_word_in_any_template(self):
        cases = [{**BASE, "m": m, "regime": r, "zg": zg, "zgStatus": st, "cw": cw, "pw": pw, "emd": em}
                 for m, r, (zg, st), cw, pw, em in itertools.product(
                     ("NQ", "ES"), ("POSITIVE", "NEGATIVE", "INDETERMINATE", "UNAVAILABLE", None),
                     ((25500.0, "ESTIMATE"), (24000.0, "ESTIMATE"), (25099.9, "ESTIMATE"), (None, BASE["zgStatus"]), (None, "UNAVAILABLE"), (None, "")),
                     (28881.5, None), (24770.0, None), (1254.4, None))]
        for s in say(cases):
            for w in BANNED:
                self.assertNotRegex(s.lower(), rf"\b{w}\b", s)
            self.assertNotIn("undefined", s)
            self.assertNotIn("NaN", s)

    def test_the_numbers_are_the_tiles_numbers(self):
        # the key-level tiles: num(|v - fut|, 0) + " pts above|below · " + num(|v - fut| / emd, 1) + "σ", fut = ref
        strip = JS.split('$("keyStrip").innerHTML', 1)[0].rsplit("function renderStats", 1)[1]
        self.assertIn('const away = v => v == null ? "" : `${num(Math.abs(v - fut), 0)} pts ${v >= fut ? "above" : "below"}${emd ? ` · ${num(Math.abs(v - fut) / emd, 1)}σ` : ""}`;', strip)
        self.assertIn("const fut = L.futures_equiv_of_ref ?? s.ref_price", strip)
        self.assertIn("const ref = L.futures_equiv_of_ref ?? s.ref_price;", JS)
        self.assertIn('const gap = (v, from = "level") => { const d = Math.abs(v - o.ref), pts = num(d, 0);', JS)
        self.assertIn("num(d / o.emd, 1)}σ)", JS)


class Placement(unittest.TestCase):
    def test_under_the_price_and_escaped(self):
        hero = JS.split("function renderHero(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn('<p class="lvh-say" id="lvSay">${esc(stateSentence({m: market, regime: s.regime, ref, zg: zgp,', hero)
        self.assertIn("emd, cw: lvPrice(L.call_wall), pw: lvPrice(L.put_wall), backup: !!s.backup, past: rOld}))}</p>", hero)


if __name__ == "__main__":
    unittest.main()
