"""The Levels page's level map (dashboard/assets/app.js renderLevelMap): drawn to one scale, honest about what is off it.

Runs the real function in node with a stand-in for the page, on the NQ numbers of 2026-11-19 22:45 ET (OCC backup)."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "assets" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "assets" / "terminal.css").read_text(encoding="utf-8")


def piece(start, end="\n}"):
    return start + JS.split(start, 1)[1].split(end, 1)[0] + end


SRC = "\n".join([next(l for l in JS.splitlines() if l.startswith(p)) for p in ("const esc =", "const num =", "const signed =")]
                + ["const MAP_SPAN = 3.3;", piece("function niceStep(", "}"), piece("function renderLevelMap(")])
STUB = """
const els = {lvMap: {innerHTML: "", clientWidth: %d}, lvMapSub: {textContent: ""}}, $ = id => els[id], market = "NQ";
renderLevelMap(%s, %s, %s, %s);
console.log(JSON.stringify({svg: els.lvMap.innerHTML, sub: els.lvMapSub.textContent}));
"""
REF, EM = 26594.97, 557.15
W_ = {"source": "NDX", "result": {"mapped": {}, "session": {"levels": {"C1": 27009.25, "P1": 26387.25}}}}
L_ = {"zero_gamma": {"price": 27361.75}, "call_wall": {"price": 28859.5}, "put_wall": {"price": 26387.25}}
X_ = {"expected_move": {"daily_points_fut": EM, "anchor_fut": 26595.0}, "profile": {"base_fut": 25926.0, "width_fut": 25.07, "values": [-3, 0, -52, 4]}}


def draw(width=560, w=W_, L=L_, X=X_, ref=REF):
    js = SRC + STUB % (width, json.dumps(w), json.dumps(L), json.dumps(X), json.dumps(ref))
    return json.loads(subprocess.run(["node", "-e", js], capture_output=True, encoding="utf-8", check=True).stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class LevelMap(unittest.TestCase):
    def test_levels_sit_on_one_linear_scale(self):
        svg = draw()["svg"]
        H = int(re.search(r'viewBox="0 0 \d+ (\d+)"', svg).group(1))
        lo, hi, top, bot = REF - 3.3 * EM, REF + 3.3 * EM, 14, H - 14
        y = lambda v: bot - (v - lo) / (hi - lo) * (bot - top)
        for cls, v in (("zg", 27361.75), ("pos", 27009.25), ("neg", 26387.25)):
            got = [float(m) for m in re.findall(rf'y1="([\d.]+)"[^>]*class="m-lv {cls}', svg)]
            self.assertTrue(any(abs(g - y(v)) < 0.01 for g in got), (cls, v, got, y(v)))
        px = float(re.search(r'y1="([\d.]+)"[^>]*class="m-px"', svg).group(1))
        self.assertAlmostEqual(px, y(REF), places=6)

    def test_a_level_beyond_the_scale_is_pinned_with_an_arrow(self):
        svg = draw()["svg"]
        self.assertIn("↑ CW <tspan", svg)                                # the call wall is 4.1σ away: beyond 3.3σ
        self.assertRegex(svg, r'class="m-lv pos off"')
        self.assertIn("+2,265 pts · +4.1σ", svg)                         # its real distance is still printed

    def test_the_same_price_twice_is_one_line(self):
        svg = draw()["svg"]
        self.assertIn("P1 · PW <tspan", svg)
        self.assertEqual(svg.count('class="m-lv neg'), 1)

    def test_labels_never_overlap_and_stay_inside(self):
        for width in (327, 560):
            svg = draw(width)["svg"]
            H = int(re.search(r'viewBox="0 0 \d+ (\d+)"', svg).group(1))
            ys = [float(v) for v in re.findall(r'<text x="0" y="([\d.]+)" class="m-k', svg)]
            pill = [float(v) + 9 for v in re.findall(r'<rect x="0" y="([\d.-]+)" width="[\d.]+" height="22"', svg)]   # its centre less 2, like a label's
            ys = sorted(ys + pill)
            self.assertTrue(all(b - a >= 27.9 for a, b in zip(ys, ys[1:])), ys)
            self.assertTrue(all(0 < v < H for v in ys), ys)

    def test_the_subtitle_names_the_prices_it_uses(self):
        self.assertEqual(draw()["sub"], "NQ equiv. of NDX · ±3.3σ around the price")
        self.assertIn(">NQ eq. 26,594.97</text>", draw()["svg"])           # the pill names the converted price too
        unmapped = {"source": "NDX", "result": {"session": W_["result"]["session"]}}
        self.assertEqual(draw(w=unmapped)["sub"], "NDX prices · ±3.3σ around the price")

    def test_no_expected_move_says_so(self):
        out = draw(X={"expected_move": {}})
        self.assertIn("No map in this update", out["svg"])
        self.assertEqual(out["sub"], "")

    def test_the_map_has_help_and_old_data_is_marked_on_the_headline(self):
        self.assertIn('data-help="level_map"', (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8"))
        self.assertIn("  level_map: {title:", JS)
        self.assertIn("body.stale-data #lvHead .lvh-px .eyebrow::after{content:var(--stale-text)", CSS)
        self.assertIn('<div class="lvh-px"><div class="eyebrow">${esc(market)} ${w.result.mapped ? "equiv. of " + esc(w.source) : esc(w.source)}${refAt(s.ref_time)}</div>', JS)


if __name__ == "__main__":
    unittest.main()
