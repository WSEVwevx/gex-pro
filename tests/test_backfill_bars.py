"""tools/backfill_bars.py: a saved raw Yahoo response becomes an archive-format file marked "backfilled"; days the
archive covers are refused; an existing file is never replaced."""
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import backfill_bars as B  # noqa: E402

from gexpro import archive as A


def yahoo(ts):
    q = {"open": [10.0, 11.0, None], "high": [12.0, 12.5, 13.0], "low": [9.0, 10.5, 11.0], "close": [11.0, 12.0, 12.0],
         "volume": [5, None, 1]}
    return json.dumps({"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [q]}}]}}).encode()


class TestRecord(unittest.TestCase):
    def test_archive_format_marked_backfilled(self):
        d = date(2026, 10, 21)
        lo, hi = A.futures_window(d)
        t0 = int(lo.timestamp())
        raw = yahoo([t0 - 60, t0, t0 + 60])                      # one bar before the Globex day, one without an open
        at = datetime(2026, 11, 19, 5, 4, 55, tzinfo=timezone.utc)
        rel, rec = B.record("2026-10-21_NQF-1m.json", raw, at)
        self.assertEqual(rel, "2026-10-21/NQF-1m.json")
        self.assertEqual(rec["bars"], [[t0, 11.0, 12.5, 10.5, 12.0, 0]])
        want = A.bar_record("NQ", "NQ=F", d, lo, hi, [[t0, 11.0, 12.5, 10.5, 12.0, 0]])
        self.assertEqual({k: v for k, v in rec.items() if k != "backfilled"}, want)
        self.assertEqual(rec["backfilled"]["downloaded_at"], "2026-11-19T05:04:55+00:00")
        self.assertEqual(rec["backfilled"]["raw_sha256"], hashlib.sha256(raw).hexdigest())

    def test_refuses_archive_days_and_empty_days(self):
        lo, _ = A.futures_window(A.FIRST_DAY)
        with self.assertRaisesRegex(ValueError, "archive covers"):
            B.record(f"{A.FIRST_DAY}_ESF-1m.json", yahoo([int(lo.timestamp())]), datetime.now(timezone.utc))
        with self.assertRaisesRegex(ValueError, "no bars"):
            B.record("2026-10-21_ESF-1m.json", yahoo([0, 60, 120]), datetime.now(timezone.utc))

    def test_never_replaces_a_file(self):
        lo, _ = A.futures_window(date(2026, 10, 22))
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            (Path(src) / "2026-10-22_ESF-1m.json").write_bytes(yahoo([int(lo.timestamp()) + 60 * i for i in range(3)]))
            (Path(out) / "2026-10-22").mkdir()
            (Path(out) / "2026-10-22" / "ESF-1m.json").write_text("kept")
            with mock.patch.object(B, "OUT", Path(out)), mock.patch.object(B, "MANIFEST", Path(out) / "m.json"),                     mock.patch("builtins.print"):
                B.main([src])
            self.assertEqual((Path(out) / "2026-10-22" / "ESF-1m.json").read_text(), "kept")


class TestCommittedFiles(unittest.TestCase):
    def test_every_backfill_file_is_before_the_archive_and_marked(self):
        files = sorted(B.OUT.glob("*/*.json"))
        for p in files:
            rec = json.loads(p.read_bytes())
            self.assertLess(date.fromisoformat(p.parent.name), A.FIRST_DAY)
            self.assertEqual((rec["session"], rec["symbol"]), (p.parent.name, {"NQF-1m.json": "NQ=F", "ESF-1m.json": "ES=F"}[p.name]))
            self.assertIn("raw_sha256", rec["backfilled"])
            self.assertTrue(all(rec["from"] <= b[0] < rec["to"] for b in rec["bars"]))

    def test_files_match_their_manifest(self):
        man = json.loads(B.MANIFEST.read_text())
        self.assertEqual(sorted(man), sorted(f"{p.parent.name}/{p.name}" for p in B.OUT.glob("*/*.json")))
        for rel, m in man.items():
            b = (B.OUT / rel).read_bytes()
            self.assertEqual((hashlib.sha256(b).hexdigest(), len(b)), (m["sha256"], m["bytes"]), rel)
            self.assertEqual(json.loads(b)["backfilled"]["raw_sha256"], m["raw_sha256"])


if __name__ == "__main__":
    unittest.main()
