"""Ticker quotes: parsing, the change from the previous close, caching, and a failed symbol kept as stale."""
import io
import json
import unittest

from feeds.quotes import Quotes, parse


def body(price, prev, t=1792792800):
    return json.dumps({"chart": {"result": [{"meta": {"regularMarketPrice": price, "chartPreviousClose": prev,
                                                     "regularMarketTime": t}}]}}).encode()


class FakeOpener:
    def __init__(self, table):
        self.table, self.calls = table, 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        sym = req.full_url.split("/chart/")[1].split("?")[0]
        v = self.table.get(sym)
        if v is None:
            raise OSError("down")
        return io.BytesIO(v)


class TestQuotes(unittest.TestCase):
    def test_parse(self):
        q = parse(body(7623.68, 7663.43))
        self.assertAlmostEqual(q["change"], -39.75, places=2)
        self.assertAlmostEqual(q["pct"], -0.5187, places=3)
        self.assertIsNone(parse(b'{"chart": {"result": []}}'))
        self.assertIsNone(parse(body(0, 1)))

    def test_cache_and_stale(self):
        now = [1000.0]
        op = FakeOpener({"%5EGSPC": body(100, 99), "BTC-USD": body(50000, 51000)})
        syms = [("SPX", "^GSPC", 2, "index"), ("BTC", "BTC-USD", 0, "crypto")]
        q = Quotes(ttl_s=60, opener=op, clock=lambda: now[0], symbols=syms)
        a = q.get()
        self.assertEqual([x["label"] for x in a["quotes"]], ["SPX", "BTC"])
        q.get()
        self.assertEqual(op.calls, 2)                                   # cached within the ttl
        now[0] += 61
        op.table.pop("BTC-USD")                                         # BTC fails on the next refresh
        b = {x["label"]: x for x in q.get()["quotes"]}
        self.assertFalse(b["SPX"]["stale"])
        self.assertTrue(b["BTC"]["stale"])                              # last good price kept, marked stale
        self.assertEqual(b["BTC"]["price"], 50000)


if __name__ == "__main__":
    unittest.main()
