"""Every state of the Levels page (2040 redesign, Phase 4): a backup estimate on its own plate in words, ageing data
quieter but readable with its time, and the calendar's early closes and futures roll weeks named from marketcal."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "assets" / "terminal.css").read_text(encoding="utf-8")


def piece(head):
    return head + JS.split(head, 1)[1].split("\n}\n", 1)[0] + "\n}"


def notes(now_utc, sessions):
    src = "\n".join(['const ET = {timeZone: "America/New_York"};', "const etDay = d => d.toLocaleDateString(\"en-CA\", ET);", piece("function sessionPhase(d, cal){"),
                     piece("function calNotes(d, cal){"),
                     f"console.log(JSON.stringify(calNotes(new Date({json.dumps(now_utc)}), {json.dumps({'sessions': sessions})})))"])
    return json.loads(subprocess.run(["node"], input=src, capture_output=True, encoding="utf-8", check=True).stdout)


def day(date, open_, close, early=False, roll=False):
    return {"date": date, "open": open_, "close": close, "early": early, "roll_week": roll}


# the day after Thanksgiving 2026 closes at 13:00 ET; the December roll week starts 8 days before the 18 Dec expiry
WED = day("2026-11-25", "2026-11-25T14:30:00Z", "2026-11-25T21:00:00Z")
FRI = day("2026-11-27", "2026-11-27T14:30:00Z", "2026-11-27T18:00:00Z", early=True)
ROLL = day("2026-12-10", "2026-12-10T14:30:00Z", "2026-12-10T21:00:00Z", roll=True)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class CalendarNotes(unittest.TestCase):
    def test_an_early_close_today_names_its_time(self):
        self.assertEqual(notes("2026-11-27T13:00:00Z", [WED, FRI]), ["Early close today, 1:00 PM ET"])

    def test_on_a_holiday_the_next_sessions_early_close(self):
        self.assertEqual(notes("2026-11-26T15:00:00Z", [WED, FRI]), ["Next session closes early, 1:00 PM ET"])

    def test_the_roll_week(self):
        self.assertEqual(notes("2026-12-10T15:00:00Z", [ROLL]), ["Futures roll week: levels use the frozen 9:30 basis"])

    def test_an_ordinary_day_and_no_calendar_say_nothing(self):
        self.assertEqual(notes("2026-11-25T15:00:00Z", [WED, FRI]), [])
        self.assertEqual(notes("2026-11-25T15:00:00Z", []), [])

    def test_the_times_come_from_the_calendar_not_the_clock(self):
        fn = piece("function calNotes(d, cal){")
        self.assertNotRegex(fn, r"getHours|13:00|16:00|9:30 ET|570|960")


class Wiring(unittest.TestCase):
    def test_the_label_is_rebuilt_on_every_render(self):
        self.assertIn('$("phaseLab").textContent = [phaseBase, ...calNotes(new Date(), data.calendar)].filter(Boolean).join(" · ");', JS)
        self.assertIn('$("phaseLab").textContent = phaseBase = LV_PHASE[phase] || "";', JS)

    def test_a_backup_estimate_is_its_own_material_and_says_so(self):
        self.assertIn('<div class="banner backup"><b>Backup estimate.</b>', JS)
        self.assertIn('document.body.classList.toggle("backup-data", !!(s && s.backup));', JS)
        rule = re.search(r"\.banner\.backup,body\.backup-data \.lvh-say\{([^}]*)\}", CSS).group(1)
        for tok in ("var(--backup-hatch)", "var(--backup-bg)", "color:var(--backup-ink)"):
            self.assertIn(tok, rule)
        self.assertIn('(o.backup ? "Backup estimate: " : "")', JS)                   # the sentence says it in words too

    def test_ageing_data_quiets_but_keeps_its_time(self):
        self.assertIn("body.stale-data :is(.lvh-big,.lvh-say,.lvh-mid,#keyStrip .v){color:var(--ink3)}", CSS)
        self.assertIn("body.stale-data #lvHead .lvh-px .eyebrow::after{content:var(--stale-text)", CSS)


if __name__ == "__main__":
    unittest.main()
