"""CFTC positioning: net positions ranked against their own history, and a failing source keeps the last report."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from feeds import positioning as pos


def rows(nets, oi=1000):
    """One raw CFTC row per week, newest first as the API sends them; lev net = n, asset net = -n."""
    d = date(2026, 10, 27)
    out = []
    for i, n in enumerate(reversed(nets)):
        out.append({"report_date_as_yyyy_mm_dd": f"{d - timedelta(weeks=i)}T00:00:00.000", "open_interest_all": str(oi),
                    "lev_money_positions_long": str(100 + n), "lev_money_positions_short": "100",
                    "asset_mgr_positions_long": "100", "asset_mgr_positions_short": str(100 + n)})
    return out


class TestPositioning(unittest.TestCase):
    def test_ranks_against_its_own_history_not_zero(self):
        nets = [-500 + i for i in range(40)]                          # always short, and today the least short of 40 weeks
        s = pos.summarize("ES", pos.parse_rows(rows(nets)))
        lev, asset = s["groups"]
        self.assertEqual(s["asof"], "2026-10-27")
        self.assertEqual((lev["net"], lev["change"], lev["rank"], lev["label"]), (-461, 1, 100, "very long for them"))
        self.assertEqual((asset["net"], asset["rank"], asset["label"]), (461, 0, "very short for them"))
        self.assertEqual(lev["pct_oi"], -46.1)

    def test_labels(self):
        self.assertEqual([pos.label(r) for r in (95, 75, 50, 25, 5)],
                         ["very long for them", "longer than usual", "normal range", "shorter than usual", "very short for them"])

    def test_needs_enough_history_and_skips_bad_rows(self):
        self.assertIsNone(pos.summarize("ES", pos.parse_rows(rows([1] * 10))))
        bad = rows([1] * 30)
        bad[0]["lev_money_positions_long"] = None
        self.assertEqual(len(pos.parse_rows(bad)), 29)

    def test_refreshes_slowly_and_keeps_the_last_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            now, calls = [0.0], []
            def fetch(url):
                calls.append(url)
                if len(calls) > 2:
                    raise OSError("down")
                return json.dumps(rows(list(range(40)))).encode()
            cache = Path(tmp) / "p.json"
            p = pos.Positioning(cache_path=cache, clock=lambda: now[0], fetch=fetch)
            now[0] = 100000.0
            first = p.get()
            self.assertEqual(sorted(first["markets"]), ["ES", "NQ"])
            self.assertIn("13874A", calls[0])
            p.get()
            self.assertEqual(len(calls), 2)                            # inside the refresh time
            now[0] += pos.TTL_S + 1
            self.assertEqual(p.get()["markets"], first["markets"])     # source down: last good report
            again = pos.Positioning(cache_path=cache, clock=lambda: 0.0, fetch=fetch)
            self.assertEqual(again._out["markets"], first["markets"])  # and it survives a restart


if __name__ == "__main__":
    unittest.main()
