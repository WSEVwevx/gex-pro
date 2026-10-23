"""ForexFactory calendar: normalization, caching, and keeping the last copy when the feed fails."""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from gexsys.news import Calendar, normalize_events

SAMPLE = [
    {"title": "CPI m/m", "country": "USD", "date": "2026-10-22T08:30:00-04:00", "impact": "High", "forecast": "0.3%", "previous": "0.4%"},
    {"title": "IMF Meetings", "country": "All", "date": "2026-10-18T10:15:00-04:00", "impact": "Low", "forecast": "", "previous": ""},
    {"title": "Bad date", "country": "USD", "date": "soon", "impact": "High"},
    {"title": "No tz", "country": "USD", "date": "2026-10-22T08:30:00", "impact": "High"},
    {"title": "Bank Holiday", "country": "JPY", "date": "2026-10-20T00:00:00-04:00", "impact": "Holiday"},
]


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestNews(unittest.TestCase):
    def test_normalize(self):
        ev = normalize_events(SAMPLE)
        self.assertEqual([e["title"] for e in ev], ["IMF Meetings", "Bank Holiday", "CPI m/m"])   # sorted, bad rows dropped
        cpi = ev[-1]
        self.assertEqual((cpi["impact"], cpi["country"], cpi["forecast"]), ("High", "USD", "0.3%"))
        self.assertEqual(cpi["time"], "2026-10-22T12:30:00+00:00")                               # ET -> UTC
        self.assertEqual(normalize_events({"not": "a list"}), [])

    def test_cache_ttl_and_failure_keeps_last_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, t = [], [1000.0]

            def opener(req, timeout=None):
                calls.append(req.full_url)
                if len(calls) == 2:
                    raise urllib.error.URLError("HTTP 429")
                return _Resp(json.dumps(SAMPLE).encode())
            cal = Calendar(ttl_s=1800, opener=opener, clock=lambda: t[0], cache_path=Path(tmp) / "c.json")
            self.assertEqual(len(cal.get()["events"]), 3)
            cal.get()
            self.assertEqual(len(calls), 1)                       # cached within the TTL
            t[0] += 1801
            d = cal.get()                                         # refresh fails -> last copy + note
            self.assertEqual(len(d["events"]), 3)
            self.assertIn("failed", d["error"])
            self.assertIn("ForexFactory", d["source"])
            again = Calendar(opener=opener, clock=lambda: t[0], cache_path=Path(tmp) / "c.json")   # restart: disk copy
            self.assertEqual(len(again._data["events"]), 3)


if __name__ == "__main__":
    unittest.main()
