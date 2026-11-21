"""The session-calendar export (2040 redesign, Phase 3): the build writes the cash sessions and every futures-session
change from gexsys/marketcal.py into data.calendar, and the page reads its clock and the plan's phase from there
instead of hard-coding 09:30, 16:00 and weekends (CLAUDE.md, "Time, calendar, prices")."""
import json
import shutil
import subprocess
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from gexsys import marketcal as mc
from gexsys.component import _calendar

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
U = timezone.utc
NOW = datetime(2026, 11, 21, 4, 12, tzinfo=U)            # Fri 20 Nov, 23:12 ET: after the close, before a weekend


class Export(unittest.TestCase):
    def setUp(self):
        self.c = _calendar(NOW)

    def test_sessions_in_utc_from_the_day_before(self):
        s = self.c["sessions"]
        self.assertEqual([x["date"] for x in s], ["2026-11-19", "2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25",
                                                  "2026-11-27", "2026-11-30", "2026-12-01"])      # no weekend, no Thanksgiving
        self.assertEqual((s[1]["open"], s[1]["close"]), ("2026-11-20T14:30:00Z", "2026-11-20T21:00:00Z"))

    def test_the_early_close_is_13_00_et(self):
        fri = next(x for x in self.c["sessions"] if x["date"] == "2026-11-27")
        self.assertEqual((fri["close"], fri["early"]), ("2026-11-27T18:00:00Z", True))

    def test_dst_moves_the_utc_times(self):
        s = _calendar(datetime(2026, 7, 1, 12, tzinfo=U))["sessions"]
        self.assertEqual(next(x for x in s if x["date"] == "2026-07-01")["open"], "2026-07-01T13:30:00Z")

    def test_roll_week_is_flagged(self):
        s = _calendar(datetime(2026, 12, 10, 12, tzinfo=U))["sessions"]       # roll Thu 10 Dec .. expiry Fri 18 Dec
        flags = {x["date"]: x["roll_week"] for x in s}
        self.assertFalse(flags["2026-12-09"])
        self.assertTrue(flags["2026-12-10"])
        self.assertTrue(flags["2026-12-18"])
        self.assertEqual(mc.roll_week(date(2026, 12, 18)), True)

    def test_states_are_every_change_of_marketcal(self):
        st = self.c["states"]
        self.assertEqual(st[0], ["2026-11-20T04:12:00Z", "ETH"])
        for t, s in st:
            self.assertEqual(mc.session_state(datetime.fromisoformat(t.replace("Z", "+00:00"))), s, t)
        self.assertIn(["2026-11-26T18:00:00Z", "HOLIDAY"], st)            # Thanksgiving Globex halts at 13:00 ET
        self.assertIn(["2026-11-27T18:15:00Z", "CLOSED"], st)             # the early close halts futures at 13:15 ET
        self.assertGreaterEqual(datetime.fromisoformat(st[-1][0].replace("Z", "+00:00")), datetime(2026, 11, 27, tzinfo=U))

    def test_it_stays_small(self):
        self.assertLess(len(json.dumps(self.c)), 6000)


def node(src):
    return subprocess.run(["node", "-e", src], capture_output=True, encoding="utf-8", check=True).stdout.strip()


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Page(unittest.TestCase):
    def run_js(self, cases):
        head = next(l for l in JS.splitlines() if l.startswith("const ET ="))
        body = JS.split("// ---------- clock and session state (New York)", 1)[1].split("\nfunction sessionLabel(d){", 1)[0]
        lab = "function sessionLabel(d){" + JS.split("\nfunction sessionLabel(d){", 1)[1].split("\n}\n", 1)[0] + "\n}"
        src = (head + body + lab + f"\nconst data = {{calendar: {json.dumps(_calendar(NOW))}}};"
               + f"\nconsole.log(JSON.stringify({json.dumps(cases)}.map(t => [sessionPhase(new Date(t), data.calendar).phase, sessionLabel(new Date(t))[0]])))")
        return json.loads(node(src))

    def test_phases_and_labels_follow_the_export(self):
        got = self.run_js(["2026-11-20T14:29:00Z", "2026-11-20T14:30:00Z", "2026-11-20T20:59:00Z", "2026-11-20T21:00:00Z",
                           "2026-11-21T15:00:00Z", "2026-11-22T23:30:00Z", "2026-11-23T08:00:00Z", "2026-11-23T22:30:00Z",
                           "2026-11-26T15:00:00Z", "2026-11-26T19:00:00Z", "2026-11-27T17:59:00Z", "2026-11-27T18:00:00Z",
                           "2026-11-27T18:20:00Z", "2026-11-26T23:30:00Z"])
        self.assertEqual(got, [
            ["before the open", "Globex · Europe"], ["cash session", "US cash open"], ["cash session", "US cash open"],
            ["after the close", "Globex · Asia"],
            ["no cash session today", "Futures closed"],          # Saturday
            ["no cash session today", "Globex · Asia"],           # Sunday 18:30 ET: Globex has reopened
            ["before the open", "Globex · Asia"],                 # Monday 03:00 ET: Europe starts at 04:00
            ["after the close", "Daily break"],                   # Monday 17:30 ET
            ["no cash session today", "Globex · holiday session"],  # Thanksgiving 10:00 ET
            ["no cash session today", "Market holiday"],          # Thanksgiving 14:00 ET
            ["cash session", "US cash open"], ["after the close", "Globex · Asia"],   # the 13:00 early close
            ["after the close", "Futures closed"],                # 13:20 ET, futures halted at 13:15
            ["no cash session today", "Globex · Asia"]])          # Thanksgiving 18:30 ET: reopened for Friday

    def test_without_the_export_the_page_says_so(self):
        head = next(l for l in JS.splitlines() if l.startswith("const ET ="))
        body = JS.split("// ---------- clock and session state (New York)", 1)[1].split("\nfunction sessionLabel(d){", 1)[0]
        lab = "function sessionLabel(d){" + JS.split("\nfunction sessionLabel(d){", 1)[1].split("\n}\n", 1)[0] + "\n}"
        out = json.loads(node(head + body + lab + "\nconst data = {calendar: {}};console.log(JSON.stringify([sessionPhase(new Date(), {}).phase, sessionLabel(new Date())[0]]))"))
        self.assertEqual(out, ["session times unavailable", "Session unknown"])

    def test_no_hard_coded_session_minutes(self):
        self.assertNotIn("mins < 570", JS)
        self.assertNotIn("m >= 570", JS)
        self.assertIn("const now = new Date(), phase = sessionPhase(now, data && data.calendar).phase;", JS)

    def test_the_plan_still_has_its_clock(self):
        # the plan dates itself and filters today's news with `now`: removing the old clock line must keep it defined
        plan = JS.split("function renderPlan(w){", 1)[1].split(chr(10) + "}" + chr(10), 1)[0]
        first_use = plan.index("now.")
        self.assertLess(plan.index("const now = new Date()"), first_use)


if __name__ == "__main__":
    unittest.main()
