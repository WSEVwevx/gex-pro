"""A chain shaped like the OCC provider's (open interest + one vol, no quotes), the ETF merge, combined payloads,
carry-model futures basis, and the one-toast-per-slot gate."""
import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from gexsys import config as cfgmod, marketcal
from gexsys.basis import carry_fair_value, futures_expiry
from gexsys.export import combine, parse_combined
from gexsys.mapping import SOURCES
from gexsys.marketcal import NY, rth_close
from gexsys.models import ChainSnapshot, OptionContract, OptionType, Quality
from gexsys.pipeline import run_once
from gexsys.providers.common import merge_etf
from gexsys.service import MarketWorker, NotifyGate

NOW = datetime.now(timezone.utc)
EXP = (NOW + timedelta(days=3)).date()


def contracts(root, strikes, oi, iv=0.19, mult=100, under=None):
    out = []
    for k in strikes:
        for t in (OptionType.CALL, OptionType.PUT):
            out.append(OptionContract(symbol=f"{root}{EXP:%y%m%d}{t.value}{int(k * 1000):08d}", root=root,
                                      underlying=under or root, option_type=t, strike=float(k),
                                      expiration=marketcal.option_expiry_time(EXP, root), multiplier=mult,
                                      open_interest=oi(k), iv=iv, oi_quality=Quality.EOD))
    return out


def ndx_snap(spot=29490.28, extra=()):
    src = SOURCES["NDX"]
    return ChainSnapshot(underlying=src.vendor_symbol, source_kind=src.kind, spot=spot, spot_time=NOW - timedelta(minutes=1),
                         spot_quality=Quality.DELAYED, contracts=contracts("NDXP", range(29000, 30001, 100), lambda k: 100.0 + k % 700,
                                                                          under="NDX") + list(extra),
                         source="test", fetched_at=NOW, prev_close=29400.0, rate=0.04, div_yield=0.007)


class Fake:
    """A provider giving one canned snapshot, labelled like the OCC chain."""
    name, label = "occ", "OCC"

    def __init__(self, snap=None):
        self.snap = snap

    def fetch_snapshot(self, *a, **k):
        return self.snap or ndx_snap()


class TestExpiryTime(unittest.TestCase):
    def test_pm_settled_ndxp_expires_at_the_calendars_close(self):
        # 16:00 ET, or 13:00 on an early close such as the day after Thanksgiving. Ask the calendar, never assume 16.
        c = contracts("NDXP", [29000], lambda k: 1.0)[0]
        self.assertEqual(c.expiration.astimezone(NY).hour, rth_close(EXP).hour)


class TestEtfMerge(unittest.TestCase):
    def merged(self):
        idx = ndx_snap().contracts
        qqq = contracts("QQQ", (703, 704, 712, 713, 715, 716, 740), lambda k: 4120.0, iv=0.2)
        return merge_etf(idx, qqq, 29490.28 / 715.0, "NDX", 100)

    def test_converted_into_index_contracts(self):
        from gexsys import pricing
        q = self.merged()
        r = 29490.28 / 715.0
        self.assertTrue(q and all(c.symbol.endswith("@NDX") and c.multiplier == 100 for c in q))
        self.assertTrue(all(c.bid is None and c.gamma is None and c.iv == 0.2 for c in q))
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
        res = eng.compute(ndx_snap(extra=q), eng.EngineConfig(max_dte=45))
        self.assertIn(29400.0, res.by_strike)
        self.assertFalse(any(abs(k - 712 * r) < 1e-6 for k in res.by_strike))   # no stray unsnapped level
        # dollar gamma is unchanged by the conversion (exact identity, not an approximation)
        t, iv = 3 / 365, 0.2
        own = 4120.0 * pricing.bsm_gamma(715.0, 715.0, t, 0.04, 0, iv) * 100 * 715.0 ** 2
        conv = 4120.0 / r * pricing.bsm_gamma(29490.28, 715.0 * r, t, 0.04, 0, iv) * 100 * 29490.28 ** 2
        self.assertAlmostEqual(own / conv, 1.0, places=9)

    def test_survives_normalize_and_the_config_rules(self):
        from gexsys.normalize import normalize
        s = normalize(ndx_snap(extra=self.merged()), check_occ=True)
        self.assertTrue(any(c.root == "QQQ" for c in s.contracts))     # not rejected as OCC mismatches
        with self.assertRaises(Exception):
            cfgmod.from_dict({"market": "NQ", "source": "QQQ", "provider": {"name": "occ"},
                              "mapping": {"method": "ratio"}})
        self.assertEqual(cfgmod.load("configs/free_nq.json").provider, {"name": "occ"})


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
        a = "GEX1;prov=OCC;mkt=NQ;zg=1.00;L="
        b = "GEX1;prov=OCC;mkt=ES;zg=2.00;L="
        parsed = parse_combined(combine([a, "", b]))
        self.assertEqual([(p["prov"], p["mkt"]) for p in parsed], [("OCC", "NQ"), ("OCC", "ES")])

    def test_pipeline_labels_provider_maps_with_carry_and_separates_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cfgmod.from_dict({"market": "NQ", "source": "NDX", "provider": {"name": "occ"},
                                  "futures_ref": {"mode": "carry", "rate": 0.04, "div_yield": 0.007},
                                  "engine": {"recompute_greeks": "always", "max_dte": 45, "max_spot_age_s": 1800},
                                  "storage": {"root": tmp}})
            from gexsys.storage import SnapshotStore
            r = run_once(c, Fake(), SnapshotStore(tmp))
            self.assertIn("prov=OCC;", r["pine"])
            self.assertEqual(r["summary"]["provider"], "OCC")
            self.assertIsNotNone(r["mapped"])
            self.assertGreater(r["mapped"]["mapping"]["factor"], 1.0)        # r > q: futures above index
            self.assertIn("carry-model", r["mapped"]["mapping"]["futures_ref_mode"])
            self.assertEqual(len(list(SnapshotStore(tmp).iter_summaries("NQ-OCC"))), 1)

    def test_measured_basis_is_a_session_median_with_carry_fallback(self):
        # stress test C1: the 4% carry model sat 22 NQ points below the market; the measured basis is the median
        # futures / index ratio of the last 15 minutes both traded, restarted after an hour's gap, like the indicator
        from gexsys import basis
        t0 = int(datetime(2026, 11, 9, 15, 0, tzinfo=NY).timestamp())
        idx = {t0 + 60 * i: 100.0 + 0.1 * (i * 7 % 5) for i in range(30)}     # prices that move, as real ones do
        fut = {t: v * 1.004 for t, v in idx.items()}
        fut[t0 + 60 * 29] = 150.0                                          # one bad print: the median ignores it
        idx[t0 + 86400] = 100.0                                            # next day, one minute only: a new session
        fut[t0 + 86400] = 100.35
        r, when = basis.median_ratio(fut, idx, datetime(2026, 11, 9, 23, 0, tzinfo=NY))
        self.assertEqual((round(r, 12), when.timestamp()), (1.004, t0 + 60 * 29))
        self.assertAlmostEqual(basis.median_ratio(fut, idx, datetime(2026, 11, 10, 16, 0, tzinfo=NY))[0], 1.0035, places=12)
        orig = basis._yahoo_1m
        try:
            basis._yahoo_1m = lambda sym, asof: fut if "=F" in sym else idx
            ob = basis.observed_basis("NDX", datetime(2026, 11, 9, 23, 0, tzinfo=NY))
            self.assertAlmostEqual(ob[0], 1.004, places=12)
            self.assertIn("NQ=F", ob[2])
            self.assertIsNone(basis.observed_basis("NDX", datetime(2026, 11, 20, 12, 0, tzinfo=NY)))   # stale
            # 2026-11-17 audit: bars ending Tuesday, read on Thursday evening, were inside a flat 4-day allowance;
            # anything older than the last session's close is stale
            self.assertIsNone(basis.observed_basis("NDX", datetime(2026, 11, 12, 20, 0, tzinfo=NY)))
            # stress test E1: bars shifted an hour gave a plausible but 93-point-wrong ratio; 0.6% from carry is refused
            far = {t: v * 1.006 for t, v in fut.items()}
            basis._yahoo_1m = lambda sym, asof: far if "=F" in sym else idx
            self.assertIsNone(basis.observed_basis("NDX", datetime(2026, 11, 9, 23, 0, tzinfo=NY)))
            # 2026-11-17 audit: shifted a little less, the ratio stays inside the 0.3% guard (29 NQ points off on
            # live bars) - but the two series no longer move together minute by minute, which aligned bars always do
            late = {t + 60: v for t, v in fut.items()}
            basis._yahoo_1m = lambda sym, asof: late if "=F" in sym else idx
            self.assertIsNone(basis.observed_basis("NDX", datetime(2026, 11, 9, 23, 0, tzinfo=NY)))
            def down(sym, asof):
                raise OSError("offline")
            basis._yahoo_1m = down
            self.assertIsNone(basis.observed_basis("SPX", datetime(2026, 11, 9, 23, 0, tzinfo=NY)))
            with tempfile.TemporaryDirectory() as tmp:
                c = cfgmod.from_dict({"market": "NQ", "source": "NDX", "provider": {"name": "occ"},
                                      "futures_ref": {"mode": "observed", "rate": 0.04, "div_yield": 0.007},
                                      "engine": {"recompute_greeks": "always", "max_dte": 45, "max_spot_age_s": 1800},
                                      "storage": {"root": tmp}})
                r = run_once(c, Fake())
                self.assertIn("measured basis unavailable", r["mapped"]["mapping"]["futures_ref_mode"])
        finally:
            basis._yahoo_1m = orig

    def test_free_configs_validate(self):
        for f in ("free_nq", "free_es"):
            c = cfgmod.load(f"configs/{f}.json")
            self.assertEqual(c.futures_ref["mode"], "observed")
        with self.assertRaises(Exception):
            cfgmod.from_dict({"market": "ES", "source": "SPY", "provider": {"name": "occ"},
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
