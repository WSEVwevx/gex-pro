"""A frozen brief names its graded session "Yesterday" only when it is the session right before the brief's.

Hosted sweep, 28 Nov 2026: the NY AM briefs of Nov 23-27 were frozen before briefs carried a gap flag, so they kept
"Yesterday, graded" for Fri Nov 20. The page now also judges it from the build's calendar."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")


def piece(head):
    return head + JS.split(head, 1)[1].split("\n}\n", 1)[0] + "\n}"


CAL = {"past_sessions": [{"date": d} for d in ("2026-11-19", "2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25")],
       "sessions": [{"date": "2026-11-27"}, {"date": "2026-11-30"}]}


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class GapLabel(unittest.TestCase):
    def gap(self, y, session, cal=CAL):
        src = "\n".join([f"const data = {{calendar: {json.dumps(cal)}}};", piece("function prevSession(d){"),
                         piece("function yGap(y, session){"), f"console.log(JSON.stringify(yGap({json.dumps(y)}, {json.dumps(session)})))"])
        return json.loads(subprocess.run(["node"], input=src, capture_output=True, encoding="utf-8", check=True).stdout)

    def test_a_week_old_grade_in_a_frozen_brief(self):
        self.assertTrue(self.gap({"session": "2026-11-20"}, "2026-11-27"))      # Nov 25 came between (Thanksgiving skipped)

    def test_the_session_before_is_yesterday(self):
        self.assertFalse(self.gap({"session": "2026-11-25"}, "2026-11-27"))     # the day after Thanksgiving
        self.assertFalse(self.gap({"session": "2026-11-20"}, "2026-11-23"))     # Monday after Friday

    def test_the_briefs_own_flag_wins_and_an_unknown_calendar_says_nothing(self):
        self.assertTrue(self.gap({"session": "2026-11-25", "gap": True}, "2026-11-27"))
        self.assertFalse(self.gap({"session": "2026-11-02"}, "2026-11-10", cal={"past_sessions": [], "sessions": []}))
        self.assertFalse(self.gap(None, "2026-11-27"))

    def test_the_label_uses_it(self):
        self.assertIn('yGap(m.yesterday, session) ? "Last session, graded"', JS)
        self.assertIn("briefMarket2(m, ((brief.score || {}).grades || {})[bid], b.kind, b.session)", JS)


if __name__ == "__main__":
    unittest.main()
