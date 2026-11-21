"""The command bar (2040 redesign, Phase 3): Ctrl+K or "/" opens one search box that finds pages, commands, today's
levels and glossary terms, and is usable by keyboard and screen reader."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")


def search(q, pool):
    fn = "function cmdSearch(q, pool){" + JS.split("function cmdSearch(q, pool){", 1)[1].split("\n}\n", 1)[0] + "\n}"
    src = fn + f"\nconsole.log(JSON.stringify(cmdSearch({json.dumps(q)}, {json.dumps(pool)}).map(c => c.code)))"
    return json.loads(subprocess.run(["node", "-e", src], capture_output=True, encoding="utf-8", check=True).stdout)


POOL = [{"code": "LIVE", "desc": "Open Live table"}, {"code": "LVL", "desc": "Open Levels"}, {"code": "NQ", "desc": "Switch to NQ"},
        {"code": "COPY", "desc": "Copy the TradingView paste (NQ + ES)"},
        {"code": "CW", "kind": "Level", "desc": "NQ Call wall 28,881.50 · +3,782 pts from 25,099.91"},
        {"code": "ZG", "kind": "Level", "desc": "NQ Zero gamma: unavailable (Levels says why)"},
        {"code": "Gamma", "kind": "Term", "desc": "How fast an option's delta changes as the price moves."},
        {"code": "Call wall", "kind": "Term", "desc": "The strike with the largest call gamma exposure."}]


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Search(unittest.TestCase):
    def test_empty_shows_the_commands_only(self):
        self.assertEqual(search("", POOL), ["LIVE", "LVL", "NQ", "COPY"])

    def test_an_exact_code_comes_first(self):
        self.assertEqual(search("cw", POOL)[0], "CW")
        self.assertEqual(search("LIVE", POOL)[0], "LIVE")

    def test_a_level_and_its_term_are_both_found_level_first(self):
        self.assertEqual(search("call wall", POOL), ["CW", "Call wall"])

    def test_terms_need_two_letters(self):
        self.assertNotIn("Gamma", search("g", POOL))
        self.assertIn("Gamma", search("gamma", POOL))

    def test_unavailable_levels_are_found_and_say_so(self):
        self.assertEqual(search("zero", POOL), ["ZG"])

    def test_regex_characters_are_plain_text(self):
        self.assertEqual(search("(", POOL), ["COPY", "ZG"])    # "(NQ + ES)" and "(Levels says why)"; nothing throws
        self.assertEqual(search("+", POOL), ["COPY", "CW"])    # equal scores keep the pool's order

    def test_at_most_twelve(self):
        many = [{"code": f"T{i}", "kind": "Term", "desc": "gamma"} for i in range(30)]
        self.assertEqual(len(search("gamma", many)), 12)


class Wiring(unittest.TestCase):
    def test_ctrl_k_and_slash_open_it(self):
        self.assertIn('if((e.key === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing)){ e.preventDefault(); $("cmd").focus(); return; }', JS)

    def test_it_is_a_combobox_for_screen_readers(self):
        tag = re.search(r'<input id="cmd"[^>]*>', HTML).group(0)
        for a in ('role="combobox"', 'aria-expanded="false"', 'aria-controls="cmdList"', 'aria-autocomplete="list"'):
            self.assertIn(a, tag)
        self.assertIn('box.setAttribute("aria-activedescendant", ms.length ? "cmdOpt" + cmdSel : "");', JS)
        self.assertIn('role="option" aria-selected="${i === cmdSel}"', JS)

    def test_levels_use_the_same_prices_as_the_levels_page(self):
        fn = JS.split("function cmdLevels(){", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("const s = r.mapped || r.summary", fn)
        self.assertIn("ref = (r.mapped || {}).futures_equiv_of_ref ?? s.ref_price", fn)
        self.assertIn("unavailable (Levels says why)", fn)

    def test_terms_open_the_glossary_at_that_term(self):
        self.assertIn('const cmdTerms = () => LIB.glossary.map(([t, d]) => ({code: t, kind: "Term", desc: d, run: () => openGlossary(t)}));', JS)


if __name__ == "__main__":
    unittest.main()
