"""NQ / ES drivers: weights, extended hours, average volume, earnings, points contribution, fallbacks."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from feeds import drivers as D


def weights_html(rows):
    return "".join(f'<tr><td>{i}</td><td style="x"><a href="/symbol/{s}">{n}</a></td><td><a href="/symbol/{s}">{s}</a></td>'
                   f'<td>{w}%</td></tr>' for i, (s, n, w) in enumerate(rows, 1))


def intraday(price, prev, last=None, last_t=None, vol=1000, start=100, end=200):
    ts, cl = [150], [price]
    if last is not None:
        ts.append(last_t)
        cl.append(last)
    return json.dumps({"chart": {"result": [{"meta": {"regularMarketPrice": price, "chartPreviousClose": prev, "regularMarketVolume": vol,
                                                       "currentTradingPeriod": {"regular": {"start": start, "end": end}}},
                                              "timestamp": ts, "indicators": {"quote": [{"close": cl}]}}]}}).encode()


def daily(vols, closes):
    return json.dumps({"chart": {"result": [{"indicators": {"quote": [{"volume": vols, "close": closes}]}}]}}).encode()


class Net:
    """Fake internet: URL substring -> bytes (missing -> error)."""
    def __init__(self, table):
        self.table, self.calls = table, []

    def __call__(self, req, timeout=None):
        self.calls.append(req.full_url)
        for k, v in self.table.items():
            if k in req.full_url:
                return io.BytesIO(v)
        raise OSError("down")


def world(**over):
    nq = [("NVDA", "Nvidia", 12.0), ("AAPL", "Apple", 10.0), ("ASML", "ASML", 2.0)] + [(f"Q{i}", "x", 0.1) for i in range(60)]
    es = [("NVDA", "Nvidia", 7.0), ("AAPL", "Apple", 6.0), ("BRK.B", "Berkshire", 1.5)] + [(f"S{i}", "x", 0.1) for i in range(60)]
    t = {"nasdaq100": weights_html(nq).encode(), "sp500": weights_html(es).encode(),
         "chart/NQ%3DF?range=1d": intraday(20000, 19900), "chart/ES%3DF?range=1d": intraday(5000, 5000),
         "chart/NVDA?range=1d": intraday(110, 100, last=111.1, last_t=250), "chart/AAPL?range=1d": intraday(99, 100),
         "chart/ASML?range=1d": intraday(50, 50), "chart/BRK-B?range=1d": intraday(400, 400),
         "chart/NVDA?range=3mo": daily([100, 300, 999], [1, 2, 3]),
         "earnings?date=": json.dumps({"data": {"rows": [{"symbol": "AAPL", "time": "time-after-hours"}]}}).encode()}
    t.update(over)
    return t


class TestParsing(unittest.TestCase):
    def test_weights(self):
        self.assertEqual(D.parse_weights(weights_html([("BRK.B", "Berkshire ", 1.5)])), [["BRK.B", "Berkshire", 1.5]])

    def test_extended_hours(self):
        self.assertEqual(D.parse_intraday(intraday(100, 90, last=101, last_t=250))["ext"]["session"], "after")
        self.assertEqual(D.parse_intraday(intraday(100, 90, last=99, last_t=50))["ext"]["session"], "pre")
        self.assertIsNone(D.parse_intraday(intraday(100, 90))["ext"])                   # last bar in the session
        self.assertAlmostEqual(D.parse_intraday(intraday(100, 80))["pct"], 25.0)
        self.assertIsNone(D.parse_intraday(b"{}"))

    def test_daily_excludes_today(self):
        d = D.parse_daily(daily([100, 300, 999], [1, 2, 3]))
        self.assertEqual(d["avg_volume"], 200)
        self.assertEqual(d["spark"], [1, 2])

    def test_earnings(self):
        raw = json.dumps({"data": {"rows": [{"symbol": "MSFT", "time": "time-pre-market"}, {"symbol": "X", "time": "time-not-supplied"}]}}).encode()
        self.assertEqual(D.parse_earnings(raw, "2026-10-28"), {"MSFT": {"date": "2026-10-28", "when": "before open"},
                                                                 "X": {"date": "2026-10-28", "when": ""}})


class TestDrivers(unittest.TestCase):
    def test_universe_points_and_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = D.Drivers(cache_path=Path(tmp) / "c.json", top=3, opener=Net(world())).get()
        rows = {r["symbol"]: r for r in out["stocks"]}
        self.assertEqual(list(rows), ["NVDA", "AAPL", "ASML", "BRK-B"])                  # top 3 of each, merged, Yahoo symbols
        n = rows["NVDA"]
        self.assertAlmostEqual(n["pts_nq"], 0.12 * 0.10 * 20000)                          # weight x move x futures price
        self.assertAlmostEqual(n["pts_es"], 0.07 * 0.10 * 5000)
        self.assertAlmostEqual(n["ext_pts_nq"], 0.12 * 0.01 * 20000)
        self.assertEqual(n["rel_volume"], 1000 / 200)
        self.assertEqual(n["spark"], [1, 2, 110])
        self.assertEqual(rows["AAPL"]["earnings"]["when"], "after close")
        self.assertIsNone(rows["ASML"]["pts_es"])                                        # not in the S&P 500
        self.assertAlmostEqual(out["totals"]["NQ"]["pts"], 240 - 0.10 * 0.01 * 20000)
        self.assertEqual((out["totals"]["NQ"]["up"], out["totals"]["NQ"]["down"]), (1, 1))

    def test_weights_fallback_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            net = Net(world(nasdaq100=b"blocked", sp500=b"blocked"))
            out = D.Drivers(cache_path=Path(tmp) / "c.json", opener=net).get()
            self.assertIn("fallback", out["weights_source"])                              # the bundled copy
            self.assertTrue(out["weights_asof"])
            good = D.Drivers(cache_path=Path(tmp) / "c2.json", top=3, opener=Net(world()))
            good.get()
            again = D.Drivers(cache_path=Path(tmp) / "c2.json", top=3, opener=Net({}))   # offline: weights from the cache
            self.assertEqual([u[0] for u in again.universe()], ["NVDA", "AAPL", "ASML", "BRK-B"])

    def test_cached_and_stale(self):
        now = [1000.0]
        net = Net(world())
        d = D.Drivers(top=3, opener=net, clock=lambda: now[0], ttl_s=60)
        d.get()
        n = len(net.calls)
        d.get()
        self.assertEqual(len(net.calls), n)                                              # inside the ttl
        del net.table["chart/NVDA?range=1d"]
        now[0] += 61
        rows = {r["symbol"]: r for r in d.get()["stocks"]}
        self.assertTrue(rows["NVDA"]["stale"])                                           # last good price kept
        self.assertFalse(rows["AAPL"]["stale"])


if __name__ == "__main__":
    unittest.main()
