"""tools/check.py --local: every part stays off the hosts START.bat switches off on this computer."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_tool", ROOT / "tools/check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class Local(unittest.TestCase):
    def test_adds_the_local_hosts_once_and_keeps_others(self):
        self.assertEqual(check.local_env({})["GEX_OFF_HOSTS"], "api.nasdaq.com")
        self.assertEqual(check.local_env({"GEX_OFF_HOSTS": "x.org"})["GEX_OFF_HOSTS"], "x.org,api.nasdaq.com")
        self.assertEqual(check.local_env({"GEX_OFF_HOSTS": "api.nasdaq.com"})["GEX_OFF_HOSTS"], "api.nasdaq.com")

    def test_the_same_hosts_as_start_bat(self):
        bat = (ROOT / "START.bat").read_text(encoding="utf-8")
        self.assertIn(f'set "GEX_OFF_HOSTS={",".join(check.LOCAL_OFF)}"', bat)


if __name__ == "__main__":
    unittest.main()
