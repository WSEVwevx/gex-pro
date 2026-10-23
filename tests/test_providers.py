import io
import os
import unittest
import urllib.error
from email.message import Message
from pathlib import Path

from gexsys.providers.base import (AuthError, ProviderError, ProviderUnavailable, RateLimiter, RateLimitError,
                                   http_get_json)
from gexsys.providers.csvfile import CsvProvider

DATA = Path(__file__).parent / "data"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code, retry_after=None):
    h = Message()
    if retry_after is not None:
        h["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("http://x", code, "err", h, None)


class FakeOpener:
    def __init__(self, script):
        self.script, self.calls = list(script), 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Resp(item.encode())


class TestHttp(unittest.TestCase):
    def setUp(self):
        self.sleeps = []

    def get(self, script, retries=3):
        op = FakeOpener(script)
        return op, (lambda: http_get_json("http://x", {}, retries=retries, sleep=self.sleeps.append, opener=op))

    def test_rate_limit_then_success_honours_retry_after(self):
        op, call = self.get([_http_error(429, 7), '{"ok": 1}'])
        self.assertEqual(call(), {"ok": 1})
        self.assertEqual(self.sleeps, [7.0])

    def test_rate_limit_exhausted(self):
        op, call = self.get([_http_error(429)] * 3, retries=2)
        with self.assertRaises(RateLimitError):
            call()
        self.assertEqual(op.calls, 3)

    def test_server_error_backoff_grows(self):
        op, call = self.get([_http_error(503)] * 4)
        with self.assertRaises(ProviderUnavailable):
            call()
        self.assertEqual(len(self.sleeps), 3)
        self.assertTrue(self.sleeps[2] > self.sleeps[0])

    def test_disconnect_recovers(self):
        op, call = self.get([urllib.error.URLError("conn reset"), ConnectionResetError("x"), '{"a": 2}'])
        self.assertEqual(call(), {"a": 2})

    def test_auth_not_retried(self):
        op, call = self.get([_http_error(401), '{}'])
        with self.assertRaises(AuthError):
            call()
        self.assertEqual(op.calls, 1)

    def test_bad_json(self):
        op, call = self.get(["<html>"])
        with self.assertRaises(ProviderError):
            call()

    def test_rate_limiter_spacing(self):
        t = [0.0]
        slept = []
        rl = RateLimiter(120, clock=lambda: t[0], sleep=slept.append)
        rl.wait()
        rl.wait()
        rl.wait()
        self.assertEqual(slept, [0.5, 1.0])


class TestCsv(unittest.TestCase):
    def test_csv_fixture(self):
        s = CsvProvider(str(DATA / "es_fop_sample.csv")).fetch_snapshot("ES_FOP")
        self.assertEqual(len(s.contracts), 9)
        self.assertEqual(s.spot, 5860.25)
        self.assertEqual(s.source_kind.value, "FUT")
        self.assertTrue(any("unparseable" in w for w in s.warnings))
        q = [c for c in s.contracts if c.root == "ES"][0]
        self.assertEqual(q.expiration.hour, 9)                # quarterly ES options: 09:30 ET SOQ

    def test_missing_file(self):
        with self.assertRaises(ProviderError):
            CsvProvider("nope.csv").fetch_snapshot("ES_FOP")


if __name__ == "__main__":
    unittest.main()
