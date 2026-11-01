"""NY AM and Asia briefings: schedule, text, storage, catch-up."""
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from briefings import schedule as sch
from briefings.component import BriefingsComponent
from briefings.compose import compose
from briefings.weekly import recap
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


def week_bars(closes, start=date(2026, 10, 23), gap=None):
    """closes[0] is the Friday before; the rest are Monday onward. gap = (index, open) overrides that day's open."""
    days = [start] + [start + timedelta(days=3 + i) for i in range(len(closes) - 1)]
    out = {}
    for i, (d, c) in enumerate(zip(days, closes)):
        o = closes[i - 1] if i else c
        if gap and gap[0] == i:
            o = gap[1]
        out[d.isoformat()] = {"open": o, "high": max(o, c) + 1, "low": min(o, c) - 1, "close": c}
    return out


def week_input(**kw):
    idx = {"S&P 500": week_bars([100, 101, 102, 103, 102, 98], gap=(5, 99)), "Nasdaq-100": week_bars([200, 202, 204, 206, 204, 190]),
           "Dow": week_bars([300, 300, 300, 300, 300, 303]), "Russell 2000": week_bars([400, 400, 400, 400, 400, 396]),
           "VIX": week_bars([15, 15, 15, 16, 17, 20])}
    idx.update(kw)
    stocks = [{"symbol": s, "name": s, "bars": week_bars([100, 100, 100, 100, 100, c])} for s, c in (("AAA", 110), ("BBB", 95), ("CCC", 101), ("DDD", 99))]
    return {"indexes": idx, "stocks": stocks}


class TestWeekly(unittest.TestCase):
    END = date(2026, 10, 30)

    def test_recap_states_the_measured_week(self):
        now = et(2026, 10, 30, 17, 5)
        b = recap(week_input(), self.END, et(2026, 10, 30, 17), now)
        t = b["headline"]
        self.assertIn("The S&P 500 fell 2.0% to 98 this week, and the Nasdaq-100 fell 5.0% to 190.", t)
        self.assertIn("The Dow rose 1.0% to 303, and the Russell 2000 fell 1.0% to 396.", t)
        self.assertIn("3 up days out of 5", t)
        self.assertIn("best session on Monday (+1.0%) and its worst on Friday (-3.9%)", t)
        self.assertIn("near the bottom of that range", t)                     # low 97, high 104, close 98
        self.assertIn("biggest opening gap was Friday, -2.9%", t)             # 102 to 99
        self.assertIn("lagged the S&P 500 by 3.0 percentage points", t)
        self.assertIn("The VIX rose from 15.0 to 20.0.", t)
        self.assertIn("AAA (+10.0%) did best and BBB (-5.0%) did worst", t)
        self.assertLess(b["sentences"], 10)
        self.assertEqual(t.count(". ") + 1, b["sentences"])
        self.assertEqual([x["name"] for x in b["indexes"]], ["S&P 500", "Nasdaq-100", "Dow", "Russell 2000", "VIX"])

    def test_waits_for_the_final_bar_and_survives_missing_extras(self):
        slot, now = et(2026, 10, 30, 17), et(2026, 10, 30, 17, 5)
        short = week_input()
        short["indexes"]["S&P 500"] = week_bars([100, 101, 102, 103, 102])      # Friday's bar not in yet
        self.assertIsNone(recap(short, self.END, slot, now))
        self.assertIsNone(recap(None, self.END, slot, now))
        b = recap({"indexes": {k: week_input()["indexes"][k] for k in ("S&P 500", "Nasdaq-100")}, "stocks": []}, self.END, slot, now)
        self.assertNotIn("VIX", b["headline"])
        self.assertLess(b["sentences"], 10)

    def test_due_on_the_weeks_last_trading_day_only(self):
        self.assertIsNone(sch.due("weekly", et(2026, 10, 30, 16, 59), lambda d: False))
        self.assertEqual(sch.next_slot("weekly", et(2026, 10, 28, 12), is_trading_day), et(2026, 10, 30, 17))
        self.assertEqual(sch.due("weekly", et(2026, 11, 1, 12), is_trading_day), (et(2026, 10, 30, 17), date(2026, 10, 30)))
        # Good Friday 2026: the week ends on Thursday
        self.assertEqual(sch.next_slot("weekly", et(2026, 3, 31, 12), is_trading_day), et(2026, 4, 2, 17))

    def test_component_writes_once_and_keeps_recaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            def data():
                calls.append(1)
                return week_input()
            now = [et(2026, 11, 1, 12)]
            c = BriefingsComponent(lambda: {"markets": []}, is_trading_day, store_dir=tmp, clock=lambda: now[0], week_data=data)
            self.assertEqual(c.tick(), ["2026-10-30-weekly"])
            self.assertEqual(c.tick(), [])
            self.assertEqual(len(calls), 1)
            self.assertEqual(c.payload()["latest"]["weekly"]["kind"], "weekly")
            for i in range(45):                                                  # older daily briefings are pruned, recaps are not
                c._save(f"2026-09-{i + 10:02d}-nyam", {"kind": "nyam"})
            self.assertTrue(c._path("2026-10-30-weekly").exists())

    def test_retries_slowly_while_prices_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            now = [et(2026, 10, 30, 17, 5)]
            c = BriefingsComponent(lambda: {"markets": []}, is_trading_day, store_dir=tmp, clock=lambda: now[0], week_data=lambda: calls.append(1) or {})
            c.tick(); c.tick()
            self.assertEqual(len(calls), 1)
            now[0] += timedelta(minutes=31)
            c.tick()
            self.assertEqual(len(calls), 2)


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

    def test_mirror_fills_gaps_and_never_overwrites(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            now = [et(2026, 10, 20, 9, 1)]
            c = BriefingsComponent(context=lambda: ctx(now[0]), is_trading_day=is_trading_day, store_dir=tmp, clock=lambda: now[0])
            c.tick()                                                         # writes 2026-10-20-nyam here
            mine = c._load("2026-10-20-nyam")
            remote = {"by_id": {
                "2026-10-20-nyam": dict(mine, headline="someone else's"),
                "2026-10-19-asia": dict(mine, kind="asia", slot=et(2026, 10, 19, 19).isoformat(), headline="from the site"),
                "2026-10-18-asia": {"kind": "asia", "slot": et(2026, 10, 17, 19).isoformat()},   # id and slot disagree: skipped
                "junk": "x"}}
            got = c.mirror("https://example.test/b.json", fetch=lambda u: json.dumps(remote).encode())
            self.assertEqual(got, ["2026-10-19-asia"])
            self.assertEqual(c._load("2026-10-20-nyam")["headline"], mine["headline"])   # the local one wins
            self.assertEqual(c.mirror("x", fetch=lambda u: (_ for _ in ()).throw(OSError("offline"))), [])

    def test_catch_up_is_marked_late(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = et(2026, 10, 20, 13, 0)
            c = BriefingsComponent(context=lambda: ctx(now), is_trading_day=is_trading_day, store_dir=tmp, clock=lambda: now)
            c.tick()
            self.assertTrue(c.payload()["latest"]["nyam"]["late"])


if __name__ == "__main__":
    unittest.main()
