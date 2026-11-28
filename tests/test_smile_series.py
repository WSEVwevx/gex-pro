"""Rework workstream 8 (the owner, 2026-11-28: "Yes, unlock both"): the smile estimate (chain occ+lse) feeds a local
plan and Bias and its own track record series, never the main record, the paste, the archive or the hosted site.
Synthetic snapshots only (no LSE value in the repo)."""
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from gexpro import archive, components
from gexpro.context import pre_open
from trackrecord.score import make_plan
from trackrecord.smile_series import SINCE, SmileTrackRecord

D = date(2026, 11, 30)                          # a Monday


def snap(asof, chain, backup="estimate"):
    return {"asof": asof, "status": "OK", "backup": backup, "chain": chain, "ref_price": 26000.0, "underlying": "NDX",
            "regime": "POSITIVE", "net": 1e9, "zero_gamma": {"price": 25800.0}, "call_wall": {"price": 26500.0},
            "put_wall": {"price": 25500.0}, "abs_gamma": {"price": 26000.0},
            "extras": {"expected_move": {"daily_points": 300.0, "daily_iv": 0.2}}}


def gex(tmp, files):
    """One NQ worker whose store holds the given {name: summary} under its own folder."""
    day = Path(tmp) / "NQ-OCCLSE" / "20261130"
    day.mkdir(parents=True)
    for name, s in files.items():
        (day / name).write_text(json.dumps(s), encoding="utf-8")
    w = SimpleNamespace(cfg=SimpleNamespace(market="NQ"), store=SimpleNamespace(root=Path(tmp)), key="NQ-OCCLSE")
    return SimpleNamespace(workers={"NQ-OCCLSE": w})


BIAS = mock.patch("gexpro.context.bias.compute", return_value={"bias": "Bullish", "confidence": "low"})


class PreOpen(unittest.TestCase):
    def test_the_main_record_still_takes_no_estimate(self):
        with tempfile.TemporaryDirectory() as tmp, BIAS:
            g = gex(tmp, {"130000_000000.json": snap("2026-11-30T13:00:00+00:00", "occ+lse")})
            self.assertEqual(pre_open(g, D), {"NQ": None})

    def test_the_smile_series_takes_only_the_smile_and_no_paste(self):
        with tempfile.TemporaryDirectory() as tmp, BIAS:
            g = gex(tmp, {"120000_000000.json": snap("2026-11-30T12:00:00+00:00", "occ+lse"),
                          "130000_000000.json": snap("2026-11-30T13:00:00+00:00", "occ+vix"),       # LSE fell back
                          "150000_000000.json": snap("2026-11-30T15:00:00+00:00", "occ+lse")})      # after 09:30 ET
            got = pre_open(g, D, chain="occ+lse")["NQ"]
            self.assertEqual((got["asof"], got["chain"], got["paste"]), ("2026-11-30T12:00:00+00:00", "occ+lse", None))
            plan = make_plan(got, D.isoformat(), "2026-11-30T15:00:00+00:00")
            self.assertEqual((plan["chain"], plan["bias"], plan["ref"]), ("occ+lse", "Bullish", 26000.0))

    def test_a_main_plan_has_no_chain_key(self):          # the hosted record's files are unchanged
        p = make_plan({"market": "NQ", "ref": 1.0, "em": 1.0}, "2026-11-30", "x")
        self.assertNotIn("chain", p)


class Series(unittest.TestCase):
    def comp(self, tmp, inp):
        return SmileTrackRecord(pre_open=lambda d: {"NQ": inp if d == D else None}, is_trading_day=lambda d: d.weekday() < 5,
                                session_close=lambda d: datetime(d.year, d.month, d.day, 21, tzinfo=timezone.utc),
                                store_dir=Path(tmp), clock=lambda: datetime(2026, 11, 30, 15, 5, tzinfo=timezone.utc))

    def test_its_own_folder_route_and_no_public_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = {"market": "NQ", "underlying": "NDX", "asof": "2026-11-30T12:00:00+00:00", "ref": 26000.0, "em": 300.0,
                   "chain": "occ+lse", "paste": None, "bias": None}
            c = self.comp(tmp, inp)
            self.assertEqual(list(c.routes()), ["/api/trackrecord-smile"])
            self.assertEqual((c.mirror(), c.build_static(Path(tmp), Path(tmp)), c.sources(), c.backtest()), ([], {}, [], {}))
            self.assertIn(f"{D}_NQ frozen", c.tick())
            s = json.loads((Path(tmp) / "sessions" / f"{D}_NQ.json").read_text(encoding="utf-8"))
            self.assertEqual((s["status"], s["plan"]["chain"]), ("pending", "occ+lse"))
            self.assertFalse((Path(tmp) / "pastes").exists())             # the paste stays on hold
            p = c.payload()
            self.assertEqual((p["series"], p["started"], p["stats"]["ALL"]["sessions"]), ("occ+lse", "2026-11-30", 0))
            self.assertIn("London Strategic Edge", p["label"])

    def test_nothing_before_the_owner_said_yes_is_marked_missed(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = self.comp(tmp, None)
            self.assertEqual([x for x in c.tick() if x < SINCE], [])
            self.assertGreaterEqual(c._started(), SINCE)


class Switch(unittest.TestCase):
    def names(self, env):
        with mock.patch.dict(os.environ, env):
            return [c.name for c in components.default_components([])]

    def test_only_where_the_smile_runs(self):
        off = {"GEX_LSE": "", "GITHUB_ACTIONS": "", "GEX_NO_LSE": ""}
        self.assertNotIn("trackrecord_smile", self.names(off))
        self.assertNotIn("trackrecord_smile", self.names(dict(off, GEX_LSE="1", GITHUB_ACTIONS="true")))
        self.assertNotIn("trackrecord_smile", self.names(dict(off, GEX_LSE="1", GEX_NO_LSE="1")))   # the hosted build
        on = self.names(dict(off, GEX_LSE="1"))
        self.assertIn("trackrecord_smile", on)
        self.assertEqual(on[-1], "health")                                   # the health row list is unchanged

    def test_the_routes_do_not_clash(self):
        from gexpro.server import collect_routes
        with mock.patch.dict(os.environ, {"GEX_LSE": "1", "GITHUB_ACTIONS": "", "GEX_NO_LSE": ""}):
            r = collect_routes(components.default_components([]))
        self.assertTrue({"/api/trackrecord", "/api/trackrecord-smile"} <= set(r))


class NeverPublic(unittest.TestCase):
    def test_the_archive_never_keeps_the_smile(self):
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "20261130"
            day.mkdir()
            (day / "130000_000000.json").write_text(json.dumps(snap("2026-11-30T13:00:00+00:00", "occ+lse")), encoding="utf-8")
            (day / "140000_000000.json").write_text(json.dumps(snap("2026-11-30T14:00:00+00:00", "occ+vix")), encoding="utf-8")
            c = archive.candidates(Path(tmp), D)
        self.assertEqual([(x["asof"][11:13], x["usable"], x["estimate"]) for x in c], [("13", False, False), ("14", False, True)])

    def test_the_site_asks_only_locally_and_names_the_credit(self):
        root = Path(__file__).resolve().parents[1]
        js = (root / "dashboard/assets/app.js").read_text(encoding="utf-8")
        self.assertIn('if(STATIC) return;\n  try { const r = await fetchFresh("/api/trackrecord-smile")', js)
        self.assertIn("trkSmile.credit", js)                                  # the credit from the local data only
        from gexsys.providers.lse import CREDIT
        from trackrecord import smile_series
        self.assertEqual(smile_series.CREDIT, CREDIT)
        self.assertIn('id="trkSmile" data-help="track_smile" hidden', (root / "dashboard/index.html").read_text(encoding="utf-8"))


class Brief(unittest.TestCase):
    def test_the_brief_names_the_smile_estimate(self):
        from briefings.morning import market_brief
        m = {"market": "NQ", "price": 26000.0, "asof": "2026-11-30T13:00:00+00:00", "options": "NDX+QQQ", "regime": "POSITIVE",
             "zero_gamma": 25800.0, "call_wall": 26500.0, "put_wall": 25500.0, "abs_gamma": 26000.0, "em": {},
             "nearest": {}, "backup": True, "chain": "occ+lse"}
        b = market_brief(m, [], "2026-11-30", datetime(2026, 11, 30, 13, 30, tzinfo=timezone.utc))
        self.assertIn("each strike's vol from the previous session's smile, Data: London Strategic Edge; not graded", b["data"])
        self.assertTrue(b["backup"])                                          # briefs from an estimate stay ungraded


if __name__ == "__main__":
    unittest.main()
