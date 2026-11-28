"""The main site never shows an earlier session's reading as current (rework workstream 2): the session a moment belongs
to comes from marketcal's calendar (the last session that opened at or before it), an older reading names its day and
is told in the past tense, a next paste time already gone is not shown, a settled expiry reads "expired", and the
Data health basis row has one status."""
import json
import shutil
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")


def piece(head):
    return head + JS.split(head, 1)[1].split("\n}\n", 1)[0] + "\n}"


def line(head):
    return head + JS.split(head, 1)[1].split("\n", 1)[0]


def day(d, o, c):
    return {"date": d, "open": o, "close": c}


# Thanksgiving week 2026: Wed a full session, Thu closed, Fri closes at 13:00 ET, Mon 30 Nov a full session
TUE = day("2026-11-24", "2026-11-24T14:30:00Z", "2026-11-24T21:00:00Z")
WED = day("2026-11-25", "2026-11-25T14:30:00Z", "2026-11-25T21:00:00Z")
FRI = day("2026-11-27", "2026-11-27T14:30:00Z", "2026-11-27T18:00:00Z")
MON = day("2026-11-30", "2026-11-30T14:30:00Z", "2026-11-30T21:00:00Z")
CAL = {"past_sessions": [TUE, WED], "sessions": [WED, FRI, MON]}


def old_day(asof, now):
    src = "\n".join(['const ET = {timeZone: "America/New_York"};', f"const data = {{calendar: {json.dumps(CAL)}}};",
                     piece("function sessionOf(ms, cal){"), line("const dayName = "), piece("function oldDay(iso, nowMs = Date.now()){"),
                     f"console.log(JSON.stringify(oldDay({json.dumps(asof)}, Date.parse({json.dumps(now)}))))"])
    return json.loads(subprocess.run(["node"], input=src, capture_output=True, encoding="utf-8", check=True).stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class OldReadings(unittest.TestCase):
    def test_the_last_sessions_close_is_current_until_the_next_open(self):
        self.assertIsNone(old_day("2026-11-25T21:10:00Z", "2026-11-26T15:00:00Z"))        # Thanksgiving: Wed's close is the latest
        self.assertIsNone(old_day("2026-11-25T21:10:00Z", "2026-11-27T13:00:00Z"))        # Fri 08:00 ET, before the open
        self.assertIsNone(old_day("2026-11-27T18:05:00Z", "2026-11-28T15:00:00Z"))        # Saturday: Fri's close
        self.assertIsNone(old_day("2026-11-30T12:00:00Z", "2026-11-30T13:00:00Z"))        # Mon 07:00 reading, Mon 08:00: pre-open

    def test_after_the_next_open_it_names_its_day(self):
        self.assertEqual(old_day("2026-11-25T21:10:00Z", "2026-11-27T14:31:00Z"), "Wed, Nov 25")
        self.assertEqual(old_day("2026-11-27T18:05:00Z", "2026-11-30T15:00:00Z"), "Fri, Nov 27")
        self.assertEqual(old_day("2026-11-24T15:00:00Z", "2026-11-25T15:00:00Z"), "Tue, Nov 24")

    def test_older_than_the_calendar_reaches_is_dated_too(self):
        self.assertEqual(old_day("2026-11-10T15:00:00Z", "2026-11-25T15:00:00Z"), "Tue, Nov 10")

    def test_no_calendar_no_claim(self):
        src = "\n".join(['const ET = {timeZone: "America/New_York"};', "const data = {calendar: {}};",
                         piece("function sessionOf(ms, cal){"), line("const dayName = "), piece("function oldDay(iso, nowMs = Date.now()){"),
                         'console.log(JSON.stringify(oldDay("2026-11-10T15:00:00Z", Date.parse("2026-11-25T15:00:00Z"))))'])
        self.assertIsNone(json.loads(subprocess.run(["node"], input=src, capture_output=True, encoding="utf-8", check=True).stdout))

    def test_no_session_time_is_hard_coded(self):
        for fn in (piece("function sessionOf(ms, cal){"), piece("function oldDay(iso, nowMs = Date.now()){")):
            self.assertNotRegex(fn, r"getHours|13:00|16:00|9:30|14:30|21:00")


class Wiring(unittest.TestCase):
    def test_hero_bias_and_plan_name_an_earlier_session(self):
        self.assertIn('${pOld ? ` <b class="c-warn">from ${esc(pOld)}</b>` : ""}', JS)
        self.assertIn("backup: !!s.backup, past: rOld}", JS)
        self.assertIn("`Bias from ${old}, an earlier session`", JS)
        self.assertIn("old ? `Plan from ${old}`", JS)
        self.assertIn("No plan: no pre-open reading", JS)
        self.assertIn('`<em>price ${old || review ? "was" : "is"} here</em>`', JS)

    def test_an_old_reading_builds_no_present_tense_text(self):
        self.assertIn("P1 ${p(P1)} was above the price: the first expiry's most negative-gamma strike was above it.", JS)
        self.assertIn("C1 ${p(C1)} was below the price: the first expiry's most positive-gamma strike was below it.", JS)
        self.assertIn('tapeText(near ? near.k : "", v, ref, d).replace(" is ", " was ") + ` (the ${was} price)`', JS)
        self.assertIn('${old ? `${esc(market)} · <b class="c-warn">an earlier session</b>`', JS)

    def test_a_past_next_paste_is_not_shown(self):
        self.assertIn('h.next_publish_et && h.next_publish_et > etStampNow()', JS)

    def test_a_settled_expiry_reads_expired(self):
        self.assertIn('expired(e) ? "expired"', JS)
        self.assertIn('Date.parse(/AM/.test(e.tag || "") ? x.open : x.close)', JS)

    def test_level_history_names_missing_sessions(self):
        self.assertIn("Missing: ${gaps.map(", JS)


class Calendar(unittest.TestCase):
    def test_the_export_has_the_sessions_before_today(self):
        from gexsys.component import _calendar
        c = _calendar(datetime(2026, 11, 30, 15, 0, tzinfo=timezone.utc))           # Monday after Thanksgiving
        self.assertEqual([s["date"] for s in c["past_sessions"]][-3:], ["2026-11-24", "2026-11-25", "2026-11-27"])
        self.assertEqual(len(c["past_sessions"]), 10)
        fri = c["past_sessions"][-1]
        self.assertEqual((fri["open"], fri["close"]), ("2026-11-27T14:30:00Z", "2026-11-27T18:00:00Z"))     # the early close


class BasisRow(unittest.TestCase):
    def test_a_measured_basis_is_never_not_checked_yet(self):
        # the hosted build's fresh process has no last_success: the row used it and read "not checked yet" beside a
        # measured time in its own detail line (seen 27 Nov 2026)
        from types import SimpleNamespace
        from gexpro.health import status
        from gexsys.component import GexComponent
        res = {"summary": {"status": "OK"}, "mapped": {"mapping": {"futures_ref_mode": "measured NQ=F/^NDX basis at 09:29 ET",
                                                                    "futures_time": "2026-11-27T14:29:00+00:00"}}}
        w = SimpleNamespace(cfg=SimpleNamespace(market="NQ", source="NDX"), label="OCC", result=res, published={}, failures=0,
                            last_error=None, last_success=None, health=lambda: {"calc_status": "OK"}, store=None, key="NQ-OCC")
        comp = GexComponent.__new__(GexComponent)
        comp.workers = {"NQ-OCC": w}
        comp.heat = SimpleNamespace(status={})
        row = next(r for r in comp.sources() if r["name"] == "NQ futures basis")
        self.assertEqual(row["last_ok"], "2026-11-27T14:29:00+00:00")
        self.assertEqual(status(row, datetime(2026, 11, 27, 15, 0, tzinfo=timezone.utc)), "ok")


if __name__ == "__main__":
    unittest.main()
