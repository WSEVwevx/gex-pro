"""Stress test F2: the hosted site and the local app show the same numbers, byte for byte.

  python tools/stress/site_parity.py

One build of the hosted site (the real `build-site` path, into a temporary folder), then the local app's endpoints
are asked, on the same component objects (the same snapshot), for everything the page loads. Each pair is compared:
the page's own map (dashboard/assets/app.js: API, pineUrl, hmUrl, the screener) says which file stands for which
endpoint. JSON is compared value by value with only clock fields allowed to differ (now, fetched, fetched_at, built,
generated, ok_at, age); the TradingView pastes are compared byte for byte.
Tolerance (fixed before running): no difference other than those clock fields.
Outage checks (2026-11-10): the watchdog with GitHub's API returning 503 now exits quietly after one read (it used
to fail every 15-minute run; tests/test_watchdog.py). The hosted page served from a local copy, the server then
stopped: it kept its last numbers and showed "Can't load the latest data file ... retrying"; with the server back
and a new build stamp, the next poll cleared the banner and loaded the new build.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gexpro.components import default_components  # noqa: E402
from gexpro.site import build  # noqa: E402
from gexsys import config as cfgmod  # noqa: E402
from gexsys.heatmap import RANGE  # noqa: E402

CLOCK = {"now", "fetched", "fetched_at", "built", "generated", "ok_at", "age", "age_s", "age_h", "last_try", "checked",
         "next_run_in_s"}
MODE = {"static"}         # the hosted page's own flag (window.GEX_STATIC), the one intended difference


def diff(a, b, path="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k in CLOCK or (path == "" and k in MODE):
                continue
            if k not in a or k not in b:
                out.append(f"{path}.{k}: only in {'hosted' if k in a else 'local'}")
            else:
                out += diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: {len(a)} vs {len(b)} items"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in diff(x, y, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: hosted {str(a)[:60]!r} vs local {str(b)[:60]!r}"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    out, state = Path(tempfile.mkdtemp(prefix="site-")), Path(tempfile.mkdtemp(prefix="state-"))
    # the same snapshot on both sides: the futures candles are downloaded once and reused
    from gexsys import heatmap
    real, seen = heatmap.fetch_candles, {}
    heatmap.fetch_candles = lambda market, tf: seen.setdefault((market, tf), real(market, tf))
    comps = default_components([cfgmod.load(f"configs/free_{m}_cboe.json") for m in ("nq", "es")])
    print("build:", build(comps, out, state))
    routes = {}
    for c in comps:
        routes.update(c.routes())
    data = out / "data"

    def local(path, **q):
        code, body = routes[path]({k: [v] for k, v in q.items()})
        return code, body
    pairs = [("all.json", "/api/all", {}), ("news.json", "/api/news", {}), ("posts.json", "/api/posts", {}),
             ("indicator.json", "/api/indicator", {}), ("briefings.json", "/api/briefings", {}),
             ("trackrecord.json", "/api/trackrecord", {}), ("quotes.json", "/api/quotes", {}),
             ("positioning.json", "/api/positioning", {}), ("sources.json", "/api/sources", {}),
             ("pastes.json", "/api/pastes", {}), ("screener.json", "/api/screener", {})]
    pairs += [(f"heatmap-{m}-{tf}.json", "/api/heatmap", {"market": m, "tf": tf}) for m in ("NQ", "ES") for tf in RANGE]
    pairs += [(f"bias-history-{m}.json", "/api/bias-history", {"market": m}) for m in ("NQ", "ES")]
    texts = [("pine-published.txt", "/api/pine/all", {"which": "published"}), ("pine-latest.txt", "/api/pine/all", {})]
    texts += [(f"pine-{w}-{m}.txt", "/api/pine/all", dict({"market": m}, **({"which": w} if w == "published" else {})))
              for w in ("published", "latest") for m in ("NQ", "ES")]
    bad = []
    for fname, path, q in pairs:
        f = data / fname
        if not f.exists() or path not in routes:
            bad.append(f"{fname}: {'no file' if not f.exists() else 'no endpoint ' + path}")
            continue
        code, body = local(path, **q)
        d = diff(json.loads(f.read_text(encoding="utf-8")), json.loads(json.dumps(body, default=str)))
        print(f"  {fname:28s} vs {path}{'?' + '&'.join(f'{k}={v}' for k, v in q.items()) if q else '':30s} "
              f"{'identical' if not d else f'{len(d)} differences'}")
        bad += [f"{fname}: {x}" for x in d[:5]]
    for fname, path, q in texts:
        code, body = local(path, **q)
        same = (data / fname).read_bytes() == body.encode()
        print(f"  {fname:28s} vs {path}{'?' + '&'.join(f'{k}={v}' for k, v in q.items()) if q else '':30s} "
              f"{'byte-identical' if same else 'DIFFERENT'} ({len(body)} bytes)")
        if not same:
            bad.append(f"{fname}: paste differs from the local endpoint")
    print("RESULT:", "PASS" if not bad else f"FAIL - {len(bad)}:\n  " + "\n  ".join(bad[:30]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
