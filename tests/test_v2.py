"""v2 Levels (decision 001, phase D, racing-form look): the number model follows the definitions table
(docs/v2-definitions.md), every number has its time or a "missing" text, and /v2/ is served locally and built for the
hosted site beside the main page. Invariants only; no v1 facts.

Fixture: tests/fixtures/v2/all.json, the fields v2 reads from the hosted all.json of 2026-11-23 17:39 UTC
(OCC backup estimate, RTH). Expected numbers were read off that file by hand.
"""
import copy
import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "dashboard" / "v2"
ALL = json.loads((ROOT / "tests" / "fixtures" / "v2" / "all.json").read_text(encoding="utf-8"))
NOW = "2026-11-23T17:43:16Z"                                          # the snapshot's fetch time


def model(all_, market="NQ", now=NOW):
    src = (f"const G = require({json.dumps(str(V2 / 'core.js'))});"
           f"console.log(JSON.stringify(G.levelsModel({json.dumps(all_)}, {json.dumps(market)}, Date.parse({json.dumps(now)}))))")
    return json.loads(subprocess.run(["node", "-e", src], capture_output=True, encoding="utf-8", check=True).stdout)


def age(mins):
    src = f"const G = require({json.dumps(str(V2 / 'core.js'))}); console.log(JSON.stringify({json.dumps(mins)}.map(G.age)))"
    return json.loads(subprocess.run(["node", "-e", src], capture_output=True, encoding="utf-8", check=True).stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class LevelsModel(unittest.TestCase):
    def test_the_five_answers_from_the_snapshot(self):
        m = model(ALL)
        self.assertAlmostEqual(m["price"]["v"], 26855.416335346497)
        self.assertEqual(m["price"]["at"], "2026-11-23T17:39:26+00:00")
        self.assertAlmostEqual(m["zgDistance"]["v"], 26855.416335346497 - 26574.5)
        self.assertEqual(m["zgDistance"]["side"], "above")
        self.assertTrue(m["levels"]["ZG"]["modelled"])
        w = m["nearerWall"]
        self.assertEqual((w["name"], w["v"], w["side"], w["only"]), ("Put wall", 26791.75, "below", False))
        self.assertAlmostEqual(w["d"], 26855.416335346497 - 26791.75)
        self.assertEqual(m["asof"], "2026-11-23T17:39:29.714983+00:00")
        self.assertEqual(m["ageMin"], 4)
        self.assertTrue(m["source"]["backup"])
        p = m["paste"]
        self.assertEqual((p["slot"], p["zg"], p["onHold"], p["next"]), ("2026-11-19 16:30", 27772.5, True, "2026-11-23 13:00"))
        self.assertEqual(age([p["ageMin"]]), ["3 d 20 h"])                 # 19 Nov 21:33 to 23 Nov 17:43, never "4 days"

    def test_a_past_next_attempt_is_not_shown(self):
        self.assertEqual(model(ALL, now="2026-11-23T17:59:59Z")["paste"]["next"], "2026-11-23 13:00")   # 12:59 ET
        self.assertIsNone(model(ALL, now="2026-11-23T18:00:00Z")["paste"]["next"])                     # 13:00 ET, due
        self.assertIsNone(model(ALL, now="2026-11-27T22:00:00Z")["paste"]["next"])

    def test_es_too(self):
        m = model(ALL, "ES")
        self.assertEqual(m["market"], "ES")
        self.assertIn("v", m["price"])
        self.assertIn(m["zgDistance"].get("side"), ("above", "below"))

    def test_the_ladder_runs_high_to_low_with_the_sigma_rows(self):
        m = model(ALL)
        vals = [r["v"] for r in m["ladder"]]
        self.assertEqual(vals, sorted(vals, reverse=True))
        self.assertEqual({r["k"] for r in m["ladder"]}, {"CW", "C1", "Ab1", "ZG", "P1", "PW", "SH", "SL"})
        sh = next(r for r in m["ladder"] if r["k"] == "SH")
        self.assertAlmostEqual(sh["v"], 26855.416335346497 + 339.5216977977253)
        self.assertEqual(m["notCovered"], [])

    def test_every_missing_input_says_why(self):
        def without(fn):
            a = copy.deepcopy(ALL)
            fn(next(w for w in a["workers"] if w["market"] == "NQ"))
            return model(a)
        m = without(lambda w: w["result"]["mapped"].update(zero_gamma=None))
        self.assertEqual(m["levels"]["ZG"]["missing"], "no zero gamma in this reading")
        self.assertEqual(m["zgDistance"]["missing"], "no zero gamma in this reading")
        self.assertIn({"k": "ZG", "name": "Zero gamma", "why": "no zero gamma in this reading"}, m["notCovered"])
        m = without(lambda w: w["result"]["mapped"]["mapping"].update(futures_ref=None))
        for k in ("price", "zgDistance", "nearerWall"):
            self.assertEqual(m[k]["missing"], "no futures quote")
        m = without(lambda w: w["result"].update(mapped=None))
        self.assertIn("missing", m["price"])
        m = without(lambda w: w["result"]["mapped"].update(call_wall=None))
        self.assertTrue(m["nearerWall"]["only"])
        m = without(lambda w: w["result"]["mapped"].update(call_wall=None, put_wall=None))
        self.assertEqual(m["nearerWall"]["missing"], "unavailable: no wall in this reading")
        m = without(lambda w: w["result"]["mapped"].update(expected_move=None))
        self.assertEqual(m["sigma"]["missing"], "1σ move unavailable")
        self.assertNotIn("SH", {r["k"] for r in m["ladder"]})
        m = without(lambda w: w.update(published=None))
        self.assertEqual(m["paste"]["missing"], "No paste published yet")
        m = without(lambda w: w["result"]["session"].update(levels={}))
        self.assertEqual(m["levels"]["C1"]["missing"], "not in this reading")
        self.assertEqual(model({"workers": []})["missing"], "no reading for NQ in this update")

    def test_cboe_data_is_not_called_a_backup(self):
        a = copy.deepcopy(ALL)
        for w in a["workers"]:
            w["result"]["mapped"].update(provider="CBOE", backup=None)
        m = model(a)
        self.assertFalse(m["source"]["backup"])
        self.assertFalse(m["paste"]["onHold"])

    def test_age_words_never_round_up(self):
        self.assertEqual(age([0, 59, 60, 1439, 1440, 5530]), ["0 min", "59 min", "1 h 0 min", "23 h 59 min", "1 d 0 h", "3 d 20 h"])


class Invariants(unittest.TestCase):
    CSS = (V2 / "v2.css").read_text(encoding="utf-8")
    JS = (V2 / "levels.js").read_text(encoding="utf-8")

    def test_level_colours_are_the_pine_ones(self):
        pine = (ROOT / "pine" / "nq_es_gex_levels.pine").read_text(encoding="utf-8")
        found = re.findall(r"^c(ZG|Pos|Neg|AG|EM)\s*=\s*themed\(\w+, (#[0-9a-f]{6}), (#[0-9a-f]{6})\)", pine, re.M)
        themed = {k: (d, l) for k, d, l in found}                          # name: (dark default, light shade)
        css_var = {"ZG": "--flip", "Pos": "--call", "Neg": "--put", "AG": "--abs", "EM": "--em"}
        dark, light = self.CSS.split('[data-theme="light"]', 1)
        for k, (d, l) in themed.items():
            self.assertIn(f"{css_var[k]}:{d}", dark.replace(" ", ""), k)
            self.assertIn(f"{css_var[k]}:{l}", light.replace(" ", ""), k)
        self.assertEqual(len(themed), 5)

    def test_one_highlighter_and_no_colour_beyond_level_marks(self):
        colours = set(re.findall(r"var\(--(call|put|flip|abs|em)\)", self.CSS))
        self.assertEqual(colours, set(), "level colours appear in v2.css only as tokens, never on text rules")
        self.assertNotIn("border-radius:12", self.CSS.replace(" ", ""))                   # no cards
        self.assertNotIn("box-shadow", self.CSS)

    def test_no_layout_jump_the_first_screen_has_its_rows_before_data(self):
        html = (V2 / "index.html").read_text(encoding="utf-8")
        for k in ("Nearer wall", "Regime", "Levels as of", "TradingView paste"):
            self.assertIn(k, html)
        self.assertIn('class="row hero"', html)

    def test_no_horizontal_scroll_rules(self):
        self.assertIn("overflow-x:hidden", self.CSS.replace(" ", ""))
        self.assertIn("minmax(0,", self.CSS)

    def test_no_advice_words_in_page_text(self):
        for w in ("buy", "sell", "should", "target"):
            self.assertNotRegex(self.JS.lower(), rf'["`>][^"`<]*\b{w}\b')


class Served(unittest.TestCase):
    def test_local_server_serves_v2_and_refuses_folders(self):
        from gexpro.server import make_handler
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler([]))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            for path, kind in (("/v2/", "text/html"), ("/v2/core.js", "text/javascript"), ("/v2/v2.css", "text/css")):
                with urllib.request.urlopen(base + path) as r:
                    self.assertTrue(r.headers["Content-Type"].startswith(kind), path)
            with urllib.request.urlopen(base + "/v2") as r:          # redirected, so the relative links resolve
                self.assertEqual(r.url, base + "/v2/")
                self.assertIn('src="core.js"', r.read().decode())
            for bad in ("/v2/../gexpro/server.py", "/v2/%2e%2e/README.md", "/v2/nope.js"):
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(base + bad)
        finally:
            srv.shutdown()

    def test_hosted_build_copies_v2_static_and_versioned(self):
        from gexpro import site
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "site"
            site.build([], out, Path(t) / "state")
            page = (out / "v2" / "index.html").read_text(encoding="utf-8")
            self.assertLess(page.index("window.GEX_STATIC = true"), page.index("core.js"))
            self.assertRegex(page, r'"core\.js\?v=[0-9a-f]{10}"')
            self.assertRegex(page, r'"levels\.js\?v=[0-9a-f]{10}"')
            for f in ("core.js", "levels.js", "v2.css"):
                self.assertTrue((out / "v2" / f).is_file(), f)
            self.assertTrue((out / "sw.js").is_file())                        # the root worker covers /v2/ too
            self.assertFalse((out / "v2" / "sw.js").exists())


if __name__ == "__main__":
    unittest.main()
