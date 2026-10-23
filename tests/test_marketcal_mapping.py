import unittest
from datetime import date, datetime, timedelta, timezone

from gexsys import marketcal as mc
from gexsys.mapping import MappingContext, MappingError, distance, map_summary, round_to_tick

U = timezone.utc


class TestCalendar(unittest.TestCase):
    def test_holidays_2026(self):
        h = mc.nyse_holidays(2026)
        for d in (date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
                  date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25)):
            self.assertIn(d, h, d)

    def test_saturday_new_year_not_observed(self):
        self.assertNotIn(date(2021, 12, 31), mc.nyse_holidays(2021))
        self.assertNotIn(date(2021, 12, 31), mc.nyse_holidays(2022))

    def test_early_closes(self):
        e = mc.early_closes(2026)
        self.assertIn(date(2026, 11, 27), e)
        self.assertIn(date(2026, 12, 24), e)
        self.assertNotIn(date(2026, 7, 3), e)            # holiday itself in 2026
        self.assertIn(date(2025, 7, 3), mc.early_closes(2025))
        self.assertEqual(mc.session_state(datetime(2026, 11, 27, 18, 30, tzinfo=U)), "ETH")   # 13:30 ET

    def test_dst_transitions(self):
        # 2026-03-08 spring forward. 09:35 EST = 14:35Z (Fri); 09:35 EDT = 13:35Z (Mon)
        self.assertEqual(mc.session_state(datetime(2026, 3, 6, 14, 35, tzinfo=U)), "RTH")
        self.assertEqual(mc.session_state(datetime(2026, 3, 6, 13, 35, tzinfo=U)), "ETH")
        self.assertEqual(mc.session_state(datetime(2026, 3, 9, 13, 35, tzinfo=U)), "RTH")
        # 2026-11-01 fall back. Mon 09:30 EST = 14:30Z
        self.assertEqual(mc.session_state(datetime(2026, 11, 2, 14, 30, tzinfo=U)), "RTH")
        self.assertEqual(mc.session_state(datetime(2026, 11, 2, 13, 45, tzinfo=U)), "ETH")

    def test_globex_hours(self):
        self.assertEqual(mc.session_state(datetime(2026, 10, 24, 15, 0, tzinfo=U)), "CLOSED")   # Saturday
        self.assertEqual(mc.session_state(datetime(2026, 10, 25, 22, 30, tzinfo=U)), "ETH")     # Sun 18:30 EDT
        self.assertEqual(mc.session_state(datetime(2026, 10, 20, 21, 30, tzinfo=U)), "CLOSED")  # 17:30 halt
        self.assertEqual(mc.session_state(datetime(2026, 12, 25, 15, 0, tzinfo=U)), "HOLIDAY")
        self.assertEqual(mc.refresh_interval(datetime(2026, 10, 20, 15, 0, tzinfo=U)), 60)

    def test_rollover(self):
        self.assertEqual(mc.roll_date(2026, 12), date(2026, 12, 10))
        self.assertEqual(mc.front_contract("NQ", date(2026, 12, 9)), "NQZ6")
        self.assertEqual(mc.front_contract("NQ", date(2026, 12, 10)), "NQH7")
        self.assertEqual(mc.front_contract("ES", date(2026, 10, 20)), "ESZ6")
        self.assertEqual(mc.front_contract("ES", date(2026, 9, 10)), "ESZ6")
        self.assertEqual(mc.front_contract("ES", date(2026, 9, 9)), "ESU6")

    def test_option_expiry_times(self):
        self.assertEqual(mc.option_expiry_time(date(2026, 11, 20), "SPX").hour, 9)
        self.assertEqual(mc.option_expiry_time(date(2026, 11, 20), "SPXW").hour, 16)
        self.assertEqual(mc.option_expiry_time(date(2026, 11, 27), "SPXW").hour, 13)   # early close
        t = mc.option_expiry_time(date(2026, 11, 20), "QQQ")
        self.assertEqual(t.utcoffset(), timedelta(hours=-5))                            # EST after DST end


class TestMapping(unittest.TestCase):
    T = datetime(2026, 10, 20, 15, 0, tzinfo=U)

    def ctx(self, market="NQ", source="NDX", method="ratio", f=20200.0, u=20000.0, ft=None, ut=None, **kw):
        return MappingContext(market, source, method, f, ft or self.T, u, ut or self.T, **kw)

    def test_ratio_and_offset(self):
        c = self.ctx()
        c.validate()
        self.assertAlmostEqual(c.map_price(19800), 19998.0)
        o = self.ctx(method="offset")
        o.validate()
        self.assertAlmostEqual(o.map_price(19800), 20000.0)

    def test_etf_requires_ratio(self):
        with self.assertRaises(MappingError):
            self.ctx(source="QQQ", method="offset", u=487.0).validate()
        c = self.ctx(source="QQQ", u=487.0)
        c.validate()
        self.assertAlmostEqual(c.map_price(490.0), 490.0 * 20200 / 487)

    def test_micro_contracts_share_full_size_sources(self):
        self.ctx(market="MNQ").validate()
        self.ctx(market="MES", source="SPY", f=5860, u=584).validate()

    def test_cross_index_refused(self):
        with self.assertRaises(MappingError):
            self.ctx(market="NQ", source="SPX").validate()

    def test_stale_basis_refused(self):
        with self.assertRaises(MappingError):
            self.ctx(ut=self.T - timedelta(minutes=10)).validate()
        with self.assertRaises(MappingError):
            self.ctx(u=None).validate()

    def test_futures_options_identity_and_calendar(self):
        c = MappingContext("ES", "ES_FOP", "identity", None, None, None, None)
        c.validate()
        self.assertEqual(c.map_price(5850), 5850)
        cal = MappingContext("ES", "ES_FOP", "calendar_offset", None, None, None, None, calendar_spread=52.5)
        cal.validate()
        self.assertEqual(cal.map_price(5850), 5902.5)
        with self.assertRaises(MappingError):
            MappingContext("ES", "ES_FOP", "calendar_offset", None, None, None, None).validate()

    def test_tick_and_distance(self):
        self.assertEqual(round_to_tick(20123.37, 0.25), 20123.25)
        d = distance(20000.0, 20012.5, 0.25)
        self.assertEqual(d["ticks"], 50.0)
        self.assertAlmostEqual(d["pct"], 0.0625)

    def test_map_summary_keeps_source_price(self):
        s = {"zero_gamma": {"price": 19900.0}, "call_wall": {"price": 20100.0}, "concentrations": [
            {"price": 20000.0, "share": 0.2, "sign": "+"}], "clusters": [], "zero_gamma_alternatives": [19900.0]}
        m = map_summary(s, self.ctx())
        self.assertEqual(m["call_wall"]["src_price"], 20100.0)
        self.assertEqual(m["call_wall"]["price"], round_to_tick(20100 * 1.01, 0.25))
        self.assertTrue(m["mapping"]["proxy"])


if __name__ == "__main__":
    unittest.main()
