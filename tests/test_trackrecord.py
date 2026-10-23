"""Track record: grading rules, statistics, the vol-index backtest, the freeze/grade schedule, pre-open levels."""
import json
import math
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from trackrecord import backtest, prices
from trackrecord.component import TrackRecordComponent
from trackrecord.score import grade, make_plan, summarize, wilson

NY = ZoneInfo("America/New_York")


def plan(**kw):
    base = {"market": "NQ", "underlying": "NDX", "asof": "2026-10-21T20:15:00+00:00", "ref": 100.0, "em": 10.0,
            "regime": "POSITIVE", "zg": 95.0, "cw": 108.0, "pw": 92.0, "ag": 101.0,
            "bias": {"bias": "Bullish", "confidence": "Low", "day_type": "Range / pin", "side": "positive", "target": 104.0}}
    base.update(kw)
    return make_plan(base, "2026-10-22", "2026-10-22T14:00:00+00:00")


def bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "source": "test"}


class TestGrade(unittest.TestCase):
    def test_quiet_up_day(self):
        g = grade(plan(), bar(100, 107.6, 99, 103))
        self.assertTrue(g["em_close"] and g["em_range"])
        self.assertFalse(g["em_up_break"] or g["em_down_break"])
        self.assertAlmostEqual(g["range_em"], 0.86)
        self.assertTrue(g["cw"]["touched"] and g["cw"]["held"])        # 107.6 is within 0.5 (5% of em) of 108
        self.assertFalse(g["pw"]["touched"])
        self.assertTrue(g["bias_hit"])
        self.assertTrue(g["target_beat"])                              # |103-104| < |103-100|
        self.assertFalse(g["magnet"])                                  # opened 1 from 101, closed 2 away
        self.assertEqual(g["zg"], {"open_side": "above", "crossed": False})

    def test_breakdown_day(self):
        g = grade(plan(), bar(99, 100, 88, 89))
        self.assertFalse(g["em_close"] or g["em_range"])
        self.assertTrue(g["em_down_break"])
        self.assertTrue(g["pw"]["touched"] and g["pw"]["closed_beyond"] and not g["pw"]["held"])
        self.assertTrue(g["zg"]["crossed"])
        self.assertFalse(g["bias_hit"])

    def test_levels_already_behind_price_and_neutral_are_not_graded(self):
        g = grade(plan(cw=99.0, pw=None, bias={"bias": "Neutral", "target": 100.0}, regime="NEGATIVE"), bar(100, 101, 99, 100.5))
        self.assertIsNone(g["cw"])
        self.assertIsNone(g["pw"])
        self.assertIsNone(g["bias_hit"])
        self.assertIsNone(g["target_beat"])                            # target equal to ref says nothing
        self.assertIsNone(g["magnet"])                                 # only graded in positive gamma

    def test_unusable_plan(self):
        self.assertIsNone(make_plan({"market": "NQ", "ref": 100, "em": None}, "2026-10-22", "x"))


class TestStats(unittest.TestCase):
    def test_wilson(self):
        lo, hi = wilson(7, 10)
        self.assertAlmostEqual(lo, 0.3968, places=3)                   # textbook values for 7/10
        self.assertAlmostEqual(hi, 0.8922, places=3)
        self.assertIsNone(wilson(0, 0))

    def test_summary(self):
        rows = [{"plan": plan(), "outcome": grade(plan(), bar(100, 107.6, 99, 103))},
                {"plan": plan(regime="NEGATIVE"), "outcome": grade(plan(regime="NEGATIVE"), bar(99, 100, 88, 89))},
                {"plan": plan(), "outcome": None}]
        s = summarize(rows)
        self.assertEqual(s["sessions"], 2)
        self.assertTrue(s["early"])
        self.assertEqual((s["em_close"]["k"], s["em_close"]["n"]), (1, 2))
        self.assertEqual(s["range_em"]["positive"]["mean"], 0.86)
        self.assertEqual(s["range_em"]["negative"]["mean"], 1.2)
        self.assertEqual((s["walls_held"]["k"], s["walls_held"]["n"]), (1, 2))
        self.assertEqual((s["bias"]["k"], s["bias"]["n"], s["bias"]["baseline"]), (1, 2, 0.5))


class TestBacktest(unittest.TestCase):
    def test_band_convention_and_counts(self):
        bars, vol = {}, {}
        d, c = date(2024, 1, 1), 100.0
        for i in range(60):
            d += timedelta(days=1 if d.weekday() < 4 else 3)
            bars[d.isoformat()] = {"open": c, "high": c + 2, "low": c - 2, "close": c + (1 if i % 2 else -1)}
            vol[d.isoformat()] = 36.5
            c = bars[d.isoformat()]["close"]
        r = backtest.run("SPX", "VIX", bars, vol)
        rows = backtest.days(bars, vol)
        first = rows[0]
        prev = sorted(bars)[0]
        gap = (date.fromisoformat(first["date"]) - date.fromisoformat(prev)).days
        self.assertAlmostEqual(first["em"], bars[prev]["close"] * 0.365 * math.sqrt(gap / 365))   # IV x sqrt(days/365)
        self.assertEqual(r["overall"]["n"], 59)
        self.assertEqual(sum(r["hist"]["counts"]), 59)
        self.assertAlmostEqual(sum(r["hist"]["normal"]), 59, places=0)
        self.assertEqual(r["overall"]["close_in"]["rate"], 1.0)        # +/-1 moves against a ~1.9-point band
        self.assertEqual(r["after_gap"]["weekend_or_holiday"]["n"] + r["after_gap"]["one_day"]["n"], 59)

    def test_parsers(self):
        csv = b"DATE,OPEN,HIGH,LOW,CLOSE\n10/21/2026,17.25,17.58,16.51,16.68\nbad,row\n"
        self.assertEqual(prices.parse_cboe_vol_csv(csv), {"2026-10-21": 16.68})
        daily = json.dumps({"data": [{"date": "1975-01-02", "open": "0", "high": "70.9", "low": "68.6", "close": "70.2"},
                                     {"date": "2026-10-22", "open": "7694.6", "high": "7702.9", "low": "7637.4", "close": "7663.4"}]}).encode()
        self.assertEqual(list(prices.parse_cboe_daily(daily)), ["2026-10-22"])     # no-open rows dropped
        intra = json.dumps({"data": [{"datetime": "2026-10-23T09:31:00", "price": {"open": 10, "high": 12, "low": 9, "close": 11}},
                                     {"datetime": "2026-10-23T15:59:00", "price": {"open": 11, "high": 14, "low": 10, "close": 13}}]}).encode()
        b = prices.parse_cboe_intraday(intra)
        self.assertEqual((b["open"], b["high"], b["low"], b["close"], b["last"]), (10, 14, 9, 13, "15:59"))


class FakeSource:
    VOL_INDEX = prices.VOL_INDEX

    def __init__(self):
        self.daily_bars, self.intra = {}, None

    def daily(self, underlying, since=None):
        return self.daily_bars

    def intraday(self, underlying):
        return self.intra

    def vol_index(self, underlying):
        return {}

    def hourly(self, underlying):
        return {}


class TestSchedule(unittest.TestCase):
    def make(self, tmp, now, levels):
        self.now = now
        self.src = FakeSource()
        return TrackRecordComponent(pre_open=lambda d: levels(d), is_trading_day=lambda d: d.weekday() < 5,
                                    session_close=lambda d: datetime.combine(d, datetime.min.time().replace(hour=16), NY),
                                    store_dir=Path(tmp), clock=lambda: self.now, source=self.src)

    def test_freeze_once_then_grade(self):
        inp = {"market": "NQ", "underlying": "NDX", "ref": 100.0, "em": 10.0, "regime": "POSITIVE", "cw": 108.0}
        with tempfile.TemporaryDirectory() as tmp:
            c = self.make(tmp, datetime(2026, 10, 22, 9, 50, tzinfo=NY), lambda d: {"NQ": dict(inp)} if d == date(2026, 10, 22) else {"NQ": None})
            self.assertEqual(c.tick(), [])                             # before 10:00 ET nothing is frozen
            self.now = datetime(2026, 10, 22, 10, 5, tzinfo=NY)
            self.assertEqual(c.tick(), ["2026-10-22_NQ frozen"])
            inp["ref"] = 999.0                                         # later data never changes a frozen plan
            self.assertEqual(c.tick(), [])
            self.now = datetime(2026, 10, 22, 16, 25, tzinfo=NY)
            self.src.intra = {"date": "2026-10-22", "open": 100, "high": 104, "low": 98, "close": 103, "last": "15:50", "source": "i"}
            self.assertEqual(c.tick(), [])                             # 1-minute bars stop early: not final
            self.src.intra["last"] = "15:59"
            self.assertEqual(c.tick(), ["2026-10-22_NQ graded"])
            s = c.sessions()[0]
            self.assertEqual((s["plan"]["ref"], s["outcome"]["close"], s["outcome"]["em_close"]), (100.0, 103.0, True))
            # the next day the app saw nothing before the open: recorded as missed, not skipped
            self.now = datetime(2026, 10, 23, 11, 0, tzinfo=NY)
            self.assertEqual(c.tick(), ["2026-10-23_NQ missed"])
            p = c.payload()
            self.assertEqual(p["started"], "2026-10-22")
            self.assertEqual(p["stats"]["NQ"]["sessions"], 1)
            self.assertEqual([x["status"] for x in p["sessions"]], ["missed", "graded"])

    def test_partial_daily_bar_is_never_used(self):
        inp = {"market": "ES", "underlying": "SPX", "ref": 100.0, "em": 10.0}
        with tempfile.TemporaryDirectory() as tmp:
            c = self.make(tmp, datetime(2026, 10, 22, 15, 55, tzinfo=NY), lambda d: {"ES": dict(inp)} if d == date(2026, 10, 22) else {})
            c.tick()
            self.src.daily_bars = {"2026-10-22": {"open": 100, "high": 101, "low": 99, "close": 100.5, "source": "partial"}}
            c._daily_bars("SPX", self.now)                             # cached before the close
            self.now = datetime(2026, 10, 22, 16, 25, tzinfo=NY)
            self.src.daily_bars = {"2026-10-22": {"open": 100, "high": 103, "low": 95, "close": 96, "source": "final"}}
            c.tick()
            s = [x for x in c.sessions() if x["session"] == "2026-10-22"][0]
            self.assertEqual(s["outcome"]["source"], "final")

    def test_daily_bar_later_and_give_up(self):
        inp = {"market": "ES", "underlying": "SPX", "ref": 100.0, "em": 10.0}
        with tempfile.TemporaryDirectory() as tmp:
            c = self.make(tmp, datetime(2026, 10, 22, 10, 30, tzinfo=NY), lambda d: {"ES": dict(inp)} if d == date(2026, 10, 22) else {})
            c.tick()
            self.now = datetime(2026, 10, 23, 8, 0, tzinfo=NY)
            self.src.daily_bars = {"2026-10-22": {"open": 100, "high": 101, "low": 95, "close": 96, "source": "d"}}
            c._daily.clear()
            self.assertEqual(c.tick(), ["2026-10-22_ES graded"])
        with tempfile.TemporaryDirectory() as tmp:
            c = self.make(tmp, datetime(2026, 10, 22, 10, 30, tzinfo=NY), lambda d: {"ES": dict(inp)} if d == date(2026, 10, 22) else {})
            c.tick()
            self.now = datetime(2026, 10, 30, 17, 0, tzinfo=NY)
            self.assertIn("2026-10-22_ES no_prices", c.tick())


    def test_hosted_build_writes_the_page_data(self):
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            c = self.make(tmp, datetime(2026, 10, 22, 10, 30, tzinfo=NY), lambda d: {"ES": {"market": "ES", "underlying": "SPX", "ref": 100.0, "em": 10.0}})
            with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "me/repo"}):
                os.environ.pop("GEXPRO_TRACK_DIR", None)
                c.build_static(Path(tmp) / "data", Path(tmp) / "state")
            p = json.loads((Path(tmp) / "data" / "trackrecord.json").read_text(encoding="utf-8"))
            self.assertEqual(p["proof_url"], "https://github.com/me/repo/commits/track-record")
            self.assertIn("pending", {s["status"] for s in p["sessions"]})
            self.assertTrue((Path(tmp) / "state" / "trackrecord" / "sessions").is_dir())
            self.assertIn("ALL", p["stats"])


class TestPreOpen(unittest.TestCase):
    def test_last_snapshot_before_the_open(self):
        from gexpro.context import pre_open
        from gexsys.component import GexComponent
        from gexsys.service import MarketWorker
        from tests.test_integration import synth_cfg
        with tempfile.TemporaryDirectory() as tmp:
            w = MarketWorker(synth_cfg(tmp))
            w.step()
            s = w.result["summary"]
            o = datetime(2026, 10, 22, 9, 30, tzinfo=NY)
            for t, ref in ((o - timedelta(hours=40), 1.0), (o - timedelta(hours=2), 2.0), (o - timedelta(minutes=1), 3.0), (o + timedelta(minutes=5), 4.0)):
                w.store.save(w.key, dict(s, asof=t.astimezone(timezone.utc).isoformat(), ref_price=ref))
            no_em = dict(s, extras=dict(s["extras"], expected_move=None))                 # unusable: skipped, not chosen
            w.store.save(w.key, dict(no_em, asof=(o - timedelta(seconds=30)).astimezone(timezone.utc).isoformat(), ref_price=9.0))
            got = pre_open(GexComponent.from_workers({w.key: w}), date(2026, 10, 22))["NQ"]
            self.assertEqual(got["ref"], 3.0)                          # the last one before 09:30, never after
            self.assertEqual(got["underlying"], s["underlying"])
            self.assertIsNotNone(got["em"])
            self.assertIsNotNone(got["bias"])
            self.assertIsNone(pre_open(GexComponent.from_workers({w.key: w}), date(2026, 10, 27))["NQ"])


if __name__ == "__main__":
    unittest.main()
