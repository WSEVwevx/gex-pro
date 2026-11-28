"""The OCC chain with the previous session's LSE smile (rework workstream 4): source occ+lse, its own folder, 0DTE
left out, a lagging session re-levelled by the VIX-family curve, and the VIX-family curve whenever LSE has nothing.

Synthetic rows shaped like LSE's /v3/options/chain rows (no LSE value may sit in the repo); a stub client stands in
for gexsys/providers/lse.py, so no test reaches the network."""
import math
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from gexsys import config as cfgmod, marketcal, smile as S
from gexsys.pipeline import run_once
from gexsys.providers.base import ProviderUnavailable
from gexsys.providers.common import dividend_yield, risk_free_rate
from gexsys.providers.lse import CREDIT
from gexsys.providers.occ import OccProvider
from tests.test_occ_chain import NOW, ROOT, ndx_pages, opener_for

UTC = timezone.utc


def truth(x):
    return 0.22 - 0.40 * x + 1.5 * x * x


def rows_for(session: date, root: str, s0: float, step: float, expiries=("2026-11-20", "2026-12-18"), level=1.0):
    """OTM rows every `step` across +-6%, each traded in the session's last hour at the true IV for its own x."""
    close = marketcal.rth_close_dt(session)
    r, q = risk_free_rate(), dividend_yield("QQQ" if root == "QQQ" else "NDX")
    out = []
    for e in expiries:
        exp = marketcal.option_expiry_time(date.fromisoformat(e), root)
        k = s0 * 0.94
        i = 0
        while k <= s0 * 1.06:
            when = close - timedelta(minutes=5 + (i * 7) % 50)
            t = (exp - when).total_seconds() / S.YEAR_S
            f = s0 * math.exp((r - q) * t)
            iv = level * truth(math.log(k / f) / math.sqrt(t))
            out.append({"strike": round(k, 2), "iv": iv, "greeks_underlying_price": s0, "volume_today": 5 + i % 40,
                        "contract_type": "put" if k < f else "call", "expiry": e,
                        "last_trade_at": when.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.123456789")})
            k += step
            i += 1
    return out


class StubLse:
    """session_chain / cached as gexsys.providers.lse.LseClient answers them, from a dict {(root, session): rows}."""

    def __init__(self, landed: dict, fail: Exception = None):
        self.landed, self.fail, self.asked = landed, fail, []

    def session_chain(self, root, session, **filters):
        self.asked.append((root, session, filters))
        if self.fail:
            raise self.fail
        rows = self.landed.get((root, session))
        return {"landed": True, "rows": rows, "session": session.isoformat()} if rows is not None else None

    def cached(self, root, session):
        rows = self.landed.get((root, session))
        return {"landed": True, "rows": rows} if rows is not None else None


THU, WED = date(2026, 11, 19), date(2026, 11, 18)


def landed(session=THU, level=1.0):
    return {("NDX", session): rows_for(session, "NDX", 26200, 50, level=level),
            ("NDXP", session): rows_for(session, "NDXP", 26200, 50, level=level),
            ("QQQ", session): rows_for(session, "QQQ", 637, 1, level=level)}


def snap(lse, now=NOW):
    p = OccProvider(cache_dir=None, opener=opener_for(ndx_pages()), clock=now.timestamp, lse=lse)
    return p.fetch_snapshot("NDX"), p


def contract(s, root, month, strike):
    return next(c for c in s.contracts if c.root == root and c.expiration.month == month and c.strike == strike)


class Smile(unittest.TestCase):
    def test_each_strike_gets_its_own_vol(self):
        s, p = snap(StubLse(landed()))
        self.assertEqual((s.source, p.label), ("occ+lse", "OCCLSE"))
        put, call = contract(s, "NDX", 12, 25000), contract(s, "NDX", 12, 27000)
        self.assertGreater(put.iv, call.iv)                                  # the skew a single curve vol cannot have
        r, q = risk_free_rate(), dividend_yield("NDX")
        for c in (put, call):
            t0 = (c.expiration - NOW).total_seconds() / S.YEAR_S
            self.assertAlmostEqual(c.iv, truth(S.moneyness(c.strike, 26200, t0, r, q)), delta=0.005)
        self.assertIn(f"smile: {CREDIT}, implied vols of the Nov 19 session", " ".join(s.warnings))
        self.assertTrue(s.warnings[0].startswith("estimate: OCC open interest (end of day) with each strike's implied vol"))
        self.assertEqual(p.smile_info["session"], "2026-11-19")
        qqq = next(c for c in s.contracts if c.root == "QQQ")
        self.assertIsNotNone(qqq.iv)

    def test_zero_dte_gets_no_vol(self):
        fri = datetime(2026, 11, 20, 13, 0, tzinfo=UTC)                     # 08:00 ET Friday: the 20th expires today
        s, _ = snap(StubLse(landed()), now=fri)
        today = [c for c in s.contracts if c.expiration.astimezone(marketcal.NY).date() == date(2026, 11, 20)]
        self.assertTrue(today)
        self.assertTrue(all(c.iv is None for c in today))
        self.assertTrue(all(c.iv for c in s.contracts if c.expiration.month == 12))

    def test_lse_failing_falls_back_to_the_curve_and_says_why(self):
        s, p = snap(StubLse({}, fail=ProviderUnavailable("unavailable: HTTP 503 from LSE")))
        self.assertEqual(s.source, "occ+vix")
        self.assertEqual(p.label, "OCCLSE")                                  # same folder: the snapshot says which chain
        self.assertIn("smile unavailable, the VIX-family curve is used: NDX: unavailable: HTTP 503 from LSE", " ".join(s.warnings))
        self.assertEqual(len({c.iv for c in s.contracts if c.root == "NDX" and c.expiration.month == 12}), 1)

    def test_not_landed_for_two_sessions_is_the_curve(self):
        s, _ = snap(StubLse({}))
        self.assertEqual(s.source, "occ+vix")
        self.assertIn("NDX: no LSE Greeks for Nov 19 or Nov 18 yet", " ".join(s.warnings))

    def test_a_session_late_is_moved_to_the_new_vol_level(self):
        # the 18th's market traded 10% richer; its smile, moved by the curve's own change 18th -> 19th, says so
        s, p = snap(StubLse(landed(WED, level=1.10)))
        self.assertEqual(s.source, "occ+lse")
        self.assertIn("LSE's Greeks for Nov 19 have not landed; the Nov 18 smile is moved to the Nov 19 vol level",
                      " ".join(s.warnings))
        c = contract(s, "NDX", 12, 25000)
        t0 = (c.expiration - NOW).total_seconds() / S.YEAR_S
        old, new = p._curve_on("NDX", p._hist, WED), p._curve_on("NDX", p._hist, THU)
        want = 1.10 * truth(S.moneyness(25000, 26200, t0, risk_free_rate(), dividend_yield("NDX"))) * new(t0) / old(t0)
        self.assertAlmostEqual(c.iv, want, delta=0.005)
        self.assertLess(new(t0) / old(t0), 1.0)                              # the test's closes fell 18th -> 19th

    def test_the_rows_asked_for_are_bounded(self):
        lse = StubLse(landed())
        snap(lse)
        roots = {a[0] for a in lse.asked}
        self.assertEqual(roots, {"NDX", "NDXP", "QQQ"})
        f = next(a[2] for a in lse.asked if a[0] == "NDX")
        self.assertEqual((f["min_dte"], f["max_dte"]), (1, 46))
        self.assertEqual((f["strike_min"], f["strike_max"]), (int(26200 * 0.75), int(26200 * 1.25) + 1))

    def test_pipeline_holds_it_like_the_backup_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = OccProvider(cache_dir=None, opener=opener_for(ndx_pages()), clock=NOW.timestamp, lse=StubLse(landed()))
            cfg = cfgmod.load(ROOT / "configs/free_nq.json")
            cfg.storage = {"root": tmp}
            r = run_once(cfg, prov)
        s = r["summary"]
        self.assertEqual((s["chain"], s["provider"]), ("occ+lse", "OCCLSE"))     # the store key: NQ-OCCLSE
        self.assertIn("per-strike smile", s["backup"])                     # no plan, no paste until workstream 7
        self.assertEqual(s["smile"]["credit"], CREDIT)


class HealthRow(unittest.TestCase):
    def row(self, summary):
        from gexsys.component import GexComponent
        from tests.test_occ_chain import worker
        w = worker()
        w.result = {"summary": summary}
        g = GexComponent([])
        g.workers = {"NQ-OCCLSE": w}
        with mock.patch.dict(os.environ, {"GEX_LSE": "", "LSE_KEY": ""}):
            return next(r for r in g.sources() if r["name"] == "NQ options chain")

    def test_the_chain_row_names_the_smile_and_its_credit(self):
        r = self.row({"backup": "x", "chain": "occ+lse",
                      "smile": {"session": "2026-11-19", "credit": CREDIT, "fits": {"NDX": [{}, {}], "QQQ": [{}]}}})
        self.assertEqual(r["provider"], f"OCC open interest + the previous session's smile ({CREDIT}) + Yahoo prices (NDX)")
        self.assertEqual(r["detail"], "each strike's vol from the 2026-11-19 session's smile (3 expiries fitted): walls, "
                                      "zero gamma, C1 and P1 only, 0DTE left out")

    def test_a_fallback_says_why_the_smile_was_not_used(self):
        r = self.row({"backup": "x", "chain": "occ+vix",
                      "warnings": ["smile unavailable, the VIX-family curve is used: NDX: no LSE Greeks for Nov 19 or Nov 18 yet"]})
        self.assertIn("VIX-family closes", r["provider"])
        self.assertEqual(r["detail"], "one implied vol per expiry (no skew): walls, zero gamma, C1 and P1 only, no 0DTE flip; "
                                      "the smile was not used: NDX: no LSE Greeks for Nov 19 or Nov 18 yet")

    def test_the_site_shows_the_credit_from_the_data_only(self):
        js = (ROOT / "dashboard/assets/app.js").read_text(encoding="utf-8")
        self.assertIn('s.chain === "occ+lse"', js)
        self.assertIn("esc(s.smile.credit)", js)


class Switch(unittest.TestCase):
    def test_lse_only_when_asked_with_a_key_and_never_on_github(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"LSE_KEY": "synthetic", "LOCALAPPDATA": tmp}):
            for env, want in (({"GEX_LSE": "", "GITHUB_ACTIONS": "", "GEX_NO_LSE": ""}, False),
                              ({"GEX_LSE": "1", "GITHUB_ACTIONS": "true", "GEX_NO_LSE": ""}, False),
                              ({"GEX_LSE": "1", "GITHUB_ACTIONS": "", "GEX_NO_LSE": "1"}, False),
                              ({"GEX_LSE": "1", "GITHUB_ACTIONS": "", "GEX_NO_LSE": ""}, True)):
                with mock.patch.dict(os.environ, env):
                    self.assertEqual(cfgmod._local_lse() is not None, want, env)
        self.assertIn('set "GEX_LSE=1"', (ROOT / "START.bat").read_text(encoding="utf-8"))

    def test_the_hosted_path_is_the_curve(self):
        with mock.patch.dict(os.environ, {"GEX_LSE": "1", "GITHUB_ACTIONS": "true"}):
            p = cfgmod.make_provider(cfgmod.load(ROOT / "configs/free_nq.json"))
        self.assertIsNone(p.lse)
        self.assertEqual(p.label, "OCC")


if __name__ == "__main__":
    unittest.main()
