"""Labels that say what a number is (the hosted audit of 2026-11-20): an old paste carries its day, the headline price
is named as the index converted with the basis, a missing level says why, one code means one price, and the heatmap's
latest profile carries its own time."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")


def line(start):
    return next(l for l in JS.splitlines() if l.startswith(start))


def node(src):
    return subprocess.run(["node", "-e", src], capture_output=True, encoding="utf-8", check=True).stdout.strip()


class Paste(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_an_old_paste_shows_its_day_and_todays_does_not(self):
        src = line("const ET =") + "\nconst slotTxt =" + JS.split("const slotTxt =", 1)[1].split("\nconst refAt", 1)[0]
        today = 'new Date().toLocaleDateString("en-CA", ET)'
        out = json.loads(node(src + f'\nconsole.log(JSON.stringify([slotTxt("2026-11-19 16:30"), slotTxt({today} + " 09:45")]))'))
        self.assertEqual(out, ["Thu, Nov 19, 16:30 ET", "09:45 ET"])

    def test_the_button_and_the_indicator_page_use_it(self):
        self.assertIn("`Copy for TradingView · ${slotTxt(ws.find(w=>w.published).published.slot_et)}`", JS)
        self.assertIn("`${slotTxt(pub.published.slot_et)} paste`", JS)
        self.assertNotRegex(JS, r"slot_et\.slice\(11\)\} ET")


class Headline(unittest.TestCase):
    def test_the_price_is_named_as_the_index_converted_not_the_futures_price(self):
        self.assertIn('${w.result.mapped ? "equiv. of " + esc(w.source) : esc(w.source)}', JS)
        self.assertIn("${esc(w.source)} ${num(mp.source_ref, 2)} × basis ${num(mp.factor, 5)}, not the live futures price", JS)
        self.assertNotIn('w.result.mapped ? "futures" : esc(w.source)', JS)
        self.assertIn('<b class="ld-chip now">PX</b><span>${esc(w.market)} ${w.result.mapped ? "equiv. of " + esc(w.source) : "price"}</span>', JS)


class MissingLevels(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_missing_key_level_says_unavailable_and_why(self):
        key = line("  const key = (k, v, color, why) =>").strip()
        src = ('const esc = s => String(s), num = v => String(v), away = v => "near";'
               'const tile = (k, v, sub) => `${k}|${v}|${sub}`;' + key +
               'console.log(JSON.stringify([key("Zero gamma (est.)", null, "", "no crossing near price"), key("Call wall", 28881.5, "")]))')
        self.assertEqual(json.loads(node(src)), ["Zero gamma (est.)|-|unavailable: no crossing near price", "Call wall|28881.5|near"])

    def test_zero_gamma_passes_its_reason(self):
        self.assertIn('key("Zero gamma (est.)", p(L.zero_gamma), "var(--zg)", zgWhy)', JS)
        self.assertIn('/^NO CROSSING/i.test(L.zero_gamma_status || s.zero_gamma_status || "") ? "no crossing near price"', JS)

    def test_the_plan_says_why_ab1_is_missing(self):
        self.assertIn('${lv.Ab1 != null ? p(lv.Ab1) : s.backup ? "not in the backup" : "-"}', JS)

    def test_the_banner_matches_what_the_backup_gives(self):
        self.assertIn("It gives the walls, C1, P1 and zero gamma when price is near a crossing; it has no 0DTE flip and no first-expiry Ab1 or lower ranks.", JS)
        self.assertNotIn("Zero gamma, the walls, C1 and P1 are kept", JS)


class OneCodeOnePrice(unittest.TestCase):
    def test_the_live_tables_ranked_strikes_do_not_reuse_the_indicators_codes(self):
        lad = JS.split("// strikes ranked near price over every expiry", 1)[1].split("const X =", 1)[0]
        self.assertEqual(re.findall(r'"(\+G|−G|AG)" \+ \(i \+ 1\)', lad), ["+G", "−G", "AG"])
        for old in ('"C" + (i + 1), `Call wall', '"P" + (i + 1), `Put wall', '"Ab" + (i + 1), `Abs gamma'):
            self.assertNotIn(old, JS)

    def test_a_wall_on_the_wrong_side_of_price_is_named(self):
        self.assertIn("P1 ${p(P1)} is above the price: the first expiry's most negative-gamma strike is now above it.", JS)
        self.assertIn("C1 ${p(C1)} is below the price: the first expiry's most positive-gamma strike is now below it.", JS)


class Heatmap(unittest.TestCase):
    def test_the_latest_profile_carries_its_own_time(self):
        self.assertNotIn('"GEX now"', JS)
        self.assertIn('ctx.fillText(`GEX ${pt.toLocaleDateString("en-US", {...ET, weekday: "short"})} ${hmFmt.hm.format(pt)}`', JS)

    def test_the_live_table_help_names_its_own_codes(self):
        self.assertIn("+G = the strikes near price with the most positive net GEX, −G = the most negative, AG = the most total gamma", JS)

    def test_the_heatmap_source_names_the_chain(self):
        py = (ROOT / "gexsys" / "heatmap.py").read_text(encoding="utf-8")
        self.assertIn("GEX: saved snapshots (OCC open interest + VIX-family vols, an estimate)", py)


if __name__ == "__main__":
    unittest.main()
