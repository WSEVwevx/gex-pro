"""The site watchdog's decisions (tools/watchdog.py), including a stuck run like the one of 2026-11-09."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import watchdog as W  # noqa: E402

TUE = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)          # 10:00 ET, futures trading
SAT = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)          # futures closed
ago = lambda m, now=TUE: (now - timedelta(minutes=m)).isoformat().replace("+00:00", "Z")


def run(i, status, created_min, event="workflow_dispatch", title="Website", started_min=None):
    return {"id": i, "status": status, "created_at": ago(created_min), "event": event, "display_title": title,
            "run_started_at": ago(started_min if started_min is not None else created_min)}


class TestWatchdog(unittest.TestCase):
    def test_fresh_site_does_nothing_and_closes_the_alert(self):
        d = W.decide(timedelta(minutes=5), TUE, [run(1, "in_progress", 10)], {}, open_issue=True)
        self.assertEqual((d["stale"], d["dispatch"], d["cancel"], d["close_issue"]), (False, False, [], True))

    def test_closed_futures_allow_the_hourly_gap(self):
        self.assertFalse(W.decide(timedelta(minutes=70), SAT, [], {}, False)["stale"])
        self.assertTrue(W.decide(timedelta(minutes=110), SAT, [], {}, False)["stale"])

    def test_stuck_deploy_like_2026_11_09(self):
        # the build finished, the deploy job sat "waiting" on github-pages for hours, and newer runs queued behind it
        runs = [run(1, "waiting", 480), run(2, "pending", 60, event="push")]
        jobs = {1: [{"status": "completed"}, {"status": "waiting", "started_at": ago(479)}]}
        d = W.decide(timedelta(minutes=480), TUE, runs, jobs, open_issue=False)
        self.assertTrue(d["stale"] and d["dispatch"])
        self.assertEqual(sorted(d["cancel"]), [1, 2])
        self.assertTrue(d["open_issue"])                                   # stale for over 90 minutes

    def test_a_recovery_in_flight_is_given_time(self):
        runs = [run(1, "waiting", 480), run(3, "in_progress", 10, title="Website (lane w9)", started_min=9)]
        d = W.decide(timedelta(minutes=45), TUE, runs, {3: [{"status": "in_progress"}]}, open_issue=False)
        self.assertFalse(d["dispatch"])
        self.assertEqual(d["cancel"], [1])
        self.assertFalse(d["open_issue"])                                  # 45 min: not yet worth an alert

    def test_a_normal_long_wait_is_not_stuck(self):
        # the "next" job sleeps up to an hour when futures are closed: a 70-minute run is normal
        self.assertFalse(W.stuck(run(1, "in_progress", 70), [{"status": "in_progress"}], TUE))
        self.assertTrue(W.stuck(run(1, "in_progress", 100), [{"status": "in_progress"}], TUE))
        self.assertFalse(W.stuck(run(1, "queued", 5), [], TUE))

    def test_issue_is_opened_once(self):
        d = W.decide(timedelta(minutes=200), TUE, [], {}, open_issue=True)
        self.assertFalse(d["open_issue"])


if __name__ == "__main__":
    unittest.main()
