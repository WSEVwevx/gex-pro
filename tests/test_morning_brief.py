"""The NY AM brief (briefings/morning.py): fixed text from fixed data, no hindsight, and its grade."""
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from briefings import morning, schedule as sch
from briefings.component import BriefingsComponent
from briefings.compose import compose
from gexsys.marketcal import is_trading_day

NY = sch.NY
SESSION = date(2026, 11, 16)                       # a Monday
SLOT = datetime(2026, 11, 16, 9, 0, tzinfo=NY)


def market(**kw):
    m = {"market": "NQ", "price": 28000.0, "asof": (SLOT - timedelta(minutes=2)).isoformat(), "quality": "DL", "options": "NDX+QQQ",
         "regime": "NEGATIVE", "zero_gamma": 28500.0, "call_wall": 29000.0, "put_wall": 27900.0, "abs_gamma": 27900.0,
         "nearest": {"label": "0DTE", "zero_gamma": 28400.0, "call_wall": 28200.0, "put_wall": 27950.0},
         "em": {"anchor": 28000.0, "daily": 400.0}, "factor": 1.0, "offset": 0.0,
         "prev": {"day": "2026-11-13", "zero_gamma": 28540.0, "call_wall": 29000.0, "put_wall": 28000.0, "regime": "NEGATIVE", "em": 380.0}}
    m.update(kw)
    return m


def ctx(*markets, events=()):
    return {"now": (SLOT + timedelta(minutes=1)).astimezone(timezone.utc).isoformat(), "markets": list(markets) or [market()],
            "events": list(events), "posts": []}


def graded(session, regime="NEGATIVE", range_em=1.2, market="NQ", cw=None, pw=None, **out):
    o = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "em_close": True, "move_em": 0.25, "range_em": range_em,
         "cw": cw, "pw": pw, "zg": {"crossed": False}, "bias_hit": None}
    o.update(out)
    return {"session": session, "market": market, "plan": {"regime": regime, "bias": "Bearish"}, "outcome": o}


def history(n, regime="NEGATIVE", range_em=1.2, **kw):
    d, out = date(2026, 11, 13), []
    while len(out) < n:
        if is_trading_day(d):
            out.append(graded(d.isoformat(), regime, range_em, **kw))
        d -= timedelta(days=1)
    return out


CPI = {"title": "CPI m/m", "country": "USD", "time": "2026-11-16T08:30:00-05:00", "impact": "High", "forecast": "0.3%", "previous": "0.4%"}


class TestText(unittest.TestCase):
    def test_exact_brief_from_a_fixed_snapshot(self):
        touched = {"touched": True, "held": True}
        rec = history(20, range_em=1.25, cw=touched) + history(4, "POSITIVE", 0.75, market="ES")
        b = compose("nyam", ctx(events=[CPI]), SLOT, SESSION, record=rec, past=[])
        m = b["markets"][0]
        self.assertEqual(m["regime_line"], "NQ 28,000.00 is in negative gamma, 1.2σ below zero gamma 28,500.00.")
        self.assertEqual(m["history"], "20 negative gamma sessions graded: range averaged 1.25× the expected move "
                                       "(all 24: 1.17×). Walls held on 20 of 20 touches.")
        self.assertEqual([(x["name"], x["price"], x["dist"], x["dist_em"], x["why"]) for x in m["levels"]], [
            ("0DTE put wall", 27950.0, -50.0, 0.12, "largest put gamma strike"),
            ("Put wall · Abs gamma", 27900.0, -100.0, 0.25, "largest put gamma strike"),
            ("0DTE call wall", 28200.0, 200.0, 0.5, "largest call gamma strike")])
        self.assertEqual(m["range"]["text"], "Expected range today 27,600.00 to 28,400.00 (±400 pts, 1σ).")
        self.assertEqual(m["changes"], {"since": "Fri Nov 13", "items": [
            "Zero gamma 28,540.00 → 28,500.00 (-40.00).", "Put wall 28,000.00 → 27,900.00 (-100.00).", "Expected move ±380 → ±400 pts."]})
        self.assertEqual(m["yesterday"]["text"], "Fri Nov 13: closed inside the expected range (move +0.25σ), range 1.25× the expected move; "
                                                 "call wall held; zero gamma not crossed.")
        self.assertEqual(b["headline"], "NQ: negative gamma, 1.2σ below zero gamma. 1 high-impact release: CPI m/m 8:30 AM.")
        self.assertEqual(b["rule"], morning.RULE)
        self.assertEqual([e["title"] for e in b["calendar"][0]["items"]], ["CPI m/m"])
        self.assertEqual(b["calendar"][0]["history"], "High-impact days graded so far: 0 of the 20 needed to say how they range.")
        self.assertFalse({"plan", "bias", "odte", "posts"} & (set(m) | set(b)))          # the old ungraded sections are gone

    def test_same_price_levels_merge_and_the_nearest_three_are_kept(self):
        lv = morning.key_levels(market(nearest={}))
        self.assertEqual([x["name"] for x in lv], ["Put wall · Abs gamma", "Zero gamma", "Call wall"])
        self.assertEqual(lv[1]["why"], "gamma turns positive above it")
        self.assertEqual(len(morning.key_levels(market())), 3)


class TestEmptyCases(unittest.TestCase):
    def test_no_history_no_events_no_change_no_yesterday(self):
        m0 = market(prev=dict(market()["prev"], zero_gamma=28500.0, put_wall=27900.0, em=400.0))
        b = compose("nyam", ctx(m0), SLOT, SESSION, record=[], past=[])
        m = b["markets"][0]
        self.assertEqual(m["history"], "0 negative gamma sessions graded so far: not enough yet (20 needed).")
        self.assertEqual(m["changes"]["items"], ["No change since Fri Nov 13's close."])
        self.assertIsNone(m["yesterday"])
        self.assertEqual((b["calendar"][0]["items"], b["calendar"][0]["history"]), ([], None))

    def test_too_few_sessions_or_touches_print_no_percentage(self):
        b = compose("nyam", ctx(), SLOT, SESSION, record=history(19), past=[])
        self.assertEqual(b["markets"][0]["history"], "19 negative gamma sessions graded so far: not enough yet (20 needed).")
        b = compose("nyam", ctx(), SLOT, SESSION, record=history(20), past=[])
        self.assertIn("Wall touches so far: 0 of the 20 needed.", b["markets"][0]["history"])

    def test_missing_previous_close_and_ungraded_yesterday_are_said(self):
        rec = [{"session": "2026-11-13", "market": "NQ", "plan": {"regime": "NEGATIVE"}, "outcome": None}]
        m = compose("nyam", ctx(market(prev=None)), SLOT, SESSION, record=rec, past=[])["markets"][0]
        self.assertEqual(m["changes"]["items"], ["The previous close's levels are not saved here: no comparison."])
        self.assertEqual(m["yesterday"]["text"], "Fri Nov 13: not graded yet.")

    def test_stale_levels_are_named(self):
        old = market(asof=datetime(2026, 11, 13, 16, 55, tzinfo=NY).isoformat())
        m = compose("nyam", ctx(old), SLOT, SESSION)["markets"][0]
        self.assertEqual(m["stale"], "Levels were last calculated Fri 4:55 PM ET: older than usual for a brief.")
        self.assertIsNone(compose("nyam", ctx(), SLOT, SESSION)["markets"][0]["stale"])


class TestNoHindsight(unittest.TestCase):
    def test_today_and_later_sessions_never_reach_the_brief(self):
        rec = history(22)
        clean = compose("nyam", ctx(events=[CPI]), SLOT, SESSION, record=rec, past=[])
        future = [graded("2026-11-16", range_em=9.0, cw={"touched": True, "held": False}),
                  graded("2026-11-17", range_em=9.0), graded("2026-11-16", "POSITIVE", 0.01)]
        later_brief = [{"kind": "nyam", "session": "2026-11-16", "calendar": [{"items": [{"impact": "High"}]}]}]
        self.assertEqual(compose("nyam", ctx(events=[CPI]), SLOT, SESSION, record=rec + future, past=later_brief), clean)

    def test_nothing_in_a_brief_is_newer_than_the_brief(self):
        b = compose("nyam", ctx(), SLOT, SESSION, record=history(22), past=[])
        written = datetime.fromisoformat(b["generated_at"])
        for m in b["markets"]:
            self.assertLessEqual(datetime.fromisoformat(m["asof"]), written)
            self.assertLess(m["yesterday"]["session"], b["session"])
        late = market(asof=(SLOT + timedelta(hours=1)).isoformat())                  # data stamped after the brief: refused
        with self.assertRaises(ValueError):
            compose("nyam", ctx(late), SLOT, SESSION)


class TestCalendar(unittest.TestCase):
    def test_weekends_holidays_and_early_closes(self):
        at = lambda y, mo, d, h=9, mi=5: datetime(y, mo, d, h, mi, tzinfo=NY)
        self.assertIsNone(sch.due("nyam", at(2026, 11, 14), is_trading_day))                      # Saturday
        self.assertIsNone(sch.due("nyam", at(2026, 11, 26), is_trading_day))                      # Thanksgiving
        self.assertEqual(sch.due("nyam", at(2026, 11, 27), is_trading_day)[1], date(2026, 11, 27))  # 13:00 close: still briefed
        self.assertEqual(sch.due("nyam", at(2026, 11, 16), is_trading_day)[1], SESSION)


class TestGrade(unittest.TestCase):
    def test_a_hand_graded_session(self):
        # brief: price 28,000, expected move 400, range 27,600-28,400, median range so far 1.0x; futures = index * 1.0
        b = compose("nyam", ctx(), SLOT, SESSION, record=history(20, range_em=1.0), past=[])
        mb = b["markets"][0]
        # session: high 28,190 low 27,880 close 27,920. Range 310 = 0.775x: NOT wider than 1.0x, so the negative-gamma
        # range call missed. 0DTE put wall 27,950: touched (low 27,880), closed below it: broke. Put wall 27,900: touched,
        # close 27,920 above it: held. 0DTE call wall 28,200: high 28,190 is within 20 pts (5% of 400): touched, held.
        got = morning.grade(mb, {"high": 28190.0, "low": 27880.0, "close": 27920.0})
        self.assertEqual([(g["type"], g["hit"]) for g in got], [
            ("band", True), ("regime_range", False),
            ("key_level", True), ("wall_holds", False),
            ("key_level", True), ("wall_holds", True),
            ("key_level", True), ("wall_holds", True)])
        base = [g["base"] for g in got if g["type"] == "key_level"]
        self.assertEqual(base, [0.9402, 0.8415, 0.6527])      # 2*(1-Phi(d - 0.05)) at 0.125, 0.25 and 0.5 expected moves
        self.assertEqual(morning.grade(mb, {"high": 28190.0, "low": 27880.0}), [])       # no close: nothing graded

    def test_futures_levels_are_graded_on_the_index_bar(self):
        m = market(price=28084.0, zero_gamma=28585.5, call_wall=29087.0, put_wall=27983.75, abs_gamma=27983.75, nearest={},
                   em={"anchor": 28084.0, "daily": 401.2}, factor=1.003, offset=0.0)
        mb = compose("nyam", ctx(m), SLOT, SESSION)["markets"][0]
        got = morning.grade(mb, {"high": 28100.0, "low": 27890.0, "close": 27950.0})      # index points: put wall = 27,900
        self.assertEqual([(g["type"], g["hit"]) for g in got][:3], [("band", True), ("key_level", True), ("wall_holds", True)])

    def test_score_and_the_removal_flag(self):
        rows = [{"type": "band", "hit": i < 4, "base": 0.6827} for i in range(20)] + [{"type": "key_level", "hit": True, "base": 0.6}] * 3
        s = {r["type"]: r for r in morning.score(rows)}
        self.assertEqual((s["band"]["k"], s["band"]["n"], s["band"]["rate"], s["band"]["flagged"]), (4, 20, 0.2, True))
        self.assertEqual((s["key_level"]["enough"], s["key_level"]["flagged"]), (False, False))
        self.assertEqual((s["wall_holds"]["n"], s["wall_holds"]["rate"]), (0, None))


class TestComponent(unittest.TestCase):
    def test_brief_is_frozen_and_graded_once_from_the_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [SLOT + timedelta(minutes=1)]
            rec = history(20)
            c = BriefingsComponent(context=lambda: ctx(), is_trading_day=is_trading_day, store_dir=tmp, clock=lambda: now[0],
                                   record=lambda: rec)
            self.assertEqual(c.tick(weekly=False), ["2026-11-16-nyam"])
            frozen = (c.dir / "2026-11-16-nyam.json").read_bytes()
            self.assertEqual(c.payload()["score"]["briefs"], 0)                            # no outcome yet
            rec.append(graded("2026-11-16", high=28190.0, low=27880.0, close=27920.0))
            now[0] = SLOT + timedelta(hours=8)
            c.tick(weekly=False)
            c.tick(weekly=False)                                                           # a second pass adds nothing
            self.assertEqual((c.dir / "2026-11-16-nyam.json").read_bytes(), frozen)        # the brief itself never changes
            lines = [json.loads(x) for x in (c.dir / "scores.jsonl").read_text().splitlines()]
            self.assertEqual(len(lines), 8)
            p = c.payload()
            self.assertEqual(p["score"]["briefs"], 1)
            self.assertEqual({r["type"]: (r["k"], r["n"]) for r in p["score"]["rows"]},
                             {"band": (1, 1), "regime_range": (0, 1), "key_level": (3, 3), "wall_holds": (2, 3)})
            self.assertEqual(p["latest"]["nyam"]["version"], 2)
            self.assertEqual([h["id"] for h in p["history"]], ["2026-11-16-nyam"])          # the score file is not a briefing

    def test_each_market_is_graded_when_its_own_outcome_arrives(self):
        # 2026-11-17 audit: the Track record grades NQ and ES separately (each needs its own index bar); a brief
        # graded as soon as one market had an outcome never got the other market's grades
        with tempfile.TemporaryDirectory() as tmp:
            now = [SLOT + timedelta(minutes=1)]
            rec = history(20) + history(20, market="ES")
            two = lambda: ctx(market(), market(market="ES", price=7000.0, zero_gamma=7100.0, call_wall=7200.0, put_wall=6900.0,
                                             abs_gamma=6950.0, em={"anchor": 7000.0, "daily": 80.0},
                                             nearest={"label": "0DTE", "zero_gamma": 7090.0, "call_wall": 7050.0, "put_wall": 6980.0}))
            c = BriefingsComponent(context=two, is_trading_day=is_trading_day, store_dir=tmp, clock=lambda: now[0], record=lambda: rec)
            c.tick(weekly=False)
            rec.append(graded("2026-11-16", high=28190.0, low=27880.0, close=27920.0))
            now[0] = SLOT + timedelta(hours=8)
            c.tick(weekly=False)
            rec.append(graded("2026-11-16", market="ES", high=7060.0, low=6970.0, close=7010.0))
            c.tick(weekly=False)
            c.tick(weekly=False)
            rows = [json.loads(x) for x in (c.dir / "scores.jsonl").read_text().splitlines()]
            self.assertEqual({r["market"] for r in rows}, {"NQ", "ES"})
            self.assertEqual(len([r for r in rows if r["market"] == "NQ"]), 8)                 # NQ graded once, not again

    def test_a_cut_off_last_line_does_not_regrade_everything(self):
        # 2026-11-17 audit: one unreadable line (a write cut off by a crash) made the whole score file read as empty,
        # so every brief was graded again and its rows appended a second time
        with tempfile.TemporaryDirectory() as tmp:
            now = [SLOT + timedelta(minutes=1)]
            rec = history(20)
            c = BriefingsComponent(context=lambda: ctx(), is_trading_day=is_trading_day, store_dir=tmp, clock=lambda: now[0], record=lambda: rec)
            c.tick(weekly=False)
            rec.append(graded("2026-11-16", high=28190.0, low=27880.0, close=27920.0))
            now[0] = SLOT + timedelta(hours=8)
            c.tick(weekly=False)
            f = c.dir / "scores.jsonl"
            f.write_text(f.read_text() + '{"type": "band", "hi', encoding="utf-8")
            c.tick(weekly=False)
            self.assertEqual(c.payload()["score"]["briefs"], 1)
            self.assertEqual(sum(1 for x in f.read_text().splitlines() if x.startswith("{") and x.endswith("}")), 8)

    def test_an_old_format_brief_is_replaced_only_while_its_window_is_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [datetime(2026, 11, 15, 19, 10, tzinfo=NY)]                               # Sunday evening: Monday's Asia brief
            c = BriefingsComponent(context=lambda: dict(ctx(), now=now[0].astimezone(timezone.utc).isoformat(),
                                                        markets=[market(asof=(now[0] - timedelta(minutes=2)).isoformat())]),
                                   is_trading_day=is_trading_day, store_dir=tmp, clock=lambda: now[0])
            old = {"kind": "asia", "title": "Asia session briefing", "slot": datetime(2026, 11, 15, 19, tzinfo=NY).isoformat(),
                   "session": "2026-11-16", "headline": "old words", "markets": []}
            closed = dict(old, kind="nyam", slot=datetime(2026, 11, 13, 9, tzinfo=NY).isoformat(), session="2026-11-13")
            c.dir.mkdir(parents=True, exist_ok=True)
            (c.dir / "2026-11-15-asia.json").write_text(json.dumps(old))
            (c.dir / "2026-11-13-nyam.json").write_text(json.dumps(closed))
            self.assertEqual(c.tick(weekly=False), ["2026-11-15-asia"])                     # old format, window open: replaced
            self.assertEqual(c._load("2026-11-15-asia")["version"], 2)
            self.assertEqual(c._load("2026-11-13-nyam"), closed)                            # its window closed: left as written
            frozen = (c.dir / "2026-11-15-asia.json").read_bytes()
            now[0] += timedelta(hours=1)
            self.assertEqual(c.tick(weekly=False), [])                                      # current format: frozen
            self.assertEqual((c.dir / "2026-11-15-asia.json").read_bytes(), frozen)
            self.assertEqual(c.payload()["score"]["briefs"], 0)                             # the Asia brief is never graded


if __name__ == "__main__":
    unittest.main()
