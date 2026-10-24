"""Stock screener: parsing a screen, derived columns, caching, and a failed screen kept as stale."""
import io
import json
import unittest

from feeds.screener import Screener, parse


def body(*rows):
    return json.dumps({"finance": {"result": [{"quotes": list(rows)}]}}).encode()


ROW = {"symbol": "RHI", "displayName": "Robert Half", "fullExchangeName": "NYSE", "regularMarketPrice": 45.87,
       "regularMarketChange": 8.19, "regularMarketChangePercent": 21.7357, "regularMarketVolume": 6892870,
       "averageDailyVolume3Month": 2030470, "marketCap": 4695336960, "trailingPE": 37.6,
       "fiftyTwoWeekHigh": 47.14, "fiftyTwoWeekLow": 21.83, "earningsTimestamp": 1792699200}


class FakeOpener:
    def __init__(self, table):
        self.table, self.calls = table, 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        v = self.table.get(req.full_url.split("scrIds=")[1].split("&")[0])
        if v is None:
            raise OSError("down")
        return io.BytesIO(v)


class TestScreener(unittest.TestCase):
    def test_parse(self):
        r = parse(body(ROW, {"symbol": "BAD", "regularMarketPrice": None}))[0]
        self.assertEqual(len(parse(body(ROW, {"symbol": "BAD", "regularMarketPrice": None}))), 1)   # no price -> dropped
        self.assertEqual((r["symbol"], r["name"], r["exchange"]), ("RHI", "Robert Half", "NYSE"))
        self.assertAlmostEqual(r["rel_volume"], 6892870 / 2030470)
        self.assertAlmostEqual(r["from_high"], (45.87 / 47.14 - 1) * 100)
        self.assertEqual(r["earnings"], 1792699200)
        self.assertIsNone(parse(b'{"finance": {"result": []}}'))
        self.assertIsNone(parse(b"not json"))

    def test_missing_fields_are_none(self):
        r = parse(body({"symbol": "X", "regularMarketPrice": 5}))[0]
        self.assertEqual(r["name"], "X")
        self.assertIsNone(r["rel_volume"])
        self.assertIsNone(r["from_high"])
        self.assertIsNone(r["pe"])

    def test_cache_and_stale(self):
        now = [1000.0]
        op = FakeOpener({"a": body(ROW), "b": body(ROW)})
        s = Screener(ttl_s=60, opener=op, clock=lambda: now[0], screens=[("a", "A"), ("b", "B")])
        first = s.get()
        self.assertEqual([x["id"] for x in first["screens"]], ["a", "b"])
        s.get()
        self.assertEqual(op.calls, 2)                     # cached inside the ttl
        del op.table["b"]
        now[0] += 61
        later = {x["id"]: x for x in s.get()["screens"]}
        self.assertFalse(later["a"]["stale"])
        self.assertTrue(later["b"]["stale"])
        self.assertEqual(len(later["b"]["rows"]), 1)      # last good copy kept


if __name__ == "__main__":
    unittest.main()
