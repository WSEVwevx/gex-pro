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

    def test_after_roll_uses_next_contract_and_micro_maps(self):
        code, exp = futures_expiry("MNQ", datetime(2026, 12, 11, 12, 0, tzinfo=NY))
        self.assertEqual(code, "NQH7")
        self.assertEqual(exp.date().isoformat(), "2027-03-19")

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

    def test_free_configs_validate(self):
        for f in ("free_nq_cboe", "free_es_cboe"):
            c = cfgmod.load(f"configs/{f}.json")
            self.assertEqual(c.futures_ref["mode"], "carry")
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
