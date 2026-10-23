"""Schwab OAuth + market data adapter, tested with responses shaped like the documented API
(no live account in this build), plus the Cboe fallback and the live futures basis."""
import base64
import io
import json
import os
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from gexsys import config as cfgmod
from gexsys.pipeline import run_once
from gexsys.providers.base import AuthError, ProviderError
from gexsys.providers.schwab import FallbackProvider, SchwabProvider
from gexsys.providers.schwab_auth import (REFRESH_LIFETIME_S, TokenStore, authorize_url, code_from_redirect)
from tests.test_free_sources import cboe_json
from gexsys.providers.cboe import CboeProvider

ENV = {"SCHWAB_APP_KEY": "KEY123", "SCHWAB_APP_SECRET": "SECRET456", "SCHWAB_CALLBACK_URL": "https://127.0.0.1:8182"}
NOW = datetime.now(timezone.utc)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeTokenEndpoint:
    def __init__(self):
        self.calls = []

    def __call__(self, req, timeout=None):
        form = dict(urllib.parse.parse_qsl(req.data.decode()))
        self.calls.append((req.get_header("Authorization"), form))
        n = len(self.calls)
        return _Resp(json.dumps({"access_token": f"AT{n}", "refresh_token": "RT1" if form["grant_type"] == "authorization_code" else None,
                                 "expires_in": 1800, "token_type": "Bearer"}).encode())


class TestAuth(unittest.TestCase):
    def test_authorize_url(self):
        url, state = authorize_url("KEY123", "https://127.0.0.1:8182")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        self.assertTrue(url.startswith("https://api.schwabapi.com/v1/oauth/authorize?"))
        self.assertEqual((q["client_id"], q["redirect_uri"], q["response_type"], q["state"]),
                         ("KEY123", "https://127.0.0.1:8182", "code", state))

    def test_code_from_redirect(self):
        self.assertEqual(code_from_redirect("https://127.0.0.1:8182/?code=C0.abc%40&session=xyz&state=s1", "s1"), "C0.abc@")
        self.assertEqual(code_from_redirect("https://127.0.0.1:8182/?code=Z9%40"), "Z9@")          # no state echoed
        for bad in ("https://127.0.0.1:8182/?error=access_denied", "https://127.0.0.1:8182/", "https://127.0.0.1:8182/?code=x&state=other"):
            with self.assertRaises(AuthError):
                code_from_redirect(bad, "s1")

    def test_exchange_refresh_and_seven_day_limit(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, ENV):
            t = [1_000_000.0]
            ep = FakeTokenEndpoint()
            store = TokenStore(Path(tmp) / "tok.json", clock=lambda: t[0], opener=ep)
            store.exchange_code("CODE@")
            basic, form = ep.calls[0]
            self.assertEqual(basic, "Basic " + base64.b64encode(b"KEY123:SECRET456").decode())
            self.assertEqual(form, {"grant_type": "authorization_code", "code": "CODE@", "redirect_uri": "https://127.0.0.1:8182"})
            self.assertEqual(store.access_token(), "AT1")                 # still fresh: no network call
            self.assertEqual(len(ep.calls), 1)
            t[0] += 1600                                                  # inside the 5-minute leeway -> refresh
            self.assertEqual(store.access_token(), "AT2")
            self.assertEqual(ep.calls[1][1], {"grant_type": "refresh_token", "refresh_token": "RT1"})
            self.assertEqual(store.load()["refresh_token"], "RT1")       # kept when the refresh omits it
            self.assertAlmostEqual(store.status()["refresh_days_left"], 7 - 1600 / 86400, places=2)
            t[0] = 1_000_000.0 + REFRESH_LIFETIME_S + 1
            with self.assertRaises(AuthError):
                store.access_token()
            self.assertFalse(store.status()["logged_in"])

    def test_no_token_or_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"SCHWAB_APP_KEY": ""}):
            with self.assertRaises(AuthError):
                TokenStore(Path(tmp) / "none.json").access_token()


class FakeTokens:
    def access_token(self):
        return "TOKEN"


def chain_json(delayed=False, include_flag=True):
    exp = (NOW.astimezone().date() + timedelta(days=2)).isoformat()
    calls, puts = {}, {}
    for k in range(7600, 7801, 25):
        for side, cp, store in (("CALL", "C", calls), ("PUT", "P", puts)):
            store[f"{k:.1f}"] = [{"putCall": side, "symbol": f"SPXW  {exp[2:4]}{exp[5:7]}{exp[8:10]}{cp}{k * 1000:08d}",
                                  "bid": 10.0, "ask": 10.5, "last": 10.2, "totalVolume": 300, "openInterest": 1000 + k % 300,
                                  "volatility": -999.0 if k == 7650 else 15.5, "delta": 0.5, "gamma": 0.004,
                                  "multiplier": 100.0, "optionRoot": "SPXW", "strikePrice": float(k),
                                  "quoteTimeInLong": NOW.timestamp() * 1000, "tradeTimeInLong": NOW.timestamp() * 1000}]
    d = {"symbol": "$SPX", "status": "SUCCESS", "underlyingPrice": 7712.5,
         "underlying": {"last": 7712.5, "close": 7690.0, "tradeTime": NOW.timestamp() * 1000},
         "callExpDateMap": {f"{exp}:2": calls}, "putExpDateMap": {f"{exp}:2": puts}}
    if include_flag:
        d["isDelayed"] = delayed
    return d


def quotes_json(fut_time, idx_time):
    return {"/ESZ26": {"quote": {"lastPrice": 7760.25, "tradeTime": fut_time.timestamp() * 1000}},
            "$SPX": {"quote": {"lastPrice": 7712.5, "tradeTime": idx_time.timestamp() * 1000}}}


class FakeSchwabHttp:
    def __init__(self, chain=None, fut_skew_s=5):
        self.urls, self.chain, self.skew = [], chain or chain_json(), fut_skew_s

    def __call__(self, url, headers, limiter=None):
        self.urls.append(url)
        assert headers["Authorization"] == "Bearer TOKEN"
        if "/chains" in url:
            return self.chain
        return quotes_json(NOW, NOW - timedelta(seconds=self.skew))


class TestSchwabData(unittest.TestCase):
    def test_chain_parse(self):
        http = FakeSchwabHttp()
        s = SchwabProvider(tokens=FakeTokens(), http=http).fetch_snapshot("SPX", max_dte=10)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(http.urls[0]).query))
        self.assertEqual((q["symbol"], q["contractType"], q["strategy"]), ("$SPX", "ALL", "SINGLE"))
        self.assertIn("fromDate", q)
        self.assertEqual((s.spot, s.prev_close, s.spot_quality.value), (7712.5, 7690.0, "RT"))
        self.assertEqual(len(s.contracts), 18)
        c = next(x for x in s.contracts if x.strike == 7700.0)
        self.assertAlmostEqual(c.iv, 0.155)                                   # percent -> decimal
        self.assertEqual((c.root, c.expiration.hour, c.oi_quality.value), ("SPXW", 16, "EOD"))
        self.assertTrue(all(x.iv is None for x in s.contracts if x.strike == 7650.0))   # -999 placeholder dropped

    def test_unstated_delay_is_labeled_conservatively(self):
        with mock.patch.dict(os.environ, {"SCHWAB_QUOTE_QUALITY": "DL"}):
            s = SchwabProvider(tokens=FakeTokens(), http=FakeSchwabHttp(chain_json(include_flag=False))).fetch_snapshot("SPX")
        self.assertEqual(s.spot_quality.value, "DL")
        self.assertTrue(any("did not state" in w for w in s.warnings))
        s = SchwabProvider(tokens=FakeTokens(), http=FakeSchwabHttp(chain_json(delayed=True))).fetch_snapshot("SPX")
        self.assertEqual(s.spot_quality.value, "DL")

    def test_futures_basis(self):
        fp, ft, sp, st, lbl = SchwabProvider(tokens=FakeTokens(), http=FakeSchwabHttp()).futures_basis("MES", "SPX")
        self.assertEqual((fp, sp), (7760.25, 7712.5))
        self.assertIn("/ESZ26", lbl)

    def test_fallback_to_cboe_is_labeled(self):
        class Expired:
            name, label = "schwab", "SCHWAB"

            def fetch_snapshot(self, *a, **k):
                raise AuthError("Schwab's 7-day login expired - run SCHWAB_LOGIN.bat")
        fb = FallbackProvider(Expired(), CboeProvider(http=lambda *a, **k: cboe_json()))
        snap = fb.fetch_snapshot("NDX", 45, True)
        self.assertEqual(fb.last_label, "CBOE")
        self.assertTrue(any("using CBOE" in w for w in snap.warnings))


class TestSchwabPipeline(unittest.TestCase):
    def cfg(self, tmp):
        return cfgmod.from_dict({"market": "ES", "source": "SPX", "provider": {"name": "schwab", "fallback": "cboe"},
                                 "futures_ref": {"mode": "provider"}, "storage": {"root": tmp},
                                 "engine": {"recompute_greeks": "always", "max_dte": 10, "max_spot_age_s": 1800}})

    def test_live_basis_when_time_matched_else_carry(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = self.cfg(tmp)
            p = SchwabProvider(tokens=FakeTokens(), http=FakeSchwabHttp(fut_skew_s=5))
            r = run_once(c, p)
            self.assertEqual(r["summary"]["provider"], "SCHWAB")
            self.assertIn("live, time-matched", r["mapped"]["mapping"]["futures_ref_mode"])
            self.assertAlmostEqual(r["mapped"]["mapping"]["factor"], 7760.25 / 7712.5)
            self.assertIn("prov=SCHWAB;", r["pine"])
            p2 = SchwabProvider(tokens=FakeTokens(), http=FakeSchwabHttp(fut_skew_s=3600))   # index closed
            r2 = run_once(c, p2)
            self.assertIn("carry-model", r2["mapped"]["mapping"]["futures_ref_mode"])

    def test_configs_and_validation(self):
        for f in ("schwab_nq", "schwab_es"):
            c = cfgmod.load(f"configs/{f}.json")
            self.assertEqual((c.provider["name"], c.provider["fallback"], c.futures_ref["mode"]), ("schwab", "cboe", "provider"))
            self.assertIsInstance(cfgmod.make_provider(c), FallbackProvider)
        with self.assertRaises(Exception):
            cfgmod.from_dict({"market": "ES", "source": "SPX", "provider": {"name": "cboe"}, "futures_ref": {"mode": "provider"}})

    def test_auto_configs(self):
        from gexsys.__main__ import auto_configs
        with mock.patch.dict(os.environ, {"SCHWAB_APP_KEY": ""}):
            self.assertEqual(auto_configs(), ["configs/free_nq_cboe.json", "configs/free_es_cboe.json"])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, dict(ENV, SCHWAB_TOKEN_PATH=str(Path(tmp) / "t.json"))):
            self.assertEqual(auto_configs(), ["configs/schwab_nq.json", "configs/schwab_es.json"])


if __name__ == "__main__":
    unittest.main()
