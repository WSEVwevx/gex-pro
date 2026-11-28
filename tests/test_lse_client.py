"""The LSE client (rework workstream 3): the key stays secret, the limiter is always on, refusals are named and never
looped, pages are joined, session chains are cached until their Greeks land, and LSE never runs for the public site.
Every number here is synthetic (LSE data may not enter the repo)."""
import email.message
import io
import json
import logging
import os
import tempfile
import traceback
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest import mock

from gexsys.providers import lse
from gexsys.providers.base import AuthError, ProviderUnavailable, RateLimitError

ROOT = Path(__file__).resolve().parents[1]
KEY = "test-key-7f3a9c"          # synthetic


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, body=b"", retry_after=None):
    h = email.message.Message()
    if retry_after is not None:
        h["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("https://download.londonstrategicedge.com/v3/x", code, "err", h, io.BytesIO(body))


class Script:
    """An opener that answers from a list (dicts as JSON, exceptions raised) and records each request."""

    def __init__(self, *answers):
        self.answers, self.reqs = list(answers), []

    def __call__(self, req, timeout=None):
        self.reqs.append(req)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return Resp(json.dumps(a).encode())


def client(opener, tmp=None, **kw):
    return lse.LseClient(key=KEY, opener=opener, sleep=kw.pop("sleep", lambda s: None), cache_dir=tmp, **kw)


def row(strike, iv=0.2, kind="call"):
    return {"strike": strike, "contract_type": kind, "iv": iv, "expiry": "2026-12-18", "greeks_at": "2026-11-25 20:58:00",
            "greeks_underlying_price": 100.0}


@mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "", "GEX_NO_LSE": ""})
class Secrecy(unittest.TestCase):
    def test_the_key_goes_in_the_header_only(self):
        op = Script({"rows": []})
        client(op).get("/v3/usage")
        r = op.reqs[0]
        self.assertEqual(r.get_header("X-api-key"), KEY)
        self.assertNotIn(KEY, r.full_url)
        self.assertNotIn(KEY, repr(client(op)))

    def test_no_error_log_or_file_carries_the_key(self):
        # a server that echoes the key in its error body, every failure kind, a cache folder and the log watched
        echo = json.dumps({"code": "bad-key", "message": f"key {KEY} refused"}).encode()
        cases = [http_error(401, echo), http_error(403, echo), http_error(429, echo), http_error(400, echo),
                 http_error(500, echo), http_error(500, echo), http_error(500, echo),
                 urllib.error.URLError(f"proxy said {KEY}")] + [urllib.error.URLError(f"x {KEY}")] * 2
        with tempfile.TemporaryDirectory() as tmp, self.assertLogs("gexsys.providers.lse", logging.DEBUG) as logs:
            logging.getLogger("gexsys.providers.lse").debug("watching")
            c = client(Script(*cases), tmp)
            seen = []
            for _ in range(6):
                try:
                    c.get("/v3/options/chain", underlying="SPX")
                except Exception as e:                      # noqa: BLE001 (every kind is checked)
                    seen.append("".join(traceback.format_exception(e)) + repr(e) + str(c.last_error))
            files = "".join(p.read_text(encoding="utf-8", errors="replace") for p in Path(tmp).rglob("*") if p.is_file())
        self.assertGreaterEqual(len(seen), 5)
        for text in seen + logs.output + [files]:
            self.assertNotIn(KEY, text)
        self.assertIn("key refused (HTTP 401, bad-key)", seen[0])

    def test_the_key_is_read_from_the_env_then_the_file(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(Path, "home", return_value=Path(tmp)):
            with mock.patch.dict(os.environ, {"LSE_KEY": ""}):
                self.assertIsNone(lse.read_key())
                (Path(tmp) / ".lse_key").write_text(f"  {KEY}  \n", encoding="utf-8")
                self.assertEqual(lse.read_key(), KEY)
            with mock.patch.dict(os.environ, {"LSE_KEY": "env-key"}):
                self.assertEqual(lse.read_key(), "env-key")

    def test_no_key_is_unavailable_without_a_request(self):
        op = Script()
        with self.assertRaisesRegex(AuthError, "no LSE key"):
            lse.LseClient(key="", opener=op, cache_dir=None).get("/v3/usage")
        self.assertEqual(op.reqs, [])


@mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "", "GEX_NO_LSE": ""})
class Refusals(unittest.TestCase):
    def test_a_refused_key_is_never_retried(self):
        op = Script(http_error(401), {"rows": []})
        with self.assertRaisesRegex(AuthError, "unavailable: key refused"):
            client(op).get("/v3/usage")
        self.assertEqual(len(op.reqs), 1)

    def test_429_waits_the_seconds_asked_once(self):
        waits = []
        op = Script(http_error(429, retry_after=7), {"ok": 1})
        self.assertEqual(client(op, sleep=waits.append).get("/v3/usage"), {"ok": 1})
        self.assertEqual(waits, [7.0])
        op = Script(http_error(429, retry_after=7), http_error(429, retry_after=7))
        with self.assertRaises(RateLimitError):
            client(op).get("/v3/usage")
        op = Script(http_error(429, retry_after=600))                     # longer than a minute: not waited for
        with self.assertRaises(RateLimitError):
            client(op).get("/v3/usage")
        self.assertEqual(len(op.reqs), 1)

    def test_server_errors_retry_twice_then_unavailable(self):
        op = Script(http_error(502), http_error(503), http_error(504, b'{"code": "options-timeout"}'))
        with self.assertRaisesRegex(ProviderUnavailable, "HTTP 504, options-timeout"):
            client(op).get("/v3/options/chain", underlying="SPX")
        self.assertEqual(len(op.reqs), 3)


class Limits(unittest.TestCase):
    @mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "", "GEX_NO_LSE": ""})
    def test_per_minute_per_day_and_budget(self):
        t = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            c = lse.LseClient(key=KEY, opener=Script(*[{}] * 10), clock=lambda: t[0], cache_dir=tmp, per_minute=2, per_day=3)
            c.get("/a"), c.get("/b")
            with self.assertRaisesRegex(RateLimitError, "2 LSE calls in the last minute"):
                c.get("/c")
            t[0] += 61
            c.get("/c")
            with self.assertRaisesRegex(RateLimitError, "3 LSE calls today"):
                c.get("/d")
            # the day count is on disk: a new client (a restart) shares it
            c2 = lse.LseClient(key=KEY, opener=Script({}), clock=lambda: t[0], cache_dir=tmp, per_day=3)
            with self.assertRaises(RateLimitError):
                c2.get("/e")
        c3 = lse.LseClient(key=KEY, opener=Script({}, {}), cache_dir=None, budget=1)
        c3.get("/a")
        with self.assertRaisesRegex(RateLimitError, "budget of 1"):
            c3.get("/b")

    def test_the_defaults_stay_under_the_free_plan(self):
        lim = lse.LseClient(key=KEY, cache_dir=None).limiter
        self.assertLessEqual(lim.per_minute, 30)                          # the plan allows 60
        self.assertLessEqual(lim.per_day, 2000)


@mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "", "GEX_NO_LSE": ""})
class Paging(unittest.TestCase):
    def test_every_page_is_joined(self):
        p1 = {"contracts": 5001, "returned": 5000, "greeks_as_of": "2026-11-25 21:00:00", "rows": [row(k) for k in range(5000)]}
        p2 = {"contracts": 5001, "returned": 1, "greeks_as_of": "2026-11-25 21:00:00", "rows": [row(9999)]}
        op = Script(p1, p2)
        got = client(op).chain("SPXW", max_dte=10)
        self.assertEqual(len(got["rows"]), 5001)
        self.assertEqual(got["greeks_as_of"], "2026-11-25 21:00:00")
        self.assertIn("offset=5000", op.reqs[1].full_url)
        self.assertIn("limit=5000", op.reqs[0].full_url)

    def test_greeks_changing_day_mid_chain_is_refused(self):
        p1 = {"contracts": 5001, "greeks_as_of": "2026-11-25 21:00:00", "rows": [row(k) for k in range(5000)]}
        p2 = {"contracts": 5001, "greeks_as_of": "2026-11-27 18:30:00", "rows": [row(1)]}
        with self.assertRaisesRegex(ProviderUnavailable, "changed day"):
            client(Script(p1, p2)).chain("SPXW")


@mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "", "GEX_NO_LSE": ""})
class SessionCache(unittest.TestCase):
    def test_fetched_until_landed_then_never_again(self):
        t = [0.0]
        wed = date(2026, 11, 25)
        old = {"contracts": 1, "greeks_as_of": "2026-11-24 21:00:00", "rows": [row(100)]}
        new = {"contracts": 1, "greeks_as_of": "2026-11-25 21:00:00", "rows": [row(100, 0.25)]}
        with tempfile.TemporaryDirectory() as tmp:
            op = Script(old, old, new, new)              # probe, the earlier session's chain; probe, the landed chain
            c = lse.LseClient(key=KEY, opener=op, clock=lambda: t[0], cache_dir=tmp)
            self.assertIsNone(c.session_chain("SPXW", wed))               # not landed yet: no wait, no guess
            self.assertRegex(op.reqs[0].full_url, r"[?&]limit=1(&|$)")                # a 1-row probe first, not every page
            self.assertEqual(c.newest_landed("SPXW")["session"], "2026-11-24")     # the earlier session is kept
            self.assertIsNone(c.session_chain("SPXW", wed))               # asked again within 15 min: no request
            self.assertEqual(len(op.reqs), 2)
            t[0] += lse.REFETCH_S
            got = c.session_chain("SPXW", wed)
            self.assertEqual(got["rows"][0]["iv"], 0.25)
            self.assertEqual(len(op.reqs), 4)
            self.assertEqual(c.session_chain("SPXW", wed)["rows"][0]["iv"], 0.25)       # from disk
            self.assertEqual(len(op.reqs), 4)
            land = json.loads((Path(tmp) / "landing.json").read_text(encoding="utf-8"))
            self.assertEqual(land["SPXW 2026-11-25"]["greeks_as_of"], "2026-11-25 21:00:00")
            self.assertEqual(c.newest_landed("SPXW")["session"], "2026-11-25")
            self.assertEqual(c.newest_landed("SPXW", before=wed)["session"], "2026-11-24")
            self.assertIn("newest Greeks 2026-11-25 21:00", c.health_row()["detail"])

    def test_a_probe_that_finds_nothing_new_costs_one_call(self):
        t = [0.0]
        old = {"contracts": 1, "greeks_as_of": "2026-11-24 21:00:00", "rows": [row(100)]}
        with tempfile.TemporaryDirectory() as tmp:
            op = Script(old, old, old)
            c = lse.LseClient(key=KEY, opener=op, clock=lambda: t[0], cache_dir=tmp)
            c.session_chain("SPXW", date(2026, 11, 25))                   # probe + the 24th's chain (2 calls)
            t[0] += lse.REFETCH_S
            c.session_chain("SPXW", date(2026, 11, 25))                   # the 24th is on disk: the probe only
            self.assertEqual(len(op.reqs), 3)

    def test_a_session_already_passed_is_not_asked_again(self):
        thu_greeks = {"contracts": 1, "greeks_as_of": "2026-11-27 18:30:00", "rows": [row(100)]}
        with tempfile.TemporaryDirectory() as tmp:
            t = [0.0]
            op = Script(thu_greeks)
            c = lse.LseClient(key=KEY, opener=op, clock=lambda: t[0], cache_dir=tmp)
            self.assertIsNone(c.session_chain("SPXW", date(2026, 11, 25)))
            t[0] += 10 * lse.REFETCH_S
            self.assertIsNone(c.session_chain("SPXW", date(2026, 11, 25)))
            self.assertEqual(len(op.reqs), 1)

    def test_a_chain_longer_than_the_minute_limit_carries_on_next_time(self):
        t = [0.0]
        wed = date(2026, 11, 25)
        probe = {"contracts": 5001, "greeks_as_of": "2026-11-25 21:00:00", "rows": [row(1)]}
        p1 = {"contracts": 5001, "greeks_as_of": "2026-11-25 21:00:00", "rows": [row(k) for k in range(5000)]}
        p2 = {"contracts": 5001, "greeks_as_of": "2026-11-25 21:00:00", "rows": [row(9999)]}
        with tempfile.TemporaryDirectory() as tmp:
            op = Script(probe, p1, probe, p2)
            c = lse.LseClient(key=KEY, opener=op, clock=lambda: t[0], cache_dir=tmp, per_minute=2)
            with self.assertRaises(RateLimitError):                       # probe + page 1, then the minute's limit
                c.session_chain("SPXW", wed, max_dte=10)
            self.assertIsNone(c.cached("SPXW", wed))                       # half a chain is never a landed session
            self.assertIsNone(c.newest_landed("SPXW"))
            t[0] += 61
            got = c.session_chain("SPXW", wed, max_dte=10)
            self.assertEqual(len(got["rows"]), 5001)
            self.assertEqual(len(op.reqs), 4)                             # page 1 was not asked for again
            self.assertIn("offset=5000", op.reqs[3].full_url)
            self.assertEqual(list((Path(tmp) / "chains").glob("*.part")), [])

    def test_a_greeks_time_is_dated_in_new_york(self):
        self.assertEqual(lse.session_of("2026-11-25 20:58:19.448381162"), date(2026, 11, 25))
        self.assertEqual(lse.session_of("2026-11-26 01:30:00"), date(2026, 11, 25))   # 20:30 ET
        self.assertIsNone(lse.session_of(None))


class LocalOnly(unittest.TestCase):
    def test_refuses_on_github_and_in_the_hosted_build(self):
        for env in ({"GITHUB_ACTIONS": "true", "GEX_NO_LSE": ""}, {"GITHUB_ACTIONS": "", "GEX_NO_LSE": "1"}):
            op = Script()
            with mock.patch.dict(os.environ, env), self.assertRaisesRegex(lse.LocalOnly, "local only"):
                client(op).get("/v3/usage")
            self.assertEqual(op.reqs, [])

    def test_the_site_build_and_the_archive_switch_lse_off(self):
        for f, head in (("gexpro/site.py", "def build("), ("gexpro/archive.py", "def run(")):
            body = (ROOT / f).read_text(encoding="utf-8").split(head, 1)[1].split("\ndef ", 1)[0]
            self.assertIn('os.environ["GEX_NO_LSE"] = "1"', body, f)

    def test_nothing_public_imports_lse_or_names_it(self):
        # the hosted build's code, the archive writer and the website files never use LSE or show its credit;
        # LSE stays in gexsys/providers/lse.py until a local-only component uses it
        public = [*(ROOT / "dashboard").rglob("*.js"), *(ROOT / "dashboard").rglob("*.html"), ROOT / "gexpro/site.py",
                  ROOT / "gexpro/archive.py", ROOT / "pine/nq_es_gex_levels.pine"]
        for p in public:
            text = p.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn("providers.lse", text, p)
            self.assertNotIn("London Strategic Edge", text, p)
        users = [p.relative_to(ROOT).as_posix() for p in (ROOT / "gexsys").rglob("*.py")
                 if "providers import lse" in p.read_text(encoding="utf-8") or "from .lse" in p.read_text(encoding="utf-8")]
        # its Data health row; the factory, which builds a client only with GEX_LSE=1 and never on GitHub or in the
        # hosted build (tests/test_occ_lse.py Switch); the OCC chain, which uses only a client it is handed
        self.assertEqual(sorted(users), ["gexsys/component.py", "gexsys/config.py", "gexsys/providers/occ.py"])

    def test_the_data_health_row_is_local_and_keyed(self):
        from types import SimpleNamespace
        from gexsys.component import GexComponent
        comp = GexComponent.__new__(GexComponent)
        comp.workers, comp.heat = {}, SimpleNamespace(status={})
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"LSE_KEY": KEY, "LOCALAPPDATA": tmp}):
            for env, n in (({"GITHUB_ACTIONS": "true", "GEX_NO_LSE": ""}, 0), ({"GITHUB_ACTIONS": "", "GEX_NO_LSE": "1"}, 0),
                           ({"GITHUB_ACTIONS": "", "GEX_NO_LSE": ""}, 1)):
                comp._lse = None
                with mock.patch.dict(os.environ, env):
                    rows = [r for r in comp.sources() if "LSE" in r["name"]]
                self.assertEqual(len(rows), n, env)
            self.assertNotIn(KEY, json.dumps(rows))
            self.assertIn("calls today 0/2000", rows[0]["detail"])

    def test_no_lse_values_in_fixtures(self):
        for p in (ROOT / "tests" / "fixtures").rglob("*"):
            if p.is_file() and p.suffix in (".json", ".csv", ".txt"):
                self.assertNotIn("greeks_as_of", p.read_text(encoding="utf-8", errors="replace"), p)


if __name__ == "__main__":
    unittest.main()
