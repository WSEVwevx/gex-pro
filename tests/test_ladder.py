"""GEX live table: every exposure lands in exactly one expiration, rows are evenly spaced around price."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from gexsys import ladder
from gexsys.service import MarketWorker
from tests.test_integration import synth_cfg


class TestLadder(unittest.TestCase):
    def test_totals_rows_and_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = MarketWorker(synth_cfg(tmp))
            w.step()
            L = w.result["ladder"]
        s = w.result["summary"]
        self.assertAlmostEqual(sum(e["net"] for e in L["expirations"]), s["net"], delta=abs(s["net"]) * 1e-6 + 2 * len(L["expirations"]))
        ks = [r["k"] for r in L["rows"]]
        self.assertEqual(ks, sorted(ks, reverse=True))                       # highest strike first, like a ladder
        self.assertTrue(all(abs(k - L["spot"]) <= ladder.WINDOW * L["spot"] + L["width"] for k in ks))
        self.assertTrue(all(abs((k / L["width"]) - round(k / L["width"])) < 1e-6 for k in ks))
        cell = next(iter(L["rows"][len(ks) // 2]["x"].values()))
        self.assertEqual(len(cell), len(L["fields"]))
        self.assertGreaterEqual(min(cell[2:]), 0)                             # OI and volume are counts

    def test_expiry_strip_selection(self):
        ny = timezone(timedelta(hours=-4))
        days = [datetime(2026, 10, d, 16, tzinfo=ny) for d in (26, 27, 28, 29, 30)] + \
               [datetime(2026, 11, 20, 9, 30, tzinfo=ny), datetime(2026, 11, 20, 16, tzinfo=ny), datetime(2026, 11, 24, 16, tzinfo=ny)]
        got = ladder.pick_expirations(days)
        self.assertEqual(got[:3], days[:3])                                   # the 3 nearest
        self.assertIn(days[4], got)                                           # a Friday
        self.assertIn(days[5], got)                                           # the monthly (AM and PM)
        self.assertNotIn(days[3], got)                                        # a Thursday after the first 3
        self.assertNotIn(days[7], got)                                        # a Tuesday after the first 3
        self.assertTrue(ladder._monthly(days[6].date()))
        self.assertEqual(ladder.band_width(29000.0), 40)                          # NDX: 40-point rows
        self.assertEqual(ladder.band_width(7650.0), 10)                           # SPX: 10-point rows


if __name__ == "__main__":
    unittest.main()
