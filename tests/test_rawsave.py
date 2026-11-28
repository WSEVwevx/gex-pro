"""The morning save (gexpro/rawsave.py): GitHub keeps the OCC estimate's raw inputs from before each open, so a
morning the PC slept through can be rebuilt (docs/prompts/private-app.md, W1). Synthetic data, no network."""
import hashlib
import http.client
import json
import os
import unittest
from datetime import date, datetime, timezone
from unittest import mock

from gexpro import rawsave
from gexsys import marketcal
from gexsys.providers.occ import OccProvider
from tests.test_occ_chain import ndx_pages, opener_for

UTC = timezone.utc


def et(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=marketcal.NY)


class Window(unittest.TestCase):
    def test_trading_mornings_only_from_five_until_the_open(self):
        self.assertEqual(rawsave.due(et(2026, 11, 30, 5, 0)), date(2026, 11, 30))     # Monday, EST
        self.assertEqual(rawsave.due(et(2026, 11, 30, 9, 29)), date(2026, 11, 30))
        self.assertIsNone(rawsave.due(et(2026, 11, 30, 9, 30)))                       # the open: too late
        self.assertIsNone(rawsave.due(et(2026, 11, 30, 4, 59)))
        self.assertIsNone(rawsave.due(et(2026, 11, 26, 8, 0)))                        # Thanksgiving
        self.assertIsNone(rawsave.due(et(2026, 11, 28, 8, 0)))                        # Saturday
        self.assertEqual(rawsave.due(et(2026, 7, 6, 9, 0)), date(2026, 7, 6))         # EDT: same ET window
        self.assertEqual(rawsave.due(datetime(2026, 7, 6, 13, 0, tzinfo=UTC)), date(2026, 7, 6))    # 09:00 EDT
        self.assertIsNone(rawsave.due(datetime(2026, 12, 1, 14, 30, tzinfo=UTC)))     # 09:30 EST

    def test_nothing_is_fetched_outside_the_window(self):
        get = mock.Mock()
        with mock.patch.dict(os.environ):
            self.assertEqual(rawsave.run(et(2026, 11, 28, 8, 0), get=get, do_push=False),
                             {"session": None, "saved": [], "failed": []})
        get.assert_not_called()


class Fetch(unittest.TestCase):
    def test_bytes_kept_as_they_came_and_a_failure_is_named(self):
        now = et(2026, 11, 30, 8, 5)
        body = b"Series Search Results\tNDX\r\n\xff raw"

        def get(url):
            if "symbol=SPY" in url:
                return 403, b""
            if "VIX1D" in url:
                raise OSError("timed out")
            if "VIX9D" in url:
                raise http.client.IncompleteRead(b"par")
            return 200, body
        files = rawsave.fetch(now, get)
        folder = "days/2026-11-30/130500Z"
        self.assertEqual(files[f"{folder}/occ_NDX.txt"], body)                      # byte for byte
        man = json.loads(files[f"{folder}/manifest.json"])
        self.assertEqual((man["session"], man["fetched_at"], man["rules"]), ("2026-11-30", "2026-11-30T13:05:00+00:00", 1))
        self.assertEqual(man["files"]["occ_NDX"]["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(man["files"]["occ_SPY"]["error"], "HTTP 403")
        self.assertIn("OSError: timed out", man["files"]["yvol_VIX1D"]["error"])
        self.assertIn("IncompleteRead", man["files"]["yvol_VIX9D"]["error"])
        self.assertNotIn(f"{folder}/occ_SPY.txt", files)
        self.assertEqual(len(files), len(rawsave.inputs()) - 3 + 1)

    def test_a_run_reports_what_failed(self):
        with mock.patch.dict(os.environ):
            res = rawsave.run(et(2026, 11, 30, 8, 5), get=lambda u: (200, b"") if "QQQ" in u else (200, b"x"), do_push=False)
            self.assertEqual(os.environ.get("GEX_NO_LSE"), "1")                      # LSE stays off on GitHub
        self.assertEqual(res["session"], "2026-11-30")
        self.assertEqual(res["failed"], ["occ_QQQ (HTTP 200, empty)", "price_QQQ (HTTP 200, empty)"])


class SameUrlsAsTheProvider(unittest.TestCase):
    def test_every_url_the_occ_estimate_asks_for_is_saved(self):
        """A replay serves only saved bytes: if the provider asked for a URL the save does not keep, a rebuilt
        morning would fail. NDX asks for the most (VXN too); SPX is the same pages without VXN."""
        asked = []
        op = opener_for(ndx_pages())

        def rec(req, timeout=None):
            asked.append(req.full_url)
            return op(req, timeout)
        clock = lambda: datetime(2026, 11, 20, 13, 0, tzinfo=UTC).timestamp()      # Friday 08:00 ET
        with mock.patch.dict(os.environ, {"GEX_NO_LSE": "1"}):
            OccProvider(opener=rec, clock=clock).fetch_snapshot("NDX")
        saved = set(rawsave.inputs().values())
        self.assertTrue(asked)
        self.assertEqual([u for u in asked if u not in saved], [])

    def test_no_lse_anywhere_in_what_github_saves(self):
        self.assertFalse([u for u in rawsave.inputs().values() if "londonstrategicedge" in u])
        from pathlib import Path
        src = Path(rawsave.__file__).read_text(encoding="utf-8")
        self.assertNotIn("providers.lse", src)
        self.assertNotIn("London Strategic Edge", src)


class AppendOnly(unittest.TestCase):
    def test_an_existing_path_is_never_overwritten(self):
        calls = []

        def git(*a, inp=None, env=None):
            calls.append(a)
            if a[0] == "ls-remote":
                return "abc refs/heads/raw"
            if a[0] == "rev-parse":
                return "tip"
            if a[0] == "ls-tree":
                return a[-1]                                    # every path "exists"
            return ""
        with mock.patch.object(rawsave, "_git", git), self.assertRaisesRegex(RuntimeError, "append-only"):
            rawsave.push({"days/2026-11-30/130500Z/occ_NDX.txt": b"x"}, "m")
        self.assertFalse([c for c in calls if c[0] == "push"])

    def test_a_lost_race_is_retried_on_the_new_tip(self):
        pushes = []

        def git(*a, inp=None, env=None):
            if a[0] == "ls-remote":
                return "abc refs/heads/raw"
            if a[0] == "rev-parse":
                return f"tip{len(pushes)}"
            if a[0] == "ls-tree":
                return ""                                       # the new path is not there yet
            if a[0] == "push":
                pushes.append(a)
                if len(pushes) == 1:
                    raise RuntimeError("git push: rejected (fetch first)")
            return "obj"
        with mock.patch.object(rawsave, "_git", git):
            rawsave.push({"days/x/y.txt": b"x"}, "m")
        self.assertEqual(len(pushes), 2)


if __name__ == "__main__":
    unittest.main()
