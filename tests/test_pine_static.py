"""Static checks on the Pine script (no TradingView compiler is available here).

Catches the classes of mistakes that broke or warned before:
  * a function called before it is defined (Pine requires definition first)
  * a variable or parameter shadowing a Pine built-in (the `second` warning)
  * an input declared but never used, or unbalanced brackets
  * a payload key the script reads that the service never emits (silent "n/a" on the chart)
"""
import re
import unittest
from pathlib import Path

from gexsys.export import pine_payload

PINE = (Path(__file__).resolve().parent.parent / "pine" / "nq_es_gex_levels.pine").read_text(encoding="utf-8")
CODE = "\n".join(l.split("//")[0] if not l.strip().startswith("//") else "" for l in PINE.splitlines())
NO_STRINGS = re.sub(r'"(?:[^"\\]|\\.)*"', '""', CODE)
BUILTINS = {"open", "high", "low", "close", "volume", "time", "time_close", "year", "month", "weekofyear", "dayofmonth",
            "dayofweek", "hour", "minute", "second", "na", "bar_index", "last_bar_index", "timenow", "hl2", "hlc3",
            "ohlc4", "hlcc4", "location", "shape", "size", "color", "line", "label", "box", "table", "array", "map",
            "math", "str", "ta", "request", "input", "timeframe", "syminfo", "barstate", "session", "strategy", "display"}


class TestPineStatic(unittest.TestCase):
    def test_version_and_header(self):
        self.assertIn("//@version=6", PINE)
        self.assertRegex(PINE, r"indicator\(\"")

    def test_brackets_balanced(self):
        for o, c in ("()", "[]"):
            self.assertEqual(NO_STRINGS.count(o), NO_STRINGS.count(c), f"unbalanced {o}{c}")

    def test_functions_defined_before_use(self):
        lines = NO_STRINGS.splitlines()
        defs = {}
        for i, l in enumerate(lines):
            m = re.match(r"^([A-Za-z_]\w*)\(([^)]*)\)\s*=>", l)
            if m:
                defs.setdefault(m.group(1), i)
        self.assertGreater(len(defs), 15)
        for name, at in defs.items():
            for i, l in enumerate(lines[:at]):
                if re.search(rf"(?<![\w.]){name}\(", l):
                    self.fail(f"{name}() used on line {i + 1} before its definition on line {at + 1}")

    def test_no_builtin_shadowing(self):
        depth = 0                                   # open brackets carried from earlier lines = argument continuation
        for i, l in enumerate(NO_STRINGS.splitlines(), 1):
            if depth == 0:
                m = re.match(r"^([A-Za-z_]\w*)\(([^)]*)\)\s*=>", l)
                params = [p.split("=")[0].split()[-1] for p in m.group(2).split(",") if p.strip()] if m else []
                decl = re.match(r"^\s*(?:var\s+)?(?:float|int|bool|string|color|label|line|box|table)?\s*([A-Za-z_]\w*)\s*(?::)?=(?!=)", l)
                for n in params + ([decl.group(1)] if decl else []):
                    self.assertNotIn(n, BUILTINS, f"line {i}: '{n}' shadows a Pine built-in")
            depth += l.count("(") + l.count("[") - l.count(")") - l.count("]")

    def test_inputs_stay_out_of_the_status_line(self):
        # TradingView prints every input's value next to the indicator's name unless it opts out;
        # a fresh chart should show just "GEX PRO", not a row of line-style glyphs
        calls = re.findall(r"(?<![\w.])input\.\w+\(", PINE)
        self.assertEqual(len(calls), PINE.count("display = display.none"), "an input is missing display = display.none")

    def test_text_sizes_are_builtin_constants(self):
        # a number as a label / table text size broke the TradingView compile once; only size.* is known to work
        self.assertNotRegex(CODE, r"(?<![\w.])(?:size|text_size)\s*=\s*\d")
        self.assertNotRegex(CODE, r"(?:lSz|tSz)\s*=.*\?\s*\d")

    def test_only_reviewed_builtins_and_arguments(self):
        # every built-in call and named argument here has been checked against the Pine v6 reference; a new one
        # (or a typo, or a v5 leftover like transp / when) must be checked there too before it joins the list
        inp = {"display", "group", "inline", "tooltip"}
        known = {
            "array.clear": set(), "array.from": set(), "array.get": set(), "array.min": set(), "array.push": set(),
            "array.set": set(), "array.size": set(), "box.delete": set(), "label.delete": set(), "line.delete": set(),
            "box.new": {"bgcolor", "border_color", "border_width", "extend", "xloc"},
            "color.new": set(), "label.set_text": set(), "line.set_color": set(),
            "input.bool": inp, "input.color": inp, "input.float": inp | {"maxval", "minval", "step"},
            "input.int": inp | {"maxval", "minval", "step"}, "input.string": inp | {"options"}, "input.text_area": {"display", "group", "tooltip"},
            "label.new": {"color", "size", "style", "text_font_family", "textalign", "textcolor", "tooltip", "xloc"},
            "line.new": {"color", "extend", "style", "width", "xloc"},
            "map.contains": set(), "map.get": set(), "map.put": set(),
            "math.abs": set(), "math.floor": set(), "math.max": set(), "math.min": set(), "math.round": set(), "math.round_to_mintick": set(),
            "request.security": {"gaps", "ignore_invalid_symbol", "lookahead"},
            "str.contains": set(), "str.length": set(), "str.pos": set(), "str.repeat": set(), "str.split": set(), "str.startswith": set(),
            "str.substring": set(), "str.tonumber": set(), "str.tostring": set(), "str.trim": set(), "str.upper": set(),
            "ta.cross": set(), "timeframe.change": set(),
            "table.cell": {"bgcolor", "text_color", "text_halign", "text_size"}, "table.clear": set(),
            "table.new": {"bgcolor", "border_width", "frame_color", "frame_width"},
        }
        for m in re.finditer(r"(?<![\w.])((?:array|box|color|input|label|line|map|math|request|str|ta|table|timeframe)\.\w+)\(", NO_STRINGS):
            name = m.group(1)
            self.assertIn(name, known, f"{name}() is not on the reviewed list: check it in the Pine v6 reference, then add it")
            depth, j = 1, m.end()
            while depth:
                depth += NO_STRINGS[j] in "([" and 1 or 0
                depth -= NO_STRINGS[j] in ")]" and 1 or 0
                j += 1
            d, top = 0, ""
            for ch in NO_STRINGS[m.end():j - 1]:
                d += ch in "([" and 1 or 0
                d -= ch in ")]" and 1 or 0
                top += ch if d == 0 else " "
            for arg in re.findall(r"(?:^|,)\s*(\w+)\s*=(?!=)", top):
                self.assertIn(arg, known[name], f"{name}(): '{arg} =' is not an argument it takes")

    def test_continuation_lines_are_not_block_indented(self):
        # Pine reads a line indented by a multiple of 4 as a new statement in a block; a wrapped line must use
        # another indent (5 here), and a block line a multiple of 4
        depth, cont = 0, False
        for i, l in enumerate(NO_STRINGS.splitlines(), 1):
            if l.strip():
                ind = len(l) - len(l.lstrip(" "))
                wrapped = depth > 0 or cont or l.lstrip()[:1] in "+:?"
                if wrapped:
                    self.assertNotEqual(ind % 4, 0, f"line {i}: a wrapped line indented by a multiple of 4 spaces")
                else:
                    self.assertEqual(ind % 4, 0, f"line {i}: a statement indented by {ind} spaces")
                s = l.rstrip()
                cont = s.endswith((",", "?", ":", "+", "-", "*", "/", " and", " or", "=")) and not s.endswith("=>")
            depth += l.count("(") + l.count("[") - l.count(")") - l.count("]")

    def test_functions_only_reassign_their_own_locals(self):
        # Pine rejects := on a function's parameter or on a global variable from inside a function
        lines = NO_STRINGS.splitlines()
        i = 0
        while i < len(lines):
            m = re.match(r"^([A-Za-z_]\w*)\(([^)]*)\)\s*=>\s*$", lines[i])
            if not m:
                i += 1
                continue
            params = {p.split("=")[0].split()[-1] for p in m.group(2).split(",") if p.strip()}
            local, j = set(), i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].startswith(" ")):
                l = lines[j]
                for d in re.findall(r"^\s+(?:var\s+)?(?:float|int|bool|string|color|label|line|box|table|array<\w+>|\w+)?\s*([A-Za-z_]\w*)\s*=(?!=)", l):
                    local.add(d)
                local |= set(re.findall(r"^\s+for\s+\[?\s*(\w+)", l)) | set(re.findall(r"^\s+for\s+\[\s*\w+\s*,\s*(\w+)", l))
                local |= {v.strip() for t in re.findall(r"^\s+\[([^\]]+)\]\s*=", l) for v in t.split(",")}
                for tgt in re.findall(r"(?<![\w.])([A-Za-z_]\w*)\s*:=", l):
                    self.assertNotIn(tgt, params, f"line {j + 1}: {m.group(1)}() assigns its parameter '{tgt}'")
                    self.assertIn(tgt, local, f"line {j + 1}: {m.group(1)}() assigns '{tgt}', which is not its own local variable")
                j += 1
            i = j

    def test_every_input_is_used(self):
        for name in re.findall(r"^([A-Za-z_]\w*)\s*=\s*input\.", NO_STRINGS, re.M):
            uses = len(re.findall(rf"(?<![\w.]){name}(?!\w)", NO_STRINGS))
            self.assertGreater(uses, 1, f"input '{name}' is declared but never used")

    def test_info_panel_table_is_big_enough(self):
        rows = int(re.search(r"table\.new\(tPos, 3, (\d+)", PINE).group(1))
        cleared = int(re.search(r"table\.clear\(tab, 0, 0, 2, (\d+)\)", PINE).group(1))
        longest = max(len(re.findall(r'"(\w+)"', a)) for a in re.findall(r"array\.from\(([^)]*)\)", PINE.split("rowKeys =")[1].split("rowName(")[0]))
        self.assertGreaterEqual(rows, longest + 1, "info panel needs a header row plus one row per item")
        self.assertEqual(cleared, rows - 1, "table.clear must cover every row")
        # every row key the panel shows has a name and a value case
        keys = {k for a in re.findall(r"array\.from\(([^)]*)\)", PINE.split("rowKeys =")[1].split("rowName(")[0])
                for k in re.findall(r'"(\w+)"', a)}
        names = set(re.findall(r'^\s+"(\w+)"\s+=>', PINE.split("rowName(")[1].split("valOf(")[0], re.M))
        self.assertFalse(keys - names, f"panel rows without a name: {keys - names}")

    def test_payload_keys_match_the_service(self):
        read = set(re.findall(r'(?:strOf|numOf)\(m, "(\w+)"\)', PINE))
        summary = {"asof": "2026-10-20T15:00:00+00:00", "etf": "QQQ", "ref_price": 1.0, "ref_quality": "DL", "positioning": "conventional",
                   "unit": "usd_per_1pct", "net": 1.0, "regime": "POSITIVE", "status": "OK", "zero_gamma_status": "ESTIMATE",
                   "basket": ["2026-10-20"], "concentrations": [{"price": 1.0, "sign": "+", "share": 0.1}],
                   "zero_gamma": {"price": 1.0}, "call_wall": {"price": 1.0}, "put_wall": {"price": 1.0},
                   "max_positive": {"price": 1.0}, "max_negative": {"price": 1.0}, "abs_gamma": {"price": 1.0},
                   "ranked": {"call": [{"price": 1.0, "share": 0.1}], "put": [], "abs": []},
                   "expected_move": {"one_sigma_points": 1.0},
                   "extras": {"nearest": {"label": "0DTE", "expiration": "2026-10-20", "zero_gamma": {"price": 1.0}, "call_wall": {"price": 1.0}, "put_wall": {"price": 1.0},
                                          "ranked": {"call": [{"price": 1.0, "share": 0.1}], "put": [], "abs": []},
                                          "ranked_etf": {"call": [{"price": 1.0, "share": 0.1}], "put": [], "abs": []}, "etf_share": 0.6},
                              "vol_call": {"price": 1.0}, "vol_put": {"price": 1.0}, "oi_call": {"price": 1.0}, "oi_put": {"price": 1.0},
                              "max_pain": [{"expiration": "2026-10-20", "price": 1.0}],
                              "expected_move": {"anchor": 1.0, "daily_points": 1.0, "weekly_points": 1.0, "weekly_expiry": "2026-10-23",
                                                "monthly_points": 1.0, "monthly_expiry": "2026-11-20", "daily_iv": 0.2, "weekly_iv": 0.2, "monthly_iv": 0.2},
                              "greeks": {"vanna_usd_per_vol_pt": 1.0, "charm_usd_per_day": 1.0},
                              "profile": {"base": 1.0, "width": 1.0, "values": [1]}}}
        emitted = {kv.split("=", 1)[0] for kv in pine_payload(summary, "NQ", "NDX", "ratio", provider="CBOE",
                                                               delta={"zero_gamma": 1.0, "prev_regime": "POSITIVE"}).split(";")[1:] if "=" in kv}
        # fields the service adds on every refresh (gexsys/service.py, add_tokens): open levels, reaction stats
        svc = (Path(__file__).resolve().parent.parent / "gexsys" / "service.py").read_text(encoding="utf-8")
        line = next(ln for ln in svc.splitlines() if "add_tokens(r[" in ln)
        emitted |= set(re.findall(r'"(\w+)": [^,}]*_token\(', line))
        missing = read - emitted
        self.assertFalse(missing, f"Pine reads keys the service never sends: {sorted(missing)}")


if __name__ == "__main__":
    unittest.main()
