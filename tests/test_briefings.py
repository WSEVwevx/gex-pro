"""NY AM and Asia briefings: schedule, text, storage, catch-up."""
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from briefings import schedule as sch
from briefings.component import BriefingsComponent
from briefings.compose import compose
from gexsys.marketcal import is_trading_day

NY = sch.NY


def et(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=NY)


def ctx(now, regime="NEGATIVE", zg=30000.0):
    return {"now": now.astimezone(timezone.utc).isoformat(),
            "markets": [{"market": "NQ", "price": 29100.0, "asof": now.isoformat(), "quality": "DL", "options": "NDX+QQQ",
                         "regime": regime, "net": -1e10, "zero_gamma": zg, "call_wall": 29800.0, "put_wall": 28980.0,
                         "abs_gamma": 28980.0, "nearest": {"label": "0DTE", "zero_gamma": 29900.0, "call_wall": 29700.0, "put_wall": 29000.0},
                         "em": {"anchor": 29050.0, "daily": 400.0, "weekly": 700.0, "weekly_expiry": "2026-10-23"},
                         "bias": {"bias": "Bearish", "confidence": "Medium", "day_type": "Trend / expansion", "target": 28800.0,
                                  "range": [28600.0, 29400.0], "summary": "x"},
                         "delta": {"zero_gamma": -12.5, "net_change": -1e8, "regime_changed": False, "prev_regime": regime}}],
            "events": [{"title": "CPI m/m", "country": "USD", "time": "2026-10-20T08:30:00-04:00", "impact": "High", "forecast": "0.3%", "previous": "0.4%"},
                       {"title": "Tiny thing", "country": "USD", "time": "2026-10-20T10:00:00-04:00", "impact": "Low"},
                       {"title": "BOJ Policy Rate", "country": "JPY", "time": "2026-10-20T23:00:00-04:00", "impact": "High"},
                       {"title": "Retail Sales", "country": "USD", "time": "2026-10-21T08:30:00-04:00", "impact": "High"}],
            "posts": [{"time": (now - timedelta(hours=2)).isoformat(), "text": "TARIFFS on China!", "market_words": ["china", "tariff"],
                       "tone": "bearish", "url": "https://x.example/1"},
                      {"time": (now - timedelta(hours=1)).isoformat(), "text": "Happy birthday", "market_words": [], "tone": None}]}


class TestSchedule(unittest.TestCase):
    def test_nyam(self):
        self.assertEqual(sch.due("nyam", et(2026, 10, 20, 9, 5), is_trading_day), (et(2026, 10, 20, 9), date(2026, 10, 20)))
        self.assertEqual(sch.due("nyam", et(2026, 10, 20, 15, 59), is_trading_day)[0], et(2026, 10, 20, 9))   # late catch-up
        self.assertIsNone(sch.due("nyam", et(2026, 10, 20, 16, 0), is_trading_day))                        # window closed
        self.assertIsNone(sch.due("nyam", et(2026, 10, 20, 8, 59), is_trading_day))
        self.assertIsNone(sch.due("nyam", et(2026, 10, 24, 10), is_trading_day))                           # Saturday
        self.assertEqual(sch.next_slot("nyam", et(2026, 10, 23, 10), is_trading_day), et(2026, 10, 26, 9))

    def test_asia(self):
        self.assertEqual(sch.due("asia", et(2026, 10, 22, 19, 30), is_trading_day), (et(2026, 10, 22, 19), date(2026, 10, 23)))
        self.assertEqual(sch.due("asia", et(2026, 10, 23, 8, 59), is_trading_day)[1], date(2026, 10, 23))  # valid until 09:00
        self.assertIsNone(sch.due("asia", et(2026, 10, 23, 9, 0), is_trading_day))                         # NY AM takes over
        self.assertIsNone(sch.due("asia", et(2026, 10, 23, 20), is_trading_day))                            # Friday: no Saturday session
        self.assertEqual(sch.due("asia", et(2026, 10, 25, 19, 1), is_trading_day)[1], date(2026, 10, 26))   # Sunday night -> Monday
        self.assertIsNone(sch.due("asia", et(2026, 11, 25, 19, 30), is_trading_day))                        # before Thanksgiving
        self.assertEqual(sch.due("asia", et(2026, 11, 26, 19, 30), is_trading_day)[1], date(2026, 11, 27))


class TestCompose(unittest.TestCase):
    def test_nyam(self):
        slot = et(2026, 10, 20, 9)
        b = compose("nyam", ctx(slot + timedelta(minutes=1)), slot, date(2026, 10, 20))
        m = b["markets"][0]
        self.assertIn("NQ 29,100.00: negative gamma, 2.2σ below zero gamma 30,000.00", m["headline"])
        self.assertEqual([x["name"] for x in m["levels"]], ["Zero gamma", "Call wall", "Abs gamma", "Put wall"])   # high to low
        self.assertEqual([x["price"] for x in m["levels"]], sorted([x["price"] for x in m["levels"]], reverse=True))
        self.assertIn("28,650.00 to 29,450.00", m["range"]["text"])
        self.assertTrue(m["odte"].startswith("0DTE: zero gamma 29,900.00"))
        self.assertIn("breakouts can run", m["plan"])
        self.assertIn("Bearish bias", m["bias"])
        self.assertEqual([e["title"] for e in b["calendar"][0]["items"]], ["CPI m/m"])          # USD, high/med, today only
        self.assertEqual([p["text"] for p in b["posts"]["items"]], ["TARIFFS on China!"])        # market posts only
        self.assertIn("CPI m/m Tue 8:30 AM", b["headline"])
        self.assertFalse(b["late"])

    def test_asia_compares_with_the_morning(self):
        slot = et(2026, 10, 20, 19)
        morning = {"NQ": {"zero_gamma": 29900.0, "regime": "POSITIVE"}}
        b = compose("asia", ctx(slot, zg=30000.0), slot, date(2026, 10, 21), morning)
        m = b["markets"][0]
        self.assertIn("Zero gamma 29,900.00 this morning, 30,000.00 now (+100.0)", m["changes"][0])
        self.assertIn("Regime flipped from positive gamma to negative gamma", m["changes"][1])
        self.assertIsNone(m["odte"])
        overnight, us = b["calendar"]
        self.assertEqual([e["title"] for e in overnight["items"]], ["BOJ Policy Rate"])
        self.assertEqual([e["title"] for e in us["items"]], ["Retail Sales"])


class TestComponent(unittest.TestCase):
    def test_writes_once_waits_for_levels_and_notifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [et(2026, 10, 20, 9, 1)]
            data = {"ctx": {"now": now[0].isoformat(), "markets": [], "events": [], "posts": []}}
            toasts = []
            c = BriefingsComponent(context=lambda: data["ctx"], is_trading_day=is_trading_day,
                                   notify=lambda t, b: toasts.append(t), store_dir=tmp, clock=lambda: now[0])
            self.assertEqual(c.tick(), [])                                  # no GEX levels yet: wait
            data["ctx"] = ctx(now[0])
            self.assertEqual(c.tick(), ["2026-10-20-nyam"])
            self.assertEqual(c.tick(), [])                                  # written once
            self.assertEqual(toasts, ["GEX PRO NY AM briefing"])
            now[0] = et(2026, 10, 20, 19, 2)
            data["ctx"] = ctx(now[0], zg=30050.0)
            self.assertEqual(c.tick(), ["2026-10-20-asia"])
            p = c.payload()
            self.assertEqual([h["kind"] for h in p["history"]], ["asia", "nyam"])   # newest first
            self.assertIn("this morning", p["latest"]["asia"]["markets"][0]["changes"][0])
            self.assertEqual(p["next"]["nyam"], et(2026, 10, 21, 9).isoformat())
            status, body = c.routes()["/api/briefings"]({})
            self.assertEqual((status, body["latest"]["nyam"]["session"]), (200, "2026-10-20"))

    def test_catch_up_is_marked_late(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = et(2026, 10, 20, 13, 0)
            c = BriefingsComponent(context=lambda: ctx(now), is_trading_day=is_trading_day, store_dir=tmp, clock=lambda: now)
            c.tick()
            self.assertTrue(c.payload()["latest"]["nyam"]["late"])


if __name__ == "__main__":
    unittest.main()
