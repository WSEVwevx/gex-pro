import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from gexsys import config as cfgmod
from gexsys import publish as pub
from gexsys.engine import ConfigError
from gexsys.marketcal import NY
from gexsys.service import MarketWorker


def et(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=NY)


C = pub.PublishConfig()


class TestSchedule(unittest.TestCase):
    def test_every_30_minutes_around_the_clock(self):
        self.assertEqual(len(C.slots()), 49)                                                       # 48 + 09:45
        self.assertEqual(pub.latest_slot(et(2026, 10, 20, 12, 30), C), et(2026, 10, 20, 12, 30))    # on the half hour
        self.assertEqual(pub.latest_slot(et(2026, 10, 20, 12, 20), C), et(2026, 10, 20, 12, 0))
        self.assertEqual(pub.latest_slot(et(2026, 10, 20, 12, 0), C), et(2026, 10, 20, 12, 0))     # on the hour
        self.assertEqual(pub.next_slot(et(2026, 10, 20, 12, 0), C), et(2026, 10, 20, 12, 30))
        self.assertEqual(pub.latest_slot(et(2026, 10, 20, 3, 10), C), et(2026, 10, 20, 3, 0))      # overnight
        self.assertEqual(pub.next_slot(et(2026, 10, 20, 23, 30), C), et(2026, 10, 21, 0, 0))       # midnight
        self.assertEqual(pub.latest_slot(et(2026, 10, 20, 18, 5), C), et(2026, 10, 20, 18, 0))     # after the cash close
        self.assertEqual(pub.latest_slot(et(2026, 10, 20, 17, 30), C), et(2026, 10, 20, 16, 30))   # no slot in the 17:00 halt
        self.assertEqual(pub.next_slot(et(2026, 10, 20, 16, 30), C), et(2026, 10, 20, 18, 0))      # 17:00 and 17:30 skipped

    def test_weekend(self):
        sat = et(2026, 10, 24, 12, 0)
        self.assertEqual(pub.latest_slot(sat, C), et(2026, 10, 23, 16, 30))        # the futures stop Friday 17:00
        self.assertEqual(pub.next_slot(sat, C), et(2026, 10, 25, 18, 0))           # and reopen Sunday 18:00
        self.assertEqual(pub.next_slot(et(2026, 10, 25, 18, 0), C), et(2026, 10, 25, 18, 30))

    def test_sunday_evening_publishes(self):
        # 2026-11-08: the Sunday session had no paste at all (slots needed a trading date); Friday's was served
        sun = et(2026, 11, 8, 23, 45)
        self.assertEqual(pub.latest_slot(sun, C), et(2026, 11, 8, 23, 30))
        self.assertEqual(pub.due(et(2026, 11, 6, 23, 30), sun, C), et(2026, 11, 8, 23, 30))

    def test_holiday_and_early_close(self):
        # Thanksgiving Thu 2026-11-26: the futures trade until a 13:00 halt (pastes to 12:30), reopen at 18:00
        self.assertEqual(pub.next_slot(et(2026, 11, 25, 23, 30), C), et(2026, 11, 26, 0, 0))
        self.assertEqual(pub.next_slot(et(2026, 11, 26, 12, 30), C), et(2026, 11, 26, 18, 0))
        self.assertEqual(pub.latest_slot(et(2026, 11, 26, 17, 0), C), et(2026, 11, 26, 12, 30))
        # Christmas Fri 2026-12-25: nothing from the Christmas Eve halt to the Sunday reopen
        self.assertEqual(pub.next_slot(et(2026, 12, 24, 13, 30), C), et(2026, 12, 27, 18, 0))
        # Fri 11-27: the futures halt at 13:15
        self.assertEqual(pub.next_slot(et(2026, 11, 27, 12, 30), C), et(2026, 11, 27, 13, 0))
        self.assertEqual(pub.latest_slot(et(2026, 11, 27, 23, 59), C), et(2026, 11, 27, 13, 0))
        # cash-hours-only mode still skips slots at or after an early close
        rth = pub.PublishConfig(times_et=["09:45", "13:45", "15:30"], all_day=False)
        self.assertEqual(pub.next_slot(et(2026, 11, 27, 12, 0), rth), et(2026, 11, 30, 9, 45))
        self.assertEqual(pub.latest_slot(et(2026, 11, 27, 16, 0), rth), et(2026, 11, 27, 9, 45))

    def test_dst(self):
        s = pub.next_slot(et(2026, 11, 2, 8, 30), C)          # after fall-back: EST
        self.assertEqual(s.astimezone(timezone.utc).hour, 14)
        s = pub.next_slot(et(2026, 10, 30, 8, 30), C)         # before: EDT
        self.assertEqual(s.astimezone(timezone.utc).hour, 13)

    def test_due(self):
        now = et(2026, 10, 20, 12, 0)
        slot = pub.due(None, now, C)
        self.assertEqual(slot, et(2026, 10, 20, 12, 0))
        self.assertIsNone(pub.due(slot, et(2026, 10, 20, 12, 29), C))
        self.assertEqual(pub.due(slot, et(2026, 10, 20, 12, 31), C), et(2026, 10, 20, 12, 30))
        self.assertEqual(pub.due(slot, et(2026, 10, 20, 13, 46), C), et(2026, 10, 20, 13, 30))    # a missed slot: the latest

    def test_the_extra_slot_after_the_open(self):
        # Cboe is 15 min delayed: the 09:30 paste carries ~09:15 quotes, the 09:45 one the first opening prints
        day = [s.strftime("%H:%M") for s in pub._day_slots(et(2026, 11, 19, 0, 0).date(), C)]
        self.assertEqual(day[day.index("09:00"):day.index("10:00") + 1], ["09:00", "09:30", "09:45", "10:00"])
        self.assertEqual(pub.latest_slot(et(2026, 11, 19, 9, 44), C), et(2026, 11, 19, 9, 30))
        self.assertEqual(pub.latest_slot(et(2026, 11, 19, 9, 50), C), et(2026, 11, 19, 9, 45))
        self.assertEqual(pub.next_slot(et(2026, 11, 19, 9, 44), C), et(2026, 11, 19, 9, 45))
        self.assertEqual(pub.next_slot(et(2026, 11, 19, 9, 45), C), et(2026, 11, 19, 10, 0))
        self.assertEqual(pub.due(et(2026, 11, 19, 9, 30), et(2026, 11, 19, 9, 47), C), et(2026, 11, 19, 9, 45))
        # only when the futures trade: none on a Saturday or on Christmas (closed all day); Thanksgiving trades until 13:00
        for d, want in ((et(2026, 11, 21, 0, 0), False), (et(2026, 12, 25, 0, 0), False), (et(2026, 11, 26, 0, 0), True)):
            self.assertEqual(any(s.strftime("%H:%M") == "09:45" for s in pub._day_slots(d.date(), C)), want, d.date())

    def test_configs_are_every_30_minutes_plus_0945(self):
        want = sorted([f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)] + ["09:45"])
        self.assertEqual(list(pub.DEFAULT_TIMES_ET), want)
        for path in sorted(Path("configs").glob("*.json")):
            pc = cfgmod.load(str(path)).publish
            self.assertTrue(pc.all_day, path)
            self.assertEqual([s.strftime("%H:%M") for s in pc.slots()], want, path)

    def test_validation(self):
        with self.assertRaises(ConfigError):
            pub.PublishConfig(times_et=["9h45"]).validate()
        with self.assertRaises(ConfigError):
            pub.PublishConfig(webhook_format="slack").validate()
        with self.assertRaises(ConfigError):
            cfgmod.from_dict({"market": "NQ", "source": "NDX", "provider": {"name": "synthetic"},
                              "publish": {"time_et": ["10:00"]}})

    def test_webhook_bodies(self):
        p = "GEX1;" + "x" * 1800
        d = pub.webhook_body("discord", "NQ", p, {"slot_et": "2026-10-20 11:45", "regime": "POSITIVE", "zero_gamma": 1})
        self.assertLessEqual(len(d["content"]), 2000)
        j = pub.webhook_body("json", "NQ", "GEX1;a=1", {"regime": "NEGATIVE"})
        self.assertEqual((j["payload"], j["regime"]), ("GEX1;a=1", "NEGATIVE"))


class TestWorkerPublish(unittest.TestCase):
    def test_publishes_once_per_slot_and_notifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cfgmod.from_dict({"market": "NQ", "source": "NDX", "provider": {"name": "synthetic", "live_clock": False},
                                  "futures_ref": {"mode": "synthetic_basis"}, "storage": {"root": tmp},
                                  "publish": {"webhook_format": "discord"}})
            w = MarketWorker(c)
            toasts, hooks = [], []
            w.notify_desktop = lambda t, b: toasts.append((t, b))
            w.send_webhook = lambda url, body: hooks.append((url, body))
            with mock.patch.dict(os.environ, {"GEX_PUBLISH_WEBHOOK_URL": "https://example.invalid/hook"}):
                w.step(et(2026, 10, 20, 12, 5))
                w.step(et(2026, 10, 20, 12, 20))
                self.assertEqual(len(toasts), 1)
                self.assertEqual(w.published["slot_et"], "2026-10-20 12:00")
                self.assertTrue(w.published["payload"].startswith("GEX1;"))
                self.assertIn("```GEX1;", hooks[0][1]["content"])
                w.step(et(2026, 10, 20, 13, 50))
                self.assertEqual(len(toasts), 2)
                self.assertEqual(w.published["slot_et"], "2026-10-20 13:30")


if __name__ == "__main__":
    unittest.main()
