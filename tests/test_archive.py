"""The history archive (gexpro/archive.py): which snapshots are kept, the bars, the manifest, append-only."""
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from gexpro import context
from gexsys import marketcal
from gexpro import archive as A

NY = marketcal.NY
D = date(2026, 11, 18)                     # a Wednesday, full session
EARLY = date(2026, 11, 27)                 # the day after Thanksgiving: 13:00 close


def et(d, hh, mm, ss=0):
    return datetime.combine(d, time(hh, mm, ss), NY)


def cand(t, usable=True):
    return {"file": t.astimezone(timezone.utc).strftime("%Y%m%d/%H%M%S_000000.json"), "asof": t.isoformat(),
            "status": "OK" if usable else "UNAVAILABLE", "usable": usable}


def save_snap(folder: Path, t: datetime, usable=True):
    u = t.astimezone(timezone.utc)
    f = folder / u.strftime("%Y%m%d") / u.strftime("%H%M%S_000000.json")
    f.parent.mkdir(parents=True, exist_ok=True)
    s = {"asof": t.isoformat(), "status": "OK" if usable else "UNAVAILABLE", "zero_gamma": 1.0,
         "extras": {"expected_move": {"daily_points": 100.0 if usable else None}}, "futures_map": {"factor": 1.003, "offset": 0}}
    f.write_text(json.dumps(s), encoding="utf-8")
    return f


def yahoo(ts_from, n, price=100.0):
    ts = [ts_from + 60 * i for i in range(n)]
    q = {"open": [price] * n, "high": [price + 1] * n, "low": [price - 1] * n, "close": [price + .5] * n, "volume": [7] * n}
    q["close"][1] = None                   # an empty bar: left out
    return json.dumps({"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [q]}}]}}).encode()


def fake_get(url):
    p1 = int(url.split("period1=")[1].split("&")[0])
    return yahoo(p1, 5)


class TestChoose(unittest.TestCase):
    def test_open_is_last_usable_before_0930(self):
        cs = [cand(et(D, 9, 0)), cand(et(D, 9, 29, 59)), cand(et(D, 9, 29, 59) + timedelta(microseconds=1), usable=False),
              cand(et(D, 9, 30))]
        self.assertEqual(A.choose(cs, D)["open"]["asof"], et(D, 9, 29, 59).isoformat())

    def test_open_window_is_the_plans(self):
        self.assertEqual(A.PRE_OPEN_WINDOW, context.PRE_OPEN_WINDOW)
        self.assertIsNone(A.choose([cand(et(D, 9, 30) - timedelta(hours=30, seconds=1))], D)["open"])

    def test_midday_nearest_noon_ties_take_the_earlier(self):
        cs = [cand(et(D, 11, 50)), cand(et(D, 12, 10)), cand(et(D, 12, 5), usable=False)]
        self.assertEqual(A.choose(cs, D)["midday"]["asof"], et(D, 11, 50).isoformat())
        self.assertIsNone(A.choose([cand(et(D, 12, 31))], D)["midday"])

    def test_close_respects_early_close(self):
        cs = [cand(et(EARLY, 12, 45)), cand(et(EARLY, 13, 0)), cand(et(EARLY, 13, 5))]
        self.assertEqual(A.choose(cs, EARLY)["close"]["asof"], et(EARLY, 13, 0).isoformat())
        self.assertIsNone(A.choose([cand(et(D, 14, 59))], D)["close"])

    def test_candidates_read_across_utc_days_and_skip_chains(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp)
            save_snap(f, et(D, 9, 30) - timedelta(hours=31))           # outside the window
            save_snap(f, et(D - timedelta(days=1), 20, 0))              # the next UTC day's folder
            save_snap(f, et(D, 15, 59), usable=False)
            (f / "20261118").mkdir(exist_ok=True)
            (f / "20261118" / "x.chain.json").write_text("{}")
            cs = A.candidates(f, D)
            self.assertEqual([c["usable"] for c in cs], [True, False])
            self.assertEqual(cs[0]["file"], "20261118/010000_000000.json")


class TestBars(unittest.TestCase):
    def test_parse_drops_empty_bars(self):
        self.assertEqual(len(A.parse_bars(yahoo(960, 4))), 3)

    def test_parse_drops_the_live_quote_row_off_the_minute(self):
        raw = json.loads(yahoo(1795039080, 2))                         # 16:58, 16:59 ET (the 16:59 one is empty)
        r = raw["chart"]["result"][0]
        r["timestamp"].append(1795039199)                               # 16:59:59: Yahoo's quote row, seen 2026-11-18
        for k, v in r["indicators"]["quote"][0].items():
            v.append(7340.25 if k != "volume" else 0)
        self.assertEqual([b[0] for b in A.parse_bars(json.dumps(raw).encode())], [1795039080])

    def test_contract_switch_at_quarterly_expiry(self):
        exp = date(2026, 12, 18)
        bars = [[int(et(exp, 9, 29).timestamp())] + [1] * 5, [int(et(exp, 9, 30).timestamp())] + [1] * 5]
        self.assertEqual([s["contract"] for s in A.contract_segments("NQ", bars)], ["NQZ6", "NQH7"])

    def test_roll_week(self):
        self.assertEqual([A.roll_week(date(2026, 12, d)) for d in (9, 10, 18, 21)], [False, True, True, False])

    def test_futures_window_is_the_globex_day(self):
        lo, hi = A.futures_window(date(2026, 11, 23))                    # a Monday: from Friday's reopen (Sunday open inside)
        self.assertEqual((lo, hi), (et(date(2026, 11, 20), 18, 0), et(date(2026, 11, 23), 17, 0)))
        lo, _ = A.futures_window(date(2027, 1, 19))                      # the Tuesday after MLK Day: Monday's Globex morning inside
        self.assertEqual(lo, et(date(2027, 1, 15), 18, 0))

    def test_file_names(self):
        self.assertEqual([A.file_name(s) for s in ("NQ=F", "^GSPC")], ["NQF-1m.json", "GSPC-1m.json"])


class TestDays(unittest.TestCase):
    def test_due_after_1715_skipping_holidays_and_what_exists(self):
        self.assertEqual(A.due_days(et(D, 17, 14), set()), [])
        self.assertEqual(A.due_days(et(D, 17, 15), set()), [D])
        got = A.due_days(et(date(2026, 11, 27), 18, 0), {"2026-11-20"})
        self.assertEqual(got, [date(2026, 11, d) for d in (23, 24, 25, 27)])      # 7-day lookback, Thanksgiving skipped

    def test_missing_only_after_1800(self):
        self.assertEqual(A.missing_days(et(D, 17, 59), set()), [])
        self.assertEqual(A.missing_days(et(D, 18, 0), set()), ["2026-11-18"])

    def test_append_only(self):
        self.assertEqual(A.append_only_violations("A\tdays/a\nA\tdays/b\n"), [])
        self.assertEqual(A.append_only_violations("A\tx\nM\tdays/a\nD\tdays/b"), ["M\tdays/a", "D\tdays/b"])


class TestBuildDay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folders = {m: Path(self.tmp.name) / m for m in ("NQ", "ES")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_day_and_manifest_hashes(self):
        for f in self.folders.values():
            for t in (et(D, 9, 20), et(D, 12, 2), et(D, 15, 50)):
                save_snap(f, t)
        files, gaps = A.build_day(D, self.folders, et(D, 17, 20), get=fake_get, commit="abc")
        self.assertEqual(gaps, [])
        man = json.loads(files["days/2026-11-18/manifest.json"])
        self.assertEqual(len(man["files"]), 2 * (3 + 1 + 2))
        for n, meta in man["files"].items():
            b = files[f"days/2026-11-18/{n}"]
            self.assertEqual((hashlib.sha256(b).hexdigest(), len(b)), (meta["sha256"], meta["bytes"]))
        self.assertEqual(files["days/2026-11-18/NQ-open.json"],
                         (self.folders["NQ"] / man["chosen"]["NQ"]["open"]["file"]).read_bytes())
        nqf = json.loads(files["days/2026-11-18/NQF-1m.json"])
        self.assertEqual((len(nqf["bars"]), nqf["contracts"][0]["contract"], nqf["roll_week"]), (4, "NQZ6", False))

    def test_waits_for_missing_parts_then_names_them(self):
        save_snap(self.folders["NQ"], et(D, 9, 20))
        self.assertIsNone(A.build_day(D, self.folders, et(D, 17, 20), get=fake_get)[0])
        files, gaps = A.build_day(D, self.folders, et(D + timedelta(days=3), 17, 15), get=fake_get)
        man = json.loads(files["days/2026-11-18/manifest.json"])
        self.assertIn("NQ midday snapshot: no usable snapshot within 30 minutes of 12:00 ET", man["missing"])
        self.assertIn("ES open snapshot: no usable snapshot in the 30 hours before 09:30 ET", man["missing"])
        self.assertNotIn("days/2026-11-18/ES-open.json", files)

    def test_failed_bars_are_named(self):
        def boom(url):
            raise OSError("HTTP Error 429")
        files, gaps = A.build_day(D, self.folders, et(D + timedelta(days=4), 17, 15), get=boom)
        self.assertTrue(any(g.startswith("NQ=F 1-minute bars: OSError: HTTP Error 429") for g in gaps))


class TestHealth(unittest.TestCase):
    def test_rows(self):
        self.assertIsNone(A.health_row(None)["last_ok"])
        idx = A.index_record({}, et(D, 18, 1))
        self.assertIn("1 trading day(s) missing after 18:00 ET: 2026-11-18", A.health_row(idx)["error"])
        ok = A.index_record({"2026-11-18": {"files": {"NQ-open.json": {}}, "missing": []}}, et(D, 18, 1))
        self.assertIsNone(A.health_row(ok)["error"])
        self.assertEqual((ok["markets"]["NQ"]["sessions"], ok["markets"]["ES"]["sessions"]), (1, 0))
        waiting = A.index_record({}, et(D, 18, 1), pending={"2026-11-18": ["NQ=F 1-minute bars: HTTPError 429"]})
        self.assertIn("2026-11-18 (NQ=F 1-minute bars: HTTPError 429)", A.health_row(waiting)["error"])
        early = A.index_record({}, et(D, 17, 30), pending={"2026-11-18": ["x"]})
        self.assertIn("waits for missing parts", A.health_row(early)["note"])
        failed = A.index_record({}, et(D, 17, 0), "RuntimeError: x", last_ok="2026-11-18T20:00:00+00:00")
        self.assertEqual(A.health_row(failed)["last_ok"], "2026-11-18T20:00:00+00:00")


class TestComponent(unittest.TestCase):
    def test_local_says_unavailable_and_hosted_writes_its_file(self):
        c = A.ArchiveComponent()
        self.assertIn("unavailable", c.routes()["/api/archive"]({})[1])
        self.assertEqual(c.sources(), [])                               # no archive step in the local app: no row
        with tempfile.TemporaryDirectory() as tmp:
            data, state = Path(tmp) / "data", Path(tmp) / "state"
            state.mkdir()
            (state / "archive-index.json").write_text(json.dumps(A.index_record({}, et(D, 18, 1))))
            c.build_static(data, state)
            self.assertEqual(json.loads((data / "archive.json").read_text())["missing"], ["2026-11-18"])
            self.assertEqual(c.sources()[0]["name"], "History archive")


def boom(url):
    raise AssertionError("no fetch expected")


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout


class TestRunAgainstARealGitRemote(unittest.TestCase):
    """The hosted step end to end against a local bare repository: two days added in two runs, the first untouched."""

    def test_two_runs_append_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            git(tmp, "init", "-q", "--bare", "origin.git")
            git(tmp / "origin.git", "config", "uploadpack.allowFilter", "true")
            git(tmp, "init", "-q", "work")
            work = tmp / "work"
            git(work, "remote", "add", "origin", (tmp / "origin.git").as_uri())
            state = tmp / "state"
            for k in A.SNAPSHOT_KEYS.values():
                for d in (D, D + timedelta(days=1)):
                    for t in (et(d, 9, 20), et(d, 12, 0), et(d, 15, 55)):
                        save_snap(state / "snapshots" / k, t)
            old = os.getcwd()
            os.chdir(work)
            try:
                i1 = A.run(state, now=et(D, 17, 30), get=fake_get)
                first = git(tmp / "origin.git", "rev-parse", "archive").strip()
                i2 = A.run(state, now=et(D + timedelta(days=1), 17, 30), get=fake_get)
                i3 = A.run(state, now=et(D + timedelta(days=1), 17, 40), get=boom)      # nothing due: no network
                spec = importlib.util.spec_from_file_location("la", Path(__file__).resolve().parent.parent / "tools" / "stress" / "lookahead_audit.py")
                la = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(la)
                audit = la.audit_archive()                                  # A1-A3 on the branch just written
            finally:
                os.chdir(old)
            self.assertEqual((i1["error"], i1["wrote"]), (None, ["2026-11-18"]))
            self.assertEqual((i2["error"], i2["wrote"], i3["wrote"]), (None, ["2026-11-19"], []))
            self.assertEqual(i2["markets"]["NQ"], {"sessions": 2, "from": "2026-11-18", "through": "2026-11-19"})
            second = git(tmp / "origin.git", "rev-parse", "archive").strip()
            diff = git(tmp / "origin.git", "diff", "--no-renames", "--name-status", first, second)
            self.assertEqual(A.append_only_violations(diff), [])
            self.assertEqual(len(diff.splitlines()), 13)
            self.assertEqual(audit, [])


if __name__ == "__main__":
    unittest.main()
