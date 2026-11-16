"""The site's motion and loading system (dashboard/assets/terminal.css, app.js, index.html): one set of durations and
curves, no endless animation, a shape wherever something is loading, and failures that say what happens next."""
import re
import unittest
from pathlib import Path

DASH = Path(__file__).resolve().parent.parent / "dashboard"
CSS = (DASH / "assets" / "terminal.css").read_text(encoding="utf-8")
JS = (DASH / "assets" / "app.js").read_text(encoding="utf-8")
HTML = (DASH / "index.html").read_text(encoding="utf-8")
TICKER = "animation:mq var(--mq-dur,80s) linear infinite"      # the one exception: the scrolling ticker is content, not an effect


class TestMotionTokens(unittest.TestCase):
    def test_three_durations_two_curves_nothing_over_300ms(self):
        root = CSS.split(":root{", 1)[1].split("}", 1)[0]
        got = dict(re.findall(r"--(t-\w+|ease[\w-]*):([^;]+);", root))
        self.assertEqual(sorted(got), ["ease", "ease-out", "t-fast", "t-slow", "t-std"])
        for k in ("t-fast", "t-std", "t-slow"):
            self.assertLessEqual(int(got[k].replace("ms", "")), 300, k)

    def test_every_transition_and_animation_uses_the_tokens(self):
        for decl in re.findall(r"(?:transition|animation):[^;}]*", CSS):
            if decl in (TICKER, "animation:none"):
                continue
            self.assertNotRegex(decl, r"(?<![\w-])\d*\.?\d+m?s\b", f"a duration outside the tokens: {decl}")
            self.assertIn("var(--t-", decl, decl)
            self.assertRegex(decl, r"var\(--ease(-out)?\)", f"a curve outside the tokens: {decl}")

    def test_nothing_loops_but_the_ticker(self):
        self.assertEqual(CSS.count("infinite"), 1)
        self.assertIn(TICKER, CSS)
        self.assertEqual(sorted(re.findall(r"@keyframes ([\w-]+)", CSS)), ["fade-in", "moved", "mq", "rp-flash"])

    def test_reduced_motion_is_one_switch(self):
        self.assertIn("@media(prefers-reduced-motion:reduce){:root{--t-fast:0ms; --t-std:0ms; --t-slow:0ms}}", CSS)
        self.assertIn('matchMedia("(prefers-reduced-motion: reduce)")', JS)
        self.assertIn("const calm = REDUCED || document.hidden;", JS)             # nor in a background tab: no queued burst
        self.assertNotIn('behavior: "smooth"', JS)                                 # scrolling has no token, so it is instant

    def test_script_sets_no_durations_of_its_own(self):
        self.assertNotRegex(JS, r"\.style\.(transition|animation)\s*=")
        self.assertNotRegex(JS, r"transition\s*:\s*[^;\"'`]*\d+m?s")


class TestLoadingAndStates(unittest.TestCase):
    def test_loading_is_always_a_shape(self):
        # the word "Loading" survives only inside a skeleton (for screen readers); nothing shows it as plain text
        for name, src in (("index.html", HTML), ("app.js", JS)):
            for m in re.finditer(r"Loading", src):
                before = src[max(0, m.start() - 60):m.start()]
                self.assertRegex(before, r'class="skeleton[^"]*"[^>]*>$', f"{name}: plain loading text near ...{before[-40:]!r}")
        self.assertIn(".skeleton{font-size:0;color:transparent", CSS)

    def test_every_data_card_starts_as_a_skeleton(self):
        for card in ("regimeCard", "priceCard", "netCard", "planCard", "biasCard", "drvSum", "trkKpis"):
            self.assertRegex(HTML, rf'id="{card}">(?:<div class="eyebrow">[^<]*</div>)?<div class="skeleton"', card)

    def test_cards_keep_their_height_between_visits(self):
        for piece in ("function reserve()", "c.style.minHeight = h ? h + \"px\" : \"\"", "function settle()", "store.set(HKEY, JSON.stringify(cardH))"):
            self.assertIn(piece, JS)

    def test_a_first_visit_reserves_the_usual_heights(self):
        m = re.search(r"const DEFAULT_H = \{wide: (\{.*?\}),\s+narrow: (\{.*?\})\};", JS, re.S)
        self.assertIsNotNone(m)
        views = set(re.findall(r'<div id="(\w+View)"', HTML))
        for block in m.groups():
            got = dict(re.findall(r"(\w+View):\[([\d,]+)\]", block))
            self.assertEqual(set(got), views, "a page has no default heights")
            self.assertTrue(all(h.replace(',', '').isdigit() for h in got.values()))

    def test_empty_states_say_what_is_missing_and_when(self):
        self.assertGreaterEqual(JS.count('stateHtml("empty"'), 8)
        for vague in ('>No data.<', '>No data yet.<', '>No sessions yet.<', '>Nothing graded yet.<', "Not available right now (needs"):
            self.assertNotIn(vague, JS)

    def test_a_failure_says_what_is_shown_and_what_happens_next(self):
        self.assertNotRegex(JS, r"(?<![\w.])OFFLINE(?!\w)")
        self.assertIn("Showing the ${lastGood()} ET numbers.", JS)
        self.assertIn("Retrying by itself.", JS)
        self.assertNotIn('"Data error: "', JS)                                    # no raw error text on the page
        self.assertIn('document.body.classList.toggle("stale-data", !!lag);', JS)  # old data is marked on each market card
        self.assertIn("body.stale-data", CSS)
        self.assertIn(".state.err i{background:var(--bad)}", CSS)

    def test_a_real_move_follows_the_replay_rule(self):
        self.assertIn("Math.abs(now - was) >= 0.001 * Math.abs(was)", JS)         # zero gamma: 0.1%, as gexsys/timeline.py MOVE_ZG
        from gexsys import timeline
        self.assertEqual(timeline.MOVE_ZG, 0.001)


class TestBiasPage(unittest.TestCase):
    def test_the_gauge_flips_where_the_model_flips(self):
        src = (DASH.parent / "gexsys" / "bias.py").read_text(encoding="utf-8")
        self.assertIn('"Bullish" if score >= 0.75 else "Bearish" if score <= -0.75', src)
        self.assertIn("const BIAS_FLIP = 0.75, GAUGE_MAX = 2;", JS)
        for piece in ("at(-BIAS_FLIP)", "at(BIAS_FLIP)", "at(b.score)"):
            self.assertIn(piece, JS)

    def test_one_verdict_card_and_nothing_said_twice(self):
        view = HTML.split('<div id="biasView"', 1)[1].split("<!--", 1)[0]
        self.assertEqual(view.count('class="card'), 4)                     # verdict, chart, factors, positioning
        self.assertNotIn("b.summary", JS)                                  # the sentence that repeated the cards
        self.assertIn('$("biasSummary").textContent = "";', JS)
        self.assertIn("#biasSummary:empty{display:none}", CSS)

    def test_levels_on_the_page_are_whole_points(self):
        body = JS.split("function renderBias(w){", 1)[1].split("function drawReplay", 1)[0]
        self.assertNotRegex(body, r"num\((b\.target|b\.range\[\d\]|ref|p\[1\])\)")
        self.assertIn("const whole = t =>", JS)

    def test_factors_are_bars_that_add_up_to_the_score(self):
        for piece in ('class="fx-bar"', 'f.name === "Gamma side"', "The leans added up.", 'class="fx fx-sum"'):
            self.assertIn(piece, JS)

    def test_a_gap_in_the_replay_is_not_an_alarm(self):
        self.assertNotRegex(CSS, r"\.rp-marks s\{[^}]*(gradient|warn)")
        self.assertNotIn("no update since", JS)


if __name__ == "__main__":
    unittest.main()
