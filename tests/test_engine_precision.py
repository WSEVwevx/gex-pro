"""Regression tests for the six engine defects found by stress test B1 (independent recomputation, 2026-11-10)."""
import dataclasses
import unittest
from datetime import datetime, timedelta, timezone

from gexsys import engine as eng, pricing
from gexsys.extras import compute_extras
from gexsys.providers.cboe import CboeProvider, merge_etf
from tests.util import ASOF, chain, contract


class TestOwnYield(unittest.TestCase):
    def test_converted_etf_leg_keeps_its_own_dividend_yield(self):
        # an ETF leg converted to index terms must keep the ETF's yield, or its gamma moves (QQQ 0.6% vs NDX 0.7%)
        idx = contract(100, iv=0.2, days=30)
        etf = dataclasses.replace(contract(101, iv=0.2, days=30), group_strike=100.0, div_yield=0.006)
        snap = chain([idx, etf], q=0.007, rate=0.04)
        self.assertEqual(eng.contract_q(etf, snap), 0.006)
        self.assertEqual(eng.contract_q(idx, snap), 0.007)
        res = eng.compute(snap, asof=ASOF)
        row = next(r for r in res.rows if r.contract.group_strike is not None)
        self.assertAlmostEqual(row.gamma, pricing.bsm_gamma(100.0, 101.0, row.t_years, 0.04, 0.006, 0.2), places=15)


class TestPlaceholderIV(unittest.TestCase):
    def test_vendor_iv_above_500pct_is_not_a_vol(self):
        # Cboe quotes 600-700% for deep in-the-money SPX calls: treated as missing, the neighbour's IV is borrowed
        deep = contract(40, iv=7.04, days=10, oi=1)
        near = [contract(k, iv=0.3, days=10) for k in (60, 98, 100, 102)]       # near-the-money OI, as real chains have
        res = eng.compute(chain([deep, *near]), asof=ASOF)
        row = next(r for r in res.rows if r.contract.strike == 40)
        self.assertEqual(row.iv, 0.3)

    def test_etf_placeholder_iv_is_solved_from_the_quote(self):
        exp = ASOF + timedelta(days=10)
        mid = pricing.bsm_price(500.0, 520.0, 10 / 365, 0.04, 0.006, 0.25, True)
        c = dataclasses.replace(contract(520, iv=6.5, days=10, bid=round(mid, 2) - 0.01, ask=round(mid, 2) + 0.01, exp=exp),
                                underlying="QQQ")
        out = merge_etf([contract(20800, days=10, exp=exp)], [c], 40.0, "NDX", 100.0, etf_spot=500.0, asof=ASOF, etf_q=0.006)
        self.assertAlmostEqual(out[0].iv, 0.25, delta=1e-3)
        self.assertEqual(out[0].div_yield, 0.006)


class TestStandardSeries(unittest.TestCase):
    def test_adjusted_and_special_series_are_left_out(self):
        ts = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)
        def opt(sym, oi=100):
            return {"option": sym, "iv": 0.2, "gamma": 0.001, "open_interest": oi, "bid": 1.0, "ask": 1.2, "volume": 1}
        raw = {"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
               "data": {"current_price": 7600.0, "options": [opt("SPXW261113C07600000"), opt("SPX261120C07600000"),
                                                             opt("SPXO261118C07600000")]}}
        prov = CboeProvider(http=lambda url, headers, limiter=None: raw, include_etf=False)
        snap = prov.fetch_snapshot("SPX", 45, True)
        self.assertEqual(sorted(c.root for c in snap.contracts), ["SPX", "SPXW"])
        self.assertTrue(any("non-standard" in w for w in snap.warnings))


class TestSettledSeries(unittest.TestCase):
    def test_am_settled_series_leave_max_pain_after_settlement(self):
        # monthly expiry day, 10:00 ET: the AM series settled at 09:30, the PM series still trade
        day = datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc)
        am, pm = day.replace(hour=14, minute=30), day.replace(hour=21)
        asof = day.replace(hour=15)
        cs = [contract(90, typ="P", oi=100000, iv=0.2, exp=am, root="SPX", asof=asof),     # would drag max pain to 90
              contract(100, typ="C", oi=100, iv=0.2, exp=pm, root="SPXW", asof=asof),
              contract(100, typ="P", oi=100, iv=0.2, exp=pm, root="SPXW", asof=asof),
              contract(110, typ="C", oi=50, iv=0.2, exp=pm, root="SPXW", asof=asof)]
        snap = dataclasses.replace(chain(cs), fetched_at=asof)
        res = eng.compute(snap, asof=asof)
        mp = compute_extras(snap, eng.EngineConfig(), res)["max_pain"]
        self.assertEqual([m["price"] for m in mp], [100.0])


class TestQuoteTime(unittest.TestCase):
    def test_missing_iv_is_solved_at_the_quote_time(self):
        # a 0DTE option quoted 15 minutes ago: its IV comes from the time left WHEN it was quoted
        asof = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)                 # 15:00 ET
        exp, quoted = asof + timedelta(hours=1), asof - timedelta(minutes=15)
        t_q = (exp - quoted).total_seconds() / (365 * 86400)
        px = pricing.bsm_price(1000.0, 1000.0, t_q, 0.0, 0.0, 0.3, True)          # at the money: the price pins the vol
        c = dataclasses.replace(contract(1000, iv=None, exp=exp, bid=px - 0.001, ask=px + 0.001, asof=asof), greeks_time=quoted)
        res = eng.compute(dataclasses.replace(chain([c], spot=1000.0), fetched_at=asof), asof=asof)
        self.assertAlmostEqual(res.rows[0].iv, 0.3, delta=2e-3)


if __name__ == "__main__":
    unittest.main()
