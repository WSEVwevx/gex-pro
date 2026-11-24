"""Parity replay (decision 001, phase B, rework method 7.3): the engine on saved inputs at five frozen backup clocks,
behind a network guard, gives byte-identical output run after run; compare finds any difference by path.

The replay runs in a subprocess: it freezes the clock and blocks the network for its whole process.
Inputs: tests/fixtures/parity/2026-11-20 (OCC open interest and VIX-family closes as of the 20 Nov close, trimmed to
46 days and +-10% of the close; prices frozen from the archive's 1-minute bars; QQQ/SPY merge not covered).
"""
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import parity  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "parity" / "2026-11-20"


def replay(out: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "tools" / "parity.py"), "run", "--inputs", str(FIX), "--out", str(out)],
                          capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=600)


class ParityReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        cls.a, cls.b = t / "a", t / "b"
        cls.ra, cls.rb = replay(cls.a), replay(cls.b)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_runs_clean_with_no_request(self):
        for r in (self.ra, self.rb):
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)          # 3 = a request reached the guard
            self.assertNotIn("network attempts", r.stdout)

    def test_every_clock_and_market_has_an_output_with_its_state(self):
        names = sorted(p.name for p in self.a.glob("*.json"))
        self.assertEqual(len(names), len(parity.CLOCKS) * len(parity.MARKETS))
        for tag, wall, want in parity.CLOCKS:
            for m, _, _ in parity.MARKETS:
                d = json.loads((self.a / f"{tag}-{m}.json").read_text(encoding="utf-8"))
                self.assertEqual((d["clock"], d["state"]), (wall, want))
                self.assertIn("summary", d["result"], f"{tag} {m}: {d['result'].get('error')}")

    def test_byte_identical_run_after_run(self):
        self.assertEqual(parity.compare(self.a, self.b), [])
        for p in self.a.glob("*.json"):
            self.assertEqual(p.read_bytes(), (self.b / p.name).read_bytes(), p.name)

    def test_compare_finds_a_change_by_path_and_honours_excludes(self):
        with tempfile.TemporaryDirectory() as t:
            c = Path(t)
            for p in self.a.glob("*.json"):
                (c / p.name).write_bytes(p.read_bytes())
            n = sorted(c.glob("*.json"))[0]
            d = json.loads(n.read_text(encoding="utf-8"))
            net = d["result"]["summary"]["net"]
            d["result"]["summary"]["net"] = math.nextafter(net, math.inf)  # one float step: the smallest change counts
            d["built"] = "now"                                          # excluded by name
            n.write_text(parity.canonical(d), encoding="utf-8")
            problems = parity.compare(self.a, c)
            self.assertEqual(len(problems), 1)
            self.assertIn("$.result.summary.net", problems[0])

    def test_the_inputs_hold_no_unsaved_source(self):
        prices = json.loads((FIX / "prices.json").read_text(encoding="utf-8"))
        self.assertEqual(set(prices["yahoo"]), {"^NDX", "^GSPC"})               # QQQ/SPY: not covered, never invented
        self.assertTrue(all(f.stat().st_size < 400_000 for f in FIX.iterdir()))


class Guard(unittest.TestCase):
    def test_a_request_is_blocked_and_counted(self):
        code = ("import sys, socket, urllib.request; sys.path.insert(0, 'tools'); import parity; parity.guard()\n"
                "for f in (lambda: urllib.request.urlopen('https://example.com'), lambda: socket.create_connection(('example.com', 443))):\n"
                "    try: f(); print('REACHED')\n"
                "    except parity.NetworkBlocked: pass\n"
                "print(len(parity.ATTEMPTS))")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, timeout=60)
        self.assertEqual(r.stdout.split(), ["2"], r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
