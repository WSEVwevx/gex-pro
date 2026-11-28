"""Study occ_lse_accuracy v1 (rework workstream 7): the definition is fixed before any result, so its hash is pinned.
A change to the study is a new version file, never an edit of this one."""
import hashlib
import json
import unittest
from pathlib import Path

DEF = Path(__file__).resolve().parents[1] / "studies/occ_lse_accuracy/v1.json"
SHA = "607b25a66a54b3df619c9bd436ee6ab427d6f0e496a01879baf7f5b58d641737"     # shown to the owner before any result


class Definition(unittest.TestCase):
    def test_unchanged_since_it_was_written(self):
        self.assertEqual(hashlib.sha256(DEF.read_bytes().replace(b"\r\n", b"\n")).hexdigest(), SHA)

    def test_what_it_fixes(self):
        d = json.loads(DEF.read_text(encoding="utf-8"))
        self.assertEqual((d["study"], d["version"], d["seed"]), ("occ_lse_accuracy", 1, 20261128))
        self.assertIn("8 pairs", d["pass_bar_proposed"]["minimum_n"])
        self.assertIn("not possible: no historical OI", d["B_levels_on_cboe_days"]["result_before_running"])
        self.assertIn("paste stays held", d["pass_bar_proposed"]["unlocks"])

    def test_the_owner_approved_this_exact_definition(self):
        a = json.loads((DEF.parent / "approval.json").read_text(encoding="utf-8"))
        self.assertEqual((a["approves_sha256"], a["owner"]), (SHA, "Approve pass bar"))


V2 = DEF.parent / "v2.json"
SHA2 = "a75e602dedb2f70cad45ad8785d69f0347d7e0edab4f72b215f356febe9cffc0"   # shown before any LSE call or result


class Version2(unittest.TestCase):
    def test_unchanged_and_the_same_bar(self):
        self.assertEqual(hashlib.sha256(V2.read_bytes().replace(b"\r\n", b"\n")).hexdigest(), SHA2)
        d = json.loads(V2.read_text(encoding="utf-8"))
        self.assertEqual((d["version"], d["seed"]), (2, 20261128))
        self.assertIn("identical to v1", d["pass_bar"])


class Runner(unittest.TestCase):
    """tools/stress/occ_lse_accuracy.py on synthetic prints shaped like LSE's flow rows (no LSE value here)."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("occ_lse_acc", DEF.parents[2] / "tools/stress/occ_lse_accuracy.py")
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)

    def test_after_close_window(self):
        from datetime import date, datetime, timezone
        u = lambda *a: datetime(*a, tzinfo=timezone.utc)
        self.assertEqual(self.m.session_after_close(u(2026, 11, 9, 21, 15)), date(2026, 11, 9))     # 16:15 EST
        self.assertIsNone(self.m.session_after_close(u(2026, 11, 9, 21, 14)))
        self.assertEqual(self.m.session_after_close(u(2026, 11, 10, 14, 29)), date(2026, 11, 9))    # 09:29 next day
        self.assertIsNone(self.m.session_after_close(u(2026, 11, 10, 14, 30)))
        self.assertEqual(self.m.session_after_close(u(2026, 11, 28, 2, 0)), date(2026, 11, 27))    # early close
        self.assertEqual(self.m.next_session(date(2026, 11, 25)), date(2026, 11, 27))             # Thanksgiving

    def test_prints_collapse_to_the_last_one_with_summed_size(self):
        pr = lambda ts, k, t, iv, size, s=100.0: {"ts": ts, "strike": k, "contract_type": t, "iv": iv, "size": size,
                                                   "underlying_price": s, "expiry": "2026-11-10"}
        rows, dropped = self.m.collapse([pr("2026-11-09 20:59:00.5", 101, "call", 0.20, 3, 100.5),
                                         pr("2026-11-09 20:30:00.1", 101, "call", 0.30, 4),
                                         pr("2026-11-09 20:40:00", 99, "put", 0.25, 2, None),
                                         pr("bad", 99, "put", 0.25, 2)], price_at=lambda ts: None)
        self.assertEqual(dropped, 2)                          # an unreadable time; a put with no price anywhere
        (r,) = rows
        self.assertEqual((r["iv"], r["volume_today"], r["greeks_underlying_price"]), (0.20, 7, 100.5))
        rows, _ = self.m.collapse([pr("2026-11-09 20:40:00", 99, "put", 0.25, 2, None)], price_at=lambda ts: 99.5)
        self.assertEqual(rows[0]["greeks_underlying_price"], 99.5)

    def test_the_bar(self):
        self.assertEqual(self.m.verdict([-1.0] * 7, (-2, -1)), "can't tell (n too small)")
        self.assertEqual(self.m.verdict([-1.0] * 8, (-2, -0.1)), "better")
        self.assertEqual(self.m.verdict([-1.0] * 5 + [1.0] * 3, (-2, -0.1)), "no worse (not better)")   # 62% closer
        self.assertEqual(self.m.verdict([-1.0] * 8, (-2, 0.1)), "no worse (not better)")                # CI reaches 0
        self.assertEqual(self.m.verdict([1.0] * 8, (0.5, 1.5)), "no better")


if __name__ == "__main__":
    unittest.main()
