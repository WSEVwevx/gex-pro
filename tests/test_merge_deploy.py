"""tools/merge_deploy.py (decision 001, C4): the quiet window, the next lane and the built commit. No gh calls."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import merge_deploy as md  # noqa: E402
from gexsys.marketcal import NY  # noqa: E402


def et(s):
    return datetime.fromisoformat(s).replace(tzinfo=NY).astimezone(timezone.utc)


class QuietWindow(unittest.TestCase):
    def test_a_normal_session(self):
        self.assertFalse(md.in_quiet_window(et("2026-11-23T08:29")))
        self.assertTrue(md.in_quiet_window(et("2026-11-23T08:30")))
        self.assertTrue(md.in_quiet_window(et("2026-11-23T16:14")))
        self.assertFalse(md.in_quiet_window(et("2026-11-23T16:15")))   # 15 min after the close

    def test_an_early_close_ends_earlier(self):
        # Fri 27 Nov 2026, the day after Thanksgiving: the cash close is 13:00
        self.assertTrue(md.in_quiet_window(et("2026-11-27T13:14")))
        self.assertFalse(md.in_quiet_window(et("2026-11-27T13:15")))

    def test_no_window_on_closed_days(self):
        self.assertFalse(md.in_quiet_window(et("2026-11-26T11:00")))   # Thanksgiving
        self.assertFalse(md.in_quiet_window(et("2026-11-28T11:00")))   # Saturday


class Lanes(unittest.TestCase):
    def test_next_lane_is_the_highest_plus_one(self):
        self.assertEqual(md.next_lane(["Website", "Website (lane 85)", "Website (lane 87)", "Website (lane 9)"]), 88)

    def test_no_lanes_yet(self):
        self.assertEqual(md.next_lane(["Website", ""]), 3)              # the workflow's default group is lane 2


class BuiltCommit(unittest.TestCase):
    def test_reads_the_building_line(self):
        log = "2026-11-24T00:35:19.1239306Z building 95b587c\n2026-11-24T00:35:20Z done"
        self.assertEqual(md.built_sha(log), "95b587c")

    def test_missing_line(self):
        self.assertIsNone(md.built_sha("rebuilding nothing\n"))


if __name__ == "__main__":
    unittest.main()
