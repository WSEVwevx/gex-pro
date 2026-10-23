"""Databento CME futures-options adapter, against canned responses in Databento's CSV layout."""
import csv
import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from gexsys import config as cfgmod
from gexsys import engine as eng
from gexsys import pricing
from gexsys.export import parse_payload
from gexsys.models import Quality
from gexsys.pipeline import run_once
from gexsys.providers.base import AuthError, ProviderError
from gexsys.providers.databento import DatabentoProvider, _price, _ts, session_start

NOW = datetime(2026, 12, 2, 15, 0, tzinfo=timezone.utc)          # Wednesday, US session open
R = 0.04


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S.%f000Z")


def table(rows: list[dict]) -> str:
    cols = list(dict.fromkeys(k for r in rows for k in r)) or ["instrument_id"]
    out = io.StringIO()
    w = csv.DictWriter(out, cols)
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()


THU = datetime(2026, 12, 3, 21, 0, tzinfo=timezone.utc)          # daily option (E1D) expiry
QTR = datetime(2026, 12, 18, 14, 30, tzinfo=timezone.utc)        # quarterly ES option expiry
EOM = datetime(2026, 12, 31, 21, 0, tzinfo=timezone.utc)         # end-of-month option on the March future
SETTLE_REF = datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc)    # session the settlement / OI refer to
F = {"ESZ6": 6800.0, "ESH7": 6850.0}
OPTS = [  # id, asset, raw symbol, underlying, C/P, strike, expiry, oi
    ("1", "E1D", "E1DZ6 C6800", "ESZ6", "C", 6800, THU, 1200),
    ("2", "E1D", "E1DZ6 P6800", "ESZ6", "P", 6800, THU, 1500),
    ("3", "E1D", "E1DZ6 P6750", "ESZ6", "P", 6750, THU, 900),
    ("4", "ES", "ESZ6 C6900", "ESZ6", "C", 6900, QTR, 4000),
    ("5", "ES", "ESZ6 P6700", "ESZ6", "P", 6700, QTR, 5000),
    ("6", "EW", "EWH7 C6900", "ESH7", "C", 6900, EOM, 800),      # other futures month -> shifted
    ("7", "ES", "ESZ6 C9000", "ESZ6", "C", 9000, QTR, 100),      # far outside the strike window
    ("8", "E1D", "E1DZ6 C6850", "ESZ6", "C", 6850, THU, 700),    # OI deleted -> dropped
    ("9", "E1D", "E1DZ6 C6900", "ESZ6", "C", 6900, THU, None),   # OI = 'not set' sentinel -> dropped
    ("10", "E1D", "ZZZ C6800", "NQZ6", "C", 6800, THU, 50),      # not an ES option
]
FUTS = [("100", "ESZ6"), ("101", "ESH7")]
QUOTED = {"1", "2", "4"}                                         # others fall back to settlement IV


def b76(o, f, t_from, vol=0.15):
    t = (o[6] - t_from).total_seconds() / (365 * 86400)
    return pricing.black76_price(f, o[5], t, R, vol, o[4] == "C")


class FakeDatabento:
    def __init__(self, bad_parent=None):
        self.calls, self.bad_parent = [], bad_parent

    def get(self, url):
        return {"dataset": "GLBX.MDP3", "start": "2010-06-06T00:00:00.000000000Z", "end": iso(NOW)}

    def post(self, url, data):
        self.calls.append(data)
        assert data["encoding"] == "csv" and data["pretty_px"] == "true"
        syms, schema = data["symbols"].split(","), data["schema"]
        if schema == "definition":
            if self.bad_parent and f"{self.bad_parent}.OPT" in syms:
                raise ProviderError("Databento HTTP 422: symbology_invalid_symbol")
            rows = [{"ts_recv": iso(NOW - timedelta(hours=10)), "instrument_id": i, "raw_symbol": s,
                     "security_update_action": "A", "instrument_class": "F", "expiration": iso(QTR),
                     "strike_price": "", "underlying": "", "asset": "ES", "security_type": "FUT"}
                    for i, s in FUTS if "ES.FUT" in syms]
            rows += [{"ts_recv": iso(NOW - timedelta(hours=10)), "instrument_id": o[0], "raw_symbol": o[2],
                      "security_update_action": "A", "instrument_class": o[4], "expiration": iso(o[6]),
                      "strike_price": f"{o[5]:.9f}", "underlying": o[3], "asset": o[1], "security_type": "OOF"}
                     for o in OPTS if f"{o[1]}.OPT" in syms or o[1] == "E1D" and "E1D.OPT" in syms]
            return table(rows)
        rows = []
        if schema == "statistics":
            for i, s in FUTS:
                if i in syms:
                    rows.append({"ts_recv": iso(SETTLE_REF + timedelta(hours=22)), "instrument_id": i,
                                 "ts_ref": iso(SETTLE_REF), "price": f"{F[s] - 10:.9f}", "quantity": str(2**63 - 1),
                                 "stat_type": "3", "update_action": "1", "stat_flags": "1"})
            for o in OPTS:
                if o[0] not in syms:
                    continue
                f_set = F[o[3]] - 10
                rows.append({"ts_recv": iso(SETTLE_REF + timedelta(hours=22)), "instrument_id": o[0],
                             "ts_ref": iso(SETTLE_REF), "price": f"{b76(o, f_set, SETTLE_REF):.9f}",
                             "quantity": str(2**63 - 1), "stat_type": "3", "update_action": "1", "stat_flags": "1"})
                rows.append({"ts_recv": iso(SETTLE_REF + timedelta(hours=30)), "instrument_id": o[0],
                             "ts_ref": iso(SETTLE_REF), "price": "", "stat_type": "9", "update_action": "1",
                             "quantity": str(o[7]) if o[7] is not None else str(2**63 - 1), "stat_flags": "0"})
                if o[0] == "8":
                    rows.append({"ts_recv": iso(SETTLE_REF + timedelta(hours=31)), "instrument_id": "8",
                                 "ts_ref": iso(SETTLE_REF), "price": "", "quantity": "700", "stat_type": "9",
                                 "update_action": "2", "stat_flags": "0"})
        elif schema == "bbo-1m":
            for i, s in FUTS:
                if i in syms:
                    rows.append({"ts_recv": iso(NOW - timedelta(minutes=1)), "instrument_id": i,
                                 "bid_px_00": f"{F[s] - 0.25:.9f}", "ask_px_00": f"{F[s] + 0.25:.9f}"})
            for o in OPTS:
                if o[0] in syms and o[0] in QUOTED:
                    m = b76(o, F[o[3]], NOW)
                    rows.append({"ts_recv": iso(NOW - timedelta(minutes=2)), "instrument_id": o[0],
                                 "bid_px_00": f"{m - 0.05:.9f}", "ask_px_00": f"{m + 0.05:.9f}"})
        elif schema == "ohlcv-1h":
            rows = [{"ts_event": iso(NOW - timedelta(hours=1)), "instrument_id": i, "volume": "40"} for i in syms]
            rows += [{"ts_event": iso(NOW - timedelta(hours=2)), "instrument_id": i, "volume": "60"} for i in syms]
        return table(rows)


def provider(fake=None, **kw):
    fake = fake or FakeDatabento()
    return DatabentoProvider(api_key="db-test", post=fake.post, get_json=fake.get, clock=lambda: NOW, rate=R, **kw), fake


class TestParsing(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(_price("6800.250000000"), 6800.25)
        self.assertEqual(_price("6800250000000"), 6800.25)                      # raw fixed point
        self.assertIsNone(_price(str(2**63 - 1)))
        self.assertIsNone(_price(""))
        self.assertEqual(_ts("2026-12-02T15:00:00.123456789Z"), datetime(2026, 12, 2, 15, 0, 0, 123456, timezone.utc))
        self.assertEqual(_ts("1796223600000000000"), datetime(2026, 12, 2, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(session_start(NOW).hour, 18)                          # Tue 18:00 ET for Wed morning
        self.assertEqual(session_start(datetime(2026, 12, 5, 15, tzinfo=timezone.utc)).date().isoformat(), "2026-12-03")


class TestSnapshot(unittest.TestCase):
    def test_chain(self):
        p, fake = provider()
        s = p.fetch_snapshot("ES_FOP", max_dte=45, include_0dte=True)
        self.assertEqual((s.underlying, s.spot, s.spot_quality), ("ESZ6", 6800.0, Quality.REALTIME))
        self.assertEqual(s.prev_close, 6790.0)                                   # front future's settlement
        by = {c.symbol: c for c in s.contracts}
        self.assertEqual(set(by), {"E1DZ6 C6800", "E1DZ6 P6800", "E1DZ6 P6750", "ESZ6 C6900", "ESZ6 P6700",
                                   "EWH7 C6900"})                                # far, deleted OI, unset OI, NQ dropped
        self.assertEqual(by["EWH7 C6900"].strike, 6850.0)                        # shifted by ESZ6 - ESH7 = -50
        self.assertTrue(any("shifted" in w for w in s.warnings))
        for c in s.contracts:
            self.assertEqual(c.multiplier, 50.0)
            self.assertAlmostEqual(c.iv, 0.15, delta=0.01, msg=c.symbol)         # live-quote and settlement IV
            self.assertEqual(c.volume, 100.0)
        self.assertEqual(by["E1DZ6 C6800"].quote_quality, Quality.REALTIME)
        self.assertIsNone(by["E1DZ6 P6750"].bid)                                  # not quoted -> settlement IV
        self.assertEqual(by["ESZ6 C6900"].exercise_style, "american")
        self.assertEqual(by["E1DZ6 C6800"].exercise_style, "european")
        # quotes and volume requested only for options that have open interest
        bbo = [c for c in fake.calls if c["schema"] == "bbo-1m"][-1]["symbols"].split(",")
        self.assertNotIn("8", bbo)

    def test_reference_data_cached_between_refreshes(self):
        p, fake = provider()
        p.fetch_snapshot("ES_FOP")
        n = {k: sum(c["schema"] == k for c in fake.calls) for k in ("definition", "statistics")}
        p.fetch_snapshot("ES_FOP")
        self.assertEqual(sum(c["schema"] == "definition" for c in fake.calls), n["definition"])
        self.assertEqual(sum(c["schema"] == "statistics" for c in fake.calls), n["statistics"])

    def test_unknown_series_is_skipped_not_fatal(self):
        p, _ = provider(FakeDatabento(bad_parent="E5D"))
        s = p.fetch_snapshot("ES_FOP")
        self.assertEqual(len(s.contracts), 6)
        self.assertTrue(any("E5D" in w for w in s.warnings))

    def test_key_required_and_index_sources_refused(self):
        with self.assertRaises(AuthError):
            DatabentoProvider(api_key="")._auth()
        with self.assertRaises(ProviderError):
            provider()[0].fetch_snapshot("SPX")
        with self.assertRaises(eng.ConfigError):
            cfgmod.from_dict({"market": "ES", "source": "SPX", "provider": {"name": "databento"}})


class TestPipeline(unittest.TestCase):
    def test_levels_in_futures_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cfgmod.load("configs/databento_es.json")
            c.storage = {"root": tmp}
            p, _ = provider()
            r = run_once(c, p)
            s = r["summary"]
            self.assertNotEqual(s["status"], "UNAVAILABLE")
            self.assertEqual(s["provider"], "DATABENTO")
            d = parse_payload(r["pine"])
            self.assertEqual((d["mkt"], d["src"], d["map"]), ("ES", "ES_FOP", "identity"))
            self.assertTrue(6600 < float(d["cw"]) < 7000)


if __name__ == "__main__":
    unittest.main()
