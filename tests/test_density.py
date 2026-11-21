"""Density modes and the day-aware Levels page (2040 redesign, Phase 3): Glance / Work / Study, and the order of the
Levels sections by the trading day's phase, set once at load so nothing jumps."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "assets" / "terminal.css").read_text(encoding="utf-8")
HTML = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")


class Density(unittest.TestCase):
    def test_three_modes_with_a_pressed_state(self):
        seg = re.search(r'<div class="seg dens" id="density"[^>]*>(.*?)</div>', HTML).group(1)
        self.assertEqual(re.findall(r'data-d="(\w+)"', seg), ["glance", "work", "study"])
        self.assertEqual(len(re.findall(r'aria-pressed="(true|false)"', seg)), 3)
        self.assertIn('document.querySelectorAll("#density button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.d === d)));', JS)

    def test_glance_never_hides_a_time_or_a_backup_label(self):
        rule = re.search(r"\.dens-glance #levelsView>:is\(([^)]*)\)\{display:none\}", CSS).group(1).split(",")
        self.assertEqual(rule, [".lv-chg", ".main", ".lv-more"])
        # the banner (backup, stale) sits outside #levelsView; the price and its time, the key levels and the plan stay
        self.assertLess(HTML.index('<div id="banner" data-reserve></div>'), HTML.index('<div id="levelsView">'))
        for keep in ("lv-head", "stats keys", "plan-row"):
            self.assertNotIn("." + keep.split()[0], rule)

    def test_study_opens_the_folds_without_overwriting_the_viewers_choice(self):
        self.assertIn('if(d === "study") ["lvMore", "lvHist"].forEach(openFold);', JS)
        self.assertIn("if(!foldAuto.delete(id)) store.set(", JS)
        self.assertIn("const openFold = id => { if($(id).open) return; foldAuto.add(id); $(id).open = true; };", JS)

    def test_the_choice_survives_a_reload(self):
        self.assertIn('if(save) store.set("gex.density", d);', JS)
        self.assertIn('setDensity(store.get("gex.density", "work"), false);', JS)

    def test_the_command_bar_switches_it(self):
        for code in ("GLANCE", "WORK", "STUDY"):
            self.assertRegex(JS, rf'\{{code: "{code}", desc: "[^"]+", run: \(\) => \{{ setDensity\("{code.lower()}"\); setPage\("levels"\); \}}\}}')

    def test_only_on_levels(self):
        self.assertIn('$("density").hidden = $("phaseLab").hidden = p !== "levels";', JS)


class DayOrder(unittest.TestCase):
    def test_every_phase_the_calendar_gives_has_an_order_or_keeps_the_usual_one(self):
        phases = set(re.findall(r'"(before the open|cash session|after the close|no cash session today|session times unavailable)"',
                                JS.split("function sessionPhase(d, cal){", 1)[1].split("\n}\n", 1)[0]))
        lead = JS.split("const LV_LEAD = ", 1)[1].split(";\n", 1)[0]
        label = JS.split("const LV_PHASE = ", 1)[1].split(";\n", 1)[0]
        self.assertEqual(set(re.findall(r'"([a-z ]+)": \[', lead)), {"before the open", "after the close", "no cash session today"})
        for p in phases - {"session times unavailable"}:
            self.assertIn(f'"{p}":', label)

    def test_the_lead_sections_exist(self):
        for pid in ("lvHead", "planRow", "lvHist", "keyStrip"):
            self.assertRegex(HTML, rf'id="{pid}"')

    def test_set_once_at_load_from_the_saved_calendar(self):
        self.assertEqual(len(re.findall(r"\borderLevels\(", JS)), 2)        # the definition and the one call at load
        self.assertIn("orderLevels(cal0 ? sessionPhase(new Date(), cal0).phase : null);", JS)
        self.assertIn('store.set("gex.cal", JSON.stringify({sessions: data.calendar.sessions}))', JS)

    def test_the_order_comes_from_the_calendar_not_the_clock(self):
        fn = JS.split("function orderLevels(phase){", 1)[1].split("\n}\n", 1)[0]
        self.assertNotRegex(fn, r"getHours|getDay|570|960")


if __name__ == "__main__":
    unittest.main()
