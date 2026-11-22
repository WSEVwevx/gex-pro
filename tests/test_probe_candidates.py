"""Candidate sources in the Source probe (2026-11-21): the Nasdaq option chain, proven from GitHub by probe run
44947737421 (NDX 1926, QQQ 1038, SPY 1039 contracts). A candidate isn't used by the app yet, so its failure warns
instead of failing the run."""
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tools import probe_sources as ps

# trimmed raw response, api.nasdaq.com/api/quote/NDX/option-chain, 21 Nov 2026 (as of the 20 Nov close)
RAW = {"data": {"totalRecord": 1926, "lastTrade": "LATEST INDEX VALUE: 25,028.98 (AS OF NOV 20, 2026)", "table": {"rows": [
    {"expiryDate": "Nov 23", "c_Last": "6.00", "c_Bid": "0.85", "c_Ask": "15.20", "c_Volume": "28", "c_Openinterest": "--",
     "strike": "26,940.00", "p_Last": "452.70", "p_Bid": "1,569.30", "p_Ask": "1,969.10", "p_Volume": "--",
     "p_Openinterest": "16", "drillDownURL": "/market-activity/index/ndx/option-chain/call-put-options/ndxp--261123c26940000"}]}}}


class ProbeCandidates(unittest.TestCase):
    def rows(self):
        return [s for s in ps.SOURCES if s[0].startswith("Nasdaq") and s[0].endswith("options (candidate)")]

    def test_the_three_nasdaq_chains(self):
        self.assertEqual([s[0] for s in self.rows()], [f"Nasdaq {x} options (candidate)" for x in ("NDX", "QQQ", "SPY")])
        for name, url, headers, check, backup in self.rows():
            self.assertTrue(url.startswith("https://api.nasdaq.com/api/quote/"))
            self.assertNotIn("key", url.lower())                         # free, keyless
            self.assertEqual(check(json.dumps(RAW).encode()), "1926 contracts")

    def test_an_empty_chain_is_not_ok(self):
        for empty in ({"data": {"totalRecord": 0}}, {"data": {"totalRecord": None}}, {"data": None}):
            for name, url, headers, check, backup in self.rows():
                with self.assertRaises((ValueError, TypeError)):
                    check(json.dumps(empty).encode())

    def run_main(self, ok_names):
        def probe(name, url, headers, check):
            return (name in ok_names, "ok" if name in ok_names else "HTTP 403", 0.1)
        out = io.StringIO()
        with mock.patch.object(ps, "probe", probe), redirect_stdout(out):
            code = ps.main()
        return code, out.getvalue()

    def test_a_failing_candidate_warns(self):
        names = {s[0] for s in ps.SOURCES}
        code, out = self.run_main(names - {"Nasdaq NDX options (candidate)"})
        self.assertEqual(code, 0)
        self.assertIn("RESULT: PASS", out)
        self.assertRegex(out, r"WARN Nasdaq NDX options \(candidate\).*candidate, not used yet")

    def test_a_failing_source_still_fails(self):
        names = {s[0] for s in ps.SOURCES}
        code, out = self.run_main(names - {"OCC NDX open interest"})
        self.assertEqual(code, 1)
        self.assertIn("FAIL OCC NDX open interest", out)


if __name__ == "__main__":
    unittest.main()
