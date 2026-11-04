"""Heatmap data: candle parsing, the per-snapshot heat profile, and columns read back from saved snapshots."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from gexsys import heatmap
from gexsys.ladder import HEAT_WINDOW
from gexsys.service import MarketWorker
from tests.test_integration import synth_cfg


class TestHeatmap(unittest.TestCase):
    def test_parse_candles_skips_empty_bars(self):
        raw = json.dumps({"chart": {"result": [{"timestamp": [100, 160, 220], "indicators": {"quote": [
            {"open": [1, None, 3], "high": [2, None, 4], "low": [0.5, None, 2.5], "close": [1.5, None, 3.5]}]}}]}}).encode()
        self.assertEqual(heatmap.parse_candles(raw), [[100, 1, 2, 0.5, 1.5], [220, 3, 4, 2.5, 3.5]])

    def test_bad_open_fixed(self):
        # the real 2026-10-30 15:00 ET NQ 5m bar: Yahoo's open (= high) was a stale 29562, the market ~28240
        bars = [[0, 28250.0, 28262.0, 28228.0, 28234.5], [300, 29562.0, 29562.0, 28283.25, 28307.75],
                [600, 28307.75, 28320.0, 28290.0, 28300.0]] + [[900 + 300 * i, 28300.0, 28330.0, 28290.0, 28310.0] for i in range(20)]
        out = heatmap.clean_candles([b[:] for b in bars])
        self.assertEqual(out[1], [300, 28234.5, 28307.75, 28234.5, 28307.75])
        self.assertEqual(out[0], bars[0])
        self.assertEqual(out[2:], bars[2:])

    def test_real_spike_kept(self):
        # a headline spike opens at the market and reverses inside the bar (NQ 2025-04-07 14:00 ET-like): kept as is
        bars = [[300 * i, 17200.0, 17260.0, 17180.0, 17240.0] for i in range(20)]
        bars[10] = [3000, 17273.0, 18361.5, 17163.0, 17658.5]
        bars[11] = [3300, 17658.0, 17700.0, 17500.0, 17550.0]
        self.assertEqual(heatmap.clean_candles([b[:] for b in bars]), bars)

    def test_profile_saved_and_read_back(self):
        # the synthetic chain is dated 2026-10-20: the worker's age-based cleanup must not delete it by the wall clock
        with tempfile.TemporaryDirectory() as tmp, mock.patch("gexsys.storage.SnapshotStore.prune"):
            w = MarketWorker(synth_cfg(tmp))
            w.step()
            s = w.result["summary"]
            h = s["heat"]
            self.assertLessEqual(h["base"], s["ref_price"] * (1 - HEAT_WINDOW) + h["w"])
            lo, hi = h["base"] - h["w"] / 2, h["base"] + (len(h["v"]) - 0.5) * h["w"]
            inside = sum(r["net"] for r in w.result["by_strike"] if lo <= r["strike"] < hi)     # the same refresh's strikes
            self.assertAlmostEqual(sum(h["v"]) * 1e6, inside, delta=1e5 * len(h["v"]))
            t0 = datetime.fromisoformat(s["asof"])
            out = heatmap.build(w, "5m", candles=[[int((t0 - timedelta(minutes=10)).timestamp()), 1, 2, 0.5, 1.5]])
            self.assertEqual(len(out["columns"]), 1)
            c = out["columns"][0]
            self.assertEqual((c["base"], c["w"], c["v"]), (h["base"], h["w"], h["v"]))
            self.assertNotIn("rel", c)
            self.assertIsNotNone(c["zg"] if s.get("zero_gamma") else 0)
            # a snapshot older than the first candle is left out
            later = heatmap.build(w, "5m", candles=[[int((t0 + timedelta(hours=3)).timestamp()), 1, 2, 0.5, 1.5]])
            self.assertEqual(later["columns"], [])

    def test_columns_are_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path
            day = Path(tmp) / "20261023"
            day.mkdir()
            t = datetime(2026, 10, 23, 13, tzinfo=timezone.utc)
            for i in range(heatmap.MAX_COLUMNS + 50):
                ts = t + timedelta(seconds=i)
                (day / f"{ts:%H%M%S}_{i:06d}.json").write_text(json.dumps({"asof": ts.isoformat(), "status": "OK",
                                                                            "heat": {"base": 0, "w": 1, "v": [1]}}))
            cols = heatmap.columns_from(Path(tmp), t - timedelta(hours=1))
            self.assertLessEqual(len(cols), heatmap.MAX_COLUMNS + 1)
            self.assertEqual(cols[-1]["t"], int((t + timedelta(seconds=heatmap.MAX_COLUMNS + 49)).timestamp()))   # newest kept


if __name__ == "__main__":
    unittest.main()
