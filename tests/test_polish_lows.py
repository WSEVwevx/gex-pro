"""Phase 6 lows from the 2026-11-21 sweep: no "Today's" on a day without a session, thousands separators on the
Heatmap price axis, and the Screener chart says when its price is from."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")


def piece(head):
    return head + JS.split(head, 1)[1].split("\n}\n", 1)[0] + "\n}"


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class BiasDay(unittest.TestCase):
    def label(self, now_utc, sessions):
        line = next(l for l in JS.splitlines() if l.startswith("const biasDay = "))
        src = "\n".join(['const ET = {timeZone: "America/New_York"};', 'const etDay = d => d.toLocaleDateString("en-CA", ET);',
                         piece("function sessionPhase(d, cal){"), f"const data = {{calendar: {{sessions: {json.dumps(sessions)}}}}};",
                         "const _D = Date; Date = class extends _D { constructor(...a){ super(...(a.length ? a : [" + json.dumps(now_utc) + "])); } };",
                         line, "console.log(JSON.stringify(biasDay()))"])
        return json.loads(subprocess.run(["node"], input=src, capture_output=True, encoding="utf-8", check=True).stdout)

    MON = {"date": "2026-11-23", "open": "2026-11-23T14:30:00Z", "close": "2026-11-23T21:00:00Z"}

    def test_a_saturday_says_latest(self):
        self.assertEqual(self.label("2026-11-21T15:00:00Z", [self.MON]), "Latest bias, no session today")

    def test_a_session_day_says_today(self):
        self.assertEqual(self.label("2026-11-23T15:00:00Z", [self.MON]), "Today's bias")

    def test_after_the_close_says_latest(self):
        # hosted sweep 2026-11-27 23:28 ET: "Today's bias" above a card that said "Plan for the Monday, Nov 30 session"
        self.assertEqual(self.label("2026-11-23T23:00:00Z", [self.MON]), "Latest bias, after the close")

    def test_no_card_title_hard_codes_today(self):
        self.assertNotIn('<div class="eyebrow">Today\'s bias', JS)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Parses(unittest.TestCase):
    def test_every_script_parses(self):
        # 2026-11-21: a second "const day" in renderBias was a SyntaxError that blanked the whole site; the other tests
        # run pieces of app.js and could not see it
        for f in ("app.js", "library.js"):
            r = subprocess.run(["node", "--check", str(ROOT / "dashboard" / "assets" / f)], capture_output=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)


class Charts(unittest.TestCase):
    def test_the_heatmap_axis_groups_thousands(self):
        self.assertIn('priceFormatter: p => num(p, 2)}', JS)

    def test_the_stock_chart_has_an_as_of_time(self):
        fn = piece("function renderStockChart(c){")
        self.assertIn('$("scInfo").insertAdjacentHTML("beforeend", `<span class="dim">as of ', fn)
        self.assertLess(fn.index("as of "), fn.index("if(!scChart){"))      # after the empty-bars return, before drawing
        self.assertIn('tDay + ", " + etTime(tl) + " ET"', fn)                 # with its day: on a Saturday it is Friday's
        self.assertNotIn('"Today · 5m"', fn)


class Sweep2(unittest.TestCase):
    def test_heatmap_day_marks_name_the_utc_date(self):
        # 2026-11-21 sweep: the marks are UTC midnights (evening before in ET), so an ET date read one day early
        self.assertIn('day: new Intl.DateTimeFormat("en-US", {timeZone: "UTC", month: "short", day: "numeric"}),', JS)

    def test_the_heatmap_reframes_after_a_resize(self):
        self.assertIn("if(w >= 100 && Math.abs(w - hmW) > 40){ hmW = w; clearTimeout(hmRT); hmRT = setTimeout(() => { hmReset = true; renderHeatmap(); }, 200); }", JS)

    def test_the_first_view_keeps_its_span(self):
        # the first load showed the library's default zoom (~155 bars) instead of "2 days"
        self.assertIn("requestAnimationFrame(() => requestAnimationFrame(() => hmChart.timeScale().setVisibleLogicalRange({from, to: n + ro2})));", JS)

    def test_backup_volume_is_unavailable_not_zero(self):
        self.assertIn('${s.backup ? "no volume (OCC open interest only)" : `volume calls', JS)


if __name__ == "__main__":
    unittest.main()
