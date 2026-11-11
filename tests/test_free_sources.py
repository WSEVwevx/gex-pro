"""Cboe adapter (canned responses shaped like the live ones seen 2026-10-21), combined payloads,
carry-model futures basis, and the one-toast-per-slot gate."""
import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from gexsys import config as cfgmod
from gexsys.basis import carry_fair_value, futures_expiry
from gexsys.export import combine, parse_combined
from gexsys.marketcal import NY
from gexsys.pipeline import run_once
from gexsys.providers.base import ProviderError
from gexsys.providers.cboe import CboeProvider
from gexsys.service import MarketWorker, NotifyGate

NOW = datetime.now(timezone.utc)
EXP = (NOW + timedelta(days=3)).date()
OCC = f"{EXP:%y%m%d}"


def cboe_json(spot=29490.28):
    opts = []
    for k in range(29000, 30001, 100):
        for cp in "CP":
            opts.append({"option": f"NDXP{OCC}{cp}{k * 1000:08d}", "bid": 50.0, "ask": 55.0, "iv": 0.19 if k != 29500 else 0.0,
                         "open_interest": 100.0 + k % 700, "volume": 5.0, "delta": 0.5, "gamma": 0.0004,
                         "last_trade_price": 52.0, "last_trade_time": "2026-10-20T15:59:00"})
    opts.append({"option": "GARBAGE", "iv": 0.2})
    opts.append({"option": f"NDXP{(NOW + timedelta(days=400)):%y%m%d}C30000000", "iv": 0.2, "open_interest": 5})
    return {"timestamp": NOW.strftime("%Y-%m-%d %H:%M:%S"), "symbol": "_NDX",
            "data": {"symbol": "^NDX", "current_price": spot, "prev_day_close": 29400.0, "options": opts}}


class TestCboe(unittest.TestCase):
    def test_parse(self):
        seen = {}

        def http(url, headers, limiter=None):
            seen["url"] = url
            return cboe_json()
        s = CboeProvider(http=http).fetch_snapshot("NDX", max_dte=45)
        self.assertIn("_NDX.json", seen["url"])
        self.assertEqual(s.spot, 29490.28)
        self.assertEqual(s.prev_close, 29400.0)
        self.assertEqual(s.spot_quality.value, "DL")
        self.assertEqual(len(s.contracts), 22)                 # far expiry and garbage dropped
        zero_iv = [c for c in s.contracts if c.strike == 29500.0]
        self.assertTrue(all(c.iv is None for c in zero_iv))     # iv 0 -> missing, never used as 0
        self.assertEqual(s.contracts[0].root, "NDXP")
        self.assertEqual(s.contracts[0].expiration.hour, 16)
        self.assertAlmostEqual((NOW - s.spot_time).total_seconds(), 900, delta=2)

    def test_errors(self):
        with self.assertRaises(ProviderError):
            CboeProvider(http=lambda *a, **k: cboe_json()).fetch_snapshot("NQ_FOP")
        with self.assertRaises(ProviderError):
            CboeProvider(http=lambda *a, **k: {"data": {}}).fetch_snapshot("NDX")


def qqq_json(spot=715.0):
    opts = []
    for k in (703, 704, 712, 713, 715, 716, 740):
        for cp in "CP":
            opts.append({"option": f"QQQ{OCC}{cp}{k * 1000:08d}", "bid": 5.0, "ask": 5.2, "iv": 0.2,
                         "open_interest": 4120.0, "volume": 824.0, "gamma": 0.01})
    return {"timestamp": NOW.strftime("%Y-%m-%d %H:%M:%S"), "symbol": "QQQ",
            "data": {"symbol": "QQQ", "current_price": spot, "prev_day_close": 712.0, "options": opts}}


class TestEtfMerge(unittest.TestCase):
    def snap(self, qqq=True):
        http = lambda url, headers, limiter=None: qqq_json() if "QQQ" in url else cboe_json()
        if not qqq:
            http = lambda url, headers, limiter=None: (_ for _ in ()).throw(ProviderError("down")) \
                if "QQQ" in url else cboe_json()
        return CboeProvider(http=http, include_etf=True).fetch_snapshot("NDX", max_dte=45)

    def test_converted_into_index_contracts(self):
        from gexsys import pricing
        s = self.snap()
        r = 29490.28 / 715.0
        q = [c for c in s.contracts if c.root == "QQQ"]
        self.assertTrue(q and all(c.symbol.endswith("@NDX") and c.multiplier == 100 for c in q))
        self.assertTrue(all(c.bid is None and c.gamma is None and c.iv == 0.2 for c in q))
        self.assertTrue(any("includes QQQ options in NDX terms" in w for w in s.warnings))
        # math uses the exact converted strike; levels group it with the nearest listed NDX strike
        # (100 apart here) when within 0.75 x spacing, else at the exact strike
        self.assertTrue(all(abs(c.strike - float(c.symbol.split("@")[0][-8:]) / 1000 * r) < 1e-6 for c in q))
        groups = {c.level_strike for c in q}
        self.assertIn(29000.0, groups)                   # 703 x 41.25 = 28997.6 -> grouped at 29000
        self.assertIn(round(740 * r, 2), groups)         # 30521: past the last NDX strike (30000), own level
        # 712 and 713 (29368, 29409) stay two contracts with their own strikes, both grouped at 29400
        both = [c for c in q if c.level_strike == 29400.0 and c.option_type.value == "C"]
        self.assertEqual(sorted(round(c.strike, 1) for c in both), [round(712 * r, 1), round(713 * r, 1)])
        self.assertAlmostEqual(sum(c.open_interest for c in both), 2 * 4120.0 / r, places=6)
        from gexsys import engine as eng
        res = eng.compute(s, eng.EngineConfig(max_dte=45))
        self.assertIn(29400.0, res.by_strike)
        self.assertFalse(any(abs(k - 712 * r) < 1e-6 for k in res.by_strike))   # no stray unsnapped level
        # dollar gamma is unchanged by the conversion (exact identity, not an approximation)
        t, iv = 3 / 365, 0.2
        own = 4120.0 * pricing.bsm_gamma(715.0, 715.0, t, 0.04, 0, iv) * 100 * 715.0 ** 2
        conv = 4120.0 / r * pricing.bsm_gamma(29490.28, 715.0 * r, t, 0.04, 0, iv) * 100 * 29490.28 ** 2
        self.assertAlmostEqual(own / conv, 1.0, places=9)

    def test_etf_failure_keeps_index_levels(self):
        s = self.snap(qqq=False)
        self.assertFalse(any(c.root == "QQQ" for c in s.contracts))
        self.assertTrue(any("QQQ options unavailable" in w for w in s.warnings))

    def test_survives_normalize_and_pipeline(self):
        from gexsys.normalize import normalize
        s = normalize(self.snap(), check_occ=True)
        self.assertTrue(any(c.root == "QQQ" for c in s.contracts))     # not rejected as OCC mismatches
        with self.assertRaises(Exception):
            cfgmod.from_dict({"market": "NQ", "source": "QQQ", "provider": {"name": "cboe", "include_etf": True},
                              "mapping": {"method": "ratio"}})
        self.assertTrue(cfgmod.load("configs/free_nq_cboe.json").provider["include_etf"])


class TestCarryBasis(unittest.TestCase):
    def test_hand_calculated_fair_value(self):
        asof = datetime(2026, 10, 20, 16, 0, tzinfo=NY)
        code, exp = futures_expiry("ES", asof)
        self.assertEqual(code, "ESZ6")
        self.assertEqual((exp.date().isoformat(), exp.hour), ("2026-12-18", 9))
        fv, code2, r, q = carry_fair_value("ES", "SPX", 7700.0, asof, rate=0.04, div_yield=0.013)
        t = (exp - asof).total_seconds() / (365 * 86400)
        self.assertAlmostEqual(fv, 7700.0 * math.exp(0.027 * t))
        self.assertTrue(7733 < fv < 7734)                      # 58.7 days of 2.7% carry: 7700*(e^(0.027*0.1609)-1) = +33.5

    def test_contract_is_the_one_a_continuous_chart_shows(self):
        # stress test C2: NQ1! / NQ=F keep the expiring quarterly through roll week and switch at its 09:30
        # settlement; pricing the next one from the roll date put the website ~0.8% (~230 NQ points) off the chart
        for t, want in ((datetime(2026, 12, 10, 12, 0, tzinfo=NY), "NQZ6"),      # roll date
                        (datetime(2026, 12, 18, 9, 29, tzinfo=NY), "NQZ6"),      # expiry day, before settlement
                        (datetime(2026, 12, 18, 9, 30, tzinfo=NY), "NQH7"),
                        (datetime(2027, 3, 21, 18, 5, tzinfo=NY), "NQM7")):      # Sunday open after March expiry
            self.assertEqual(futures_expiry("MNQ", t)[0], want, t)
        self.assertEqual(futures_expiry("NQ", datetime(2026, 12, 18, 10, 0, tzinfo=NY))[1].date().isoformat(), "2027-03-19")

    def test_etf_source_not_supported(self):
        self.assertIsNone(carry_fair_value("ES", "SPY", 770.0, datetime(2026, 10, 20, 16, 0, tzinfo=NY)))


class TestCombined(unittest.TestCase):
    def test_combine_and_filter(self):
        a = "GEX1;prov=CBOE;mkt=NQ;zg=1.00;L="
        b = "GEX1;prov=CBOE;mkt=ES;zg=2.00;L="
        parsed = parse_combined(combine([a, "", b]))
        self.assertEqual([(p["prov"], p["mkt"]) for p in parsed], [("CBOE", "NQ"), ("CBOE", "ES")])

    def test_pipeline_labels_provider_maps_with_carry_and_separates_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cfgmod.from_dict({"market": "NQ", "source": "NDX", "provider": {"name": "cboe"},
                                  "futures_ref": {"mode": "carry", "rate": 0.04, "div_yield": 0.007},
                                  "engine": {"recompute_greeks": "always", "max_dte": 45, "max_spot_age_s": 1800},
                                  "storage": {"root": tmp}})
            from gexsys.storage import SnapshotStore
            r = run_once(c, CboeProvider(http=lambda *a, **k: cboe_json()), SnapshotStore(tmp))
            self.assertIn("prov=CBOE;", r["pine"])
            self.assertEqual(r["summary"]["provider"], "CBOE")
            self.assertIsNotNone(r["mapped"])
            self.assertGreater(r["mapped"]["mapping"]["factor"], 1.0)        # r > q: futures above index
            self.assertIn("carry-model", r["mapped"]["mapping"]["futures_ref_mode"])
            self.assertEqual(len(list(SnapshotStore(tmp).iter_summaries("NQ-CBOE"))), 1)

    def test_measured_basis_is_a_session_median_with_carry_fallback(self):
        # stress test C1: the 4% carry model sat 22 NQ points below the market; the measured basis is the median
        # futures / index ratio of the last 15 minutes both traded, restarted after an hour's gap, like the indicator
        from gexsys import basis
        t0 = int(datetime(2026, 11, 9, 15, 0, tzinfo=NY).timestamp())
        idx = {t0 + 60 * i: 100.0 for i in range(30)}
        fut = {t: 101.0 for t in idx}
        fut[t0 + 60 * 29] = 150.0                                          # one bad print: the median ignores it
        idx[t0 + 86400] = 100.0                                            # next day, one minute only: a new session
        fut[t0 + 86400] = 100.5
        r, when = basis.median_ratio(fut, idx, datetime(2026, 11, 9, 23, 0, tzinfo=NY))
        self.assertEqual((r, when.timestamp()), (1.01, t0 + 60 * 29))
        self.assertEqual(basis.median_ratio(fut, idx, datetime(2026, 11, 10, 16, 0, tzinfo=NY))[0], 1.005)
        orig = basis._yahoo_1m
        try:
            basis._yahoo_1m = lambda sym, asof: fut if "=F" in sym else idx
            ob = basis.observed_basis("NDX", datetime(2026, 11, 9, 23, 0, tzinfo=NY))
            self.assertEqual(ob[0], 1.01)
            self.assertIn("NQ=F", ob[2])
            self.assertIsNone(basis.observed_basis("NDX", datetime(2026, 11, 20, 12, 0, tzinfo=NY)))   # stale
            def down(sym, asof):
                raise OSError("offline")
            basis._yahoo_1m = down
            self.assertIsNone(basis.observed_basis("SPX", datetime(2026, 11, 9, 23, 0, tzinfo=NY)))
            with tempfile.TemporaryDirectory() as tmp:
                c = cfgmod.from_dict({"market": "NQ", "source": "NDX", "provider": {"name": "cboe"},
                                      "futures_ref": {"mode": "observed", "rate": 0.04, "div_yield": 0.007},
                                      "engine": {"recompute_greeks": "always", "max_dte": 45, "max_spot_age_s": 1800},
                                      "storage": {"root": tmp}})
                r = run_once(c, CboeProvider(http=lambda *a, **k: cboe_json()))
                self.assertIn("measured basis unavailable", r["mapped"]["mapping"]["futures_ref_mode"])
        finally:
            basis._yahoo_1m = orig

    def test_free_configs_validate(self):
        for f in ("free_nq_cboe", "free_es_cboe"):
            c = cfgmod.load(f"configs/{f}.json")
            self.assertEqual(c.futures_ref["mode"], "observed")
        with self.assertRaises(Exception):
            cfgmod.from_dict({"market": "ES", "source": "SPY", "provider": {"name": "cboe"},
                              "futures_ref": {"mode": "carry"}})


class TestNotifyGate(unittest.TestCase):
    def test_one_toast_per_slot_across_workers(self):
        gate, toasts = NotifyGate(), []
        with tempfile.TemporaryDirectory() as tmp:
            ws = []
            for m, s in (("NQ", "NDX"), ("ES", "SPX")):
                c = cfgmod.from_dict({"market": m, "source": s, "provider": {"name": "synthetic", "live_clock": False},
                                      "storage": {"root": tmp}})
                w = MarketWorker(c, gate)
                w.notify_desktop = lambda t, b: toasts.append(t)
                ws.append(w)
            now = datetime(2026, 10, 20, 16, 0, tzinfo=timezone.utc)
            for w in ws:
                w.step(now)
            self.assertEqual(len(toasts), 1)
            self.assertTrue(all(w.published for w in ws))
            self.assertEqual({w.key for w in ws}, {"NQ-SYNTHETIC", "ES-SYNTHETIC"})


if __name__ == "__main__":
    unittest.main()
