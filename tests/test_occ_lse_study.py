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


if __name__ == "__main__":
    unittest.main()
