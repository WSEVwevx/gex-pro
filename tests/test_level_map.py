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


SRC = "\n".join([next(l for l in JS.splitlines() if l.startswith(p)) for p in ("const esc =", "const num =", "const money =", "const signed =", "const PROBE_HINT =")]
                + ["const MAP_SPAN = 3.3;", piece("function niceStep(", "}"), piece("function fieldAt("), piece("function renderLevelMap(")])
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
    return json.loads(subprocess.run(["node"], input=js, capture_output=True, encoding="utf-8", check=True).stdout)


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


# the field: an index-price profile times the frozen basis; the net crosses zero halfway between 26,900 and 27,100
F_ = 1.002
W_F = {"source": "NDX", "result": {"mapped": {"mapping": {"factor": F_}}, "session": {"levels": {}},
                                    "profile": [{"price": 26500.0, "net": 3e9}, {"price": 26900.0, "net": 1e9},
                                                {"price": 27100.0, "net": -1e9}, {"price": 27300.0, "net": -2e9}]}}
X_F = {**X_, "profile": {"base_fut": 26500.0, "width_fut": 25.0, "values": [99, 0, -50], "max_abs": 4e8}}


def fieldAt(curve, at):
    js = piece("function fieldAt(") + f"\nconsole.log(JSON.stringify(fieldAt({json.dumps(curve)}, {json.dumps(at)})))"
    return json.loads(subprocess.run(["node"], input=js, capture_output=True, encoding="utf-8", check=True).stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Field(unittest.TestCase):
    def geom(self, svg):
        W, H = map(int, re.search(r'viewBox="0 0 (\d+) (\d+)"', svg).groups())
        lo, hi, top, bot = REF - 3.3 * EM, REF + 3.3 * EM, 14, H - 14
        xr = 112 if W < 420 else 168
        return (lambda v: bot - (v - lo) / (hi - lo) * (bot - top)), round(xr + (W - 2 - xr) / 2), (W - 2 - xr) * 0.42

    def test_the_curve_crosses_the_meridian_at_zero_gamma(self):
        svg = draw(w=W_F, X=X_F)["svg"]
        y, xm, half = self.geom(svg)
        path = re.search(r'<path d="([^"]+)" class="m-curve"', svg).group(1)
        pts = [tuple(map(float, m)) for m in re.findall(r"[ML]([\d.]+) ([\d.]+)", path)]
        self.assertEqual(len(pts), 4)
        for (x, yy), (p, n) in zip(pts, [(26500, 3e9), (26900, 1e9), (27100, -1e9), (27300, -2e9)]):
            self.assertAlmostEqual(x, xm + n / 3e9 * half, delta=0.06)          # right = positive, scaled to the largest
            self.assertAlmostEqual(yy, y(p * F_), delta=0.06)                   # index price times the frozen basis
        (x0, y0), (x1, y1) = pts[1], pts[2]
        self.assertAlmostEqual(y0 + (y1 - y0) * (xm - x0) / (x1 - x0), y(27000 * F_), delta=0.1)

    def test_the_bead_sits_on_the_meridian_at_the_price(self):
        svg = draw(w=W_F, X=X_F)["svg"]
        y, xm, _ = self.geom(svg)
        cx, cy = map(float, re.search(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="6" class="m-bead"', svg).groups())
        self.assertEqual(cx, xm)
        self.assertAlmostEqual(cy, y(REF), places=6)

    def test_the_tone_is_deepest_at_the_largest_strike_and_absent_at_zero(self):
        svg = draw(w=W_F, X=X_F)["svg"]
        tones = re.findall(r'fill-opacity="([\d.]+)" class="m-tone (pos|neg)"', svg)
        self.assertEqual(tones, [("1.00", "pos"), ("0.58", "neg")])              # 0.15 + 0.85 x |v| / 99; v = 0 is not drawn

    def test_the_words_say_what_the_picture_shows(self):
        svg = draw(w=W_F, X=X_F)["svg"]
        words = re.search(r'<p class="vh">([^<]+)</p>', svg).group(1)
        # at 26,594.97: between 26,500 x 1.002 = 26,553 (3e9) and 26,900 x 1.002 = 26,953.8 (1e9)
        here = 3e9 + (1e9 - 3e9) * (REF - 26500 * F_) / (400 * F_)
        self.assertIn(f"NQ 26,594.97. Total modeled gamma at the price: +${here / 1e9:.2f}B per 1% move.", words)
        self.assertIn("It crosses zero at 27,361.75.", words)
        self.assertIn("Deepest strike tone: 26,500, positive.", words)
        self.assertIn('<div class="m-probe">Point at the field for the gamma at any price; tap or click to measure from the price.</div><div class="m-tapeout" aria-live="polite"></div>', svg)

    def test_no_profile_draws_no_curve_and_says_unavailable(self):
        svg = draw()["svg"]
        self.assertNotIn("m-curve", svg)
        self.assertIn("Total modeled gamma at the price: unavailable.", svg)

    def test_the_probe_reads_the_same_scale_back(self):
        fn = piece("function renderLevelMap(")
        self.assertIn("const at = yy => hi - (yy - top) / (bot - top) * (hi - lo);", fn)       # the inverse of y(v)
        self.assertIn("y = v => bot - (v - lo) / (hi - lo) * (bot - top)", fn)
        self.assertIn('total if price were here ${tot == null ? "unavailable" : money(tot)}', fn)
        self.assertIn('strike gamma ${!b ? "none saved here" : b[2] ? "about " + money(b[1]) : "under 1% of the largest"}', fn)

    def test_the_tape_measures_in_points_percent_and_sigma(self):
        line = next(l for l in JS.splitlines() if l.startswith("const tapeText ="))
        src = "\n".join([next(l for l in JS.splitlines() if l.startswith(p)) for p in ("const num =", "const signed =")] + [line,
              "console.log(JSON.stringify([tapeText('CW', 28881.5, 25099.91, 1254.33), tapeText('', 24770, 25099.91, 1254.33),"
              " tapeText('', 25099.91, 25099.91, 1254.33), tapeText('PW', 24770, 25099.91, null)]))"])
        a, b, c, e = json.loads(subprocess.run(["node"], input=src, capture_output=True, encoding="utf-8", check=True).stdout)
        # 3,781.59 / 25,099.91 = 15.066%, / 1,254.33 = 3.01σ; 329.91 / 25,099.91 = 1.314%, / 1,254.33 = 0.26σ
        self.assertEqual(a, "CW 28,881.50 is +3,782 pts · +15.07% · +3.0σ from the price 25,099.91")
        self.assertEqual(b, "24,770.00 is -330 pts · -1.31% · -0.3σ from the price 25,099.91")
        self.assertEqual(c, "25,099.91 is 0 pts · 0.00% · 0.0σ from the price 25,099.91")
        self.assertEqual(e, "PW 24,770.00 is -330 pts · -1.31% · σ unavailable from the price 25,099.91")

    def test_the_tape_snaps_to_a_level_within_ten_pixels(self):
        fn = piece("function renderLevelMap(")
        self.assertIn("lines.filter(l => l.v >= lo && l.v <= hi && Math.abs(y(l.v) - yy) <= 10)", fn)
        self.assertIn('box.querySelector(".m-tapeout").textContent = "Tape: " + tapeText(near ? near.k : "", v, ref, d);', fn)

    def test_the_curve_is_never_extrapolated(self):
        self.assertEqual(fieldAt([[1, 10], [3, 30]], 2), 20)
        self.assertIsNone(fieldAt([[1, 10], [3, 30]], 4))
        self.assertIsNone(fieldAt([], 1))


if __name__ == "__main__":
    unittest.main()
