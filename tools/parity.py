"""Parity replay (decision 001, phase B): run the engine on saved inputs at frozen clocks, with every network call
blocked, and compare two runs byte for byte.

    python tools/parity.py run --inputs DIR --out DIR [--code DIR]
    python tools/parity.py compare A B [--exclude KEY ...]
    python tools/parity.py fixture --occ DIR --out DIR

`run` imports gexsys from --code (default: this checkout), so the same inputs can be run through origin/main's code
(a `git worktree`) and the changed code. Each clock writes `<clock>-<market>.json`: the full `run_once` result, every
key, canonical JSON (sorted keys, repr floats). `compare` reads two such folders and reports the first difference,
with keys named by --exclude dropped at every depth first. Exit 0 = identical.

Inputs (one folder, as `fixture` writes it): OCC series files `occ_<SYM>.txt`, Cboe VIX-family CSVs `vol_<NAME>.csv`,
and `prices.json` with Yahoo's three fields per symbol plus the futures reference per market. Yahoo prices were never
saved, so `fixture` freezes them from the archive branch's 1-minute bars (last bar of the session); QQQ and SPY have
no saved bars, so the ETF merge is not covered (the provider's own "options not used" path runs instead).

Clocks (rework method 7.3): the backup's states, each one's marketcal state checked before it runs.
Not covered: Cboe chains (the live RTH path, refused since 19 Nov; the 13 Nov chains are 507 MB and outside the
repo). The 27 Nov 12:00 RTH clock runs the 20 Nov inputs, so it exercises the stale-price path, not a live session.
Network guard: socket.create_connection and urllib.request.urlopen raise; any attempt fails the run (exit 3).
"""
from __future__ import annotations

import argparse
import io
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# (tag, ET wall time, expected marketcal.session_state)
CLOCKS = (
    ("fri-2026-11-20-1900", "2026-11-20T19:00", "CLOSED"),
    ("sat-2026-11-21-1200", "2026-11-21T12:00", "CLOSED"),          # weekend
    ("sun-2026-11-22-1800", "2026-11-22T18:00", "ETH"),             # the Globex reopen
    ("thu-2026-11-26-1200", "2026-11-26T12:00", "ETH"),             # Thanksgiving: cash closed, Globex open
    ("fri-2026-11-27-1200", "2026-11-27T12:00", "RTH"),             # early close (13:00)
)
MARKETS = (("NQ", "configs/free_nq_cboe.json", "NQ=F"), ("ES", "configs/free_es_cboe.json", "ES=F"))
EXCLUDE_DEFAULT = ("built",)


class NetworkBlocked(RuntimeError):
    pass


ATTEMPTS: list[str] = []


def guard() -> None:
    """Every outside request fails, and is counted: a request that reaches the guard is a test failure."""
    def no_conn(address, *a, **k):
        ATTEMPTS.append(f"socket {address}")
        raise NetworkBlocked(f"parity: network blocked ({address})")

    def no_urlopen(req, *a, **k):
        ATTEMPTS.append(f"urlopen {getattr(req, 'full_url', req)}")
        raise NetworkBlocked("parity: network blocked")
    socket.create_connection = no_conn
    urllib.request.urlopen = no_urlopen


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def stub_opener(inputs: Path, prices: dict):
    """OccProvider's opener: answers the three URL shapes from the saved files; anything else is blocked."""
    def opener(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        q = urllib.parse.urlparse(url)
        if q.netloc == "marketdata.theocc.com":
            f = inputs / f"occ_{urllib.parse.parse_qs(q.query)['symbol'][0]}.txt"
        elif q.netloc == "cdn.cboe.com":
            f = inputs / f"vol_{q.path.rsplit('/', 1)[-1].replace('_History.csv', '')}.csv"
        elif q.netloc == "query1.finance.yahoo.com":
            sym = urllib.parse.unquote(q.path.rsplit("/", 1)[-1])
            if sym not in prices["yahoo"]:
                raise urllib.error.URLError(f"parity: no saved price for {sym} (not covered)")
            m = prices["yahoo"][sym]
            return _Resp(json.dumps({"chart": {"result": [{"meta": m}]}}).encode())
        else:
            ATTEMPTS.append(f"opener {url}")
            raise NetworkBlocked(f"parity: no saved input for {url}")
        if not f.exists():
            raise urllib.error.URLError(f"parity: {f.name} not in the inputs (not covered)")
        return _Resp(f.read_bytes())
    return opener


def freeze(at: datetime) -> None:
    """datetime.now() and time.time() read `at` in every project module (imports first, as perf_profile does)."""
    import importlib
    real = datetime

    class FrozenDT(real):
        @classmethod
        def now(cls, tz=None):
            return at.astimezone(tz) if tz else at.astimezone(timezone.utc).replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return at.astimezone(timezone.utc).replace(tzinfo=None)

    for m in ("gexsys.pipeline", "gexsys.providers.occ", "gexsys.normalize", "gexsys.basis", "gexsys.extras",
              "gexsys.engine", "gexsys.session", "gexsys.heatmap", "gexsys.ladder", "gexsys.bias", "gexsys.alerts",
              "gexsys.export", "gexsys.mapping", "gexsys.marketcal"):
        importlib.import_module(m)
    for name, mod in list(sys.modules.items()):
        d = getattr(mod, "datetime", None)
        if name.split(".")[0] in ("gexsys", "gexpro", "trackrecord", "feeds", "briefings") and isinstance(d, type)                 and issubclass(d, real):
            mod.datetime = FrozenDT
    ts = at.timestamp()
    time.time = lambda: ts


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=1, default=str, allow_nan=True) + "\n"


def run(inputs: Path, out: Path, code: Path | None = None) -> int:
    if code:
        sys.path.insert(0, str(code.resolve()))
    else:
        sys.path.insert(0, str(ROOT))
    from gexsys import config as cfgmod, marketcal
    from gexsys.pipeline import run_once
    from gexsys.providers.occ import OccProvider
    guard()
    prices = json.loads((inputs / "prices.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    root = code.resolve() if code else ROOT
    for tag, wall, want in CLOCKS:
        at = datetime.fromisoformat(wall).replace(tzinfo=marketcal.NY)
        got = marketcal.session_state(at)
        if got != want:
            print(f"{tag}: marketcal says {got}, the recipe says {want}")
            return 2
        freeze(at)
        for market, cfg_path, fut in MARKETS:
            cfg = cfgmod.load(root / cfg_path)
            prov = OccProvider(cache_dir=None, opener=stub_opener(inputs, prices), clock=lambda ts=at.timestamp(): ts)
            f = prices["futures"][fut]
            fr = (f["price"], datetime.fromisoformat(f["time"]))
            try:
                res = run_once(cfg, prov, store=None, alerts=None, futures_ref=fr)
            except Exception as e:                      # a refusal is an output too: both sides must refuse alike
                res = {"error": f"{type(e).__name__}: {e}"}
            (out / f"{tag}-{market}.json").write_text(canonical({"clock": wall, "state": got, "result": res}),
                                                      encoding="utf-8", newline="\n")
            print(f"{tag} {market} {got}: {'error' if 'error' in res else 'ok'}")
    if ATTEMPTS:
        print("network attempts reached the guard:", *ATTEMPTS[:5], sep="\n  ")
        return 3
    return 0


def drop(obj, names: set):
    if isinstance(obj, dict):
        return {k: drop(v, names) for k, v in obj.items() if k not in names}
    if isinstance(obj, list):
        return [drop(v, names) for v in obj]
    return obj


def first_diff(a, b, path="$"):
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: only in {'B' if k not in a else 'A'}"
            d = first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} vs {len(b)} items"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b and repr(a) == repr(b) else f"{path}: {a!r} vs {b!r}"


def compare(a: Path, b: Path, exclude=EXCLUDE_DEFAULT) -> list[str]:
    names, problems = set(exclude), []
    fa, fb = {p.name for p in a.glob("*.json")}, {p.name for p in b.glob("*.json")}
    for n in sorted(fa ^ fb):
        problems.append(f"{n}: only in {'A' if n in fa else 'B'}")
    for n in sorted(fa & fb):
        x = drop(json.loads((a / n).read_text(encoding="utf-8")), names)
        y = drop(json.loads((b / n).read_text(encoding="utf-8")), names)
        if canonical(x) != canonical(y):
            problems.append(f"{n}: {first_diff(x, y) or 'same values, different bytes'}")
    return problems


def _bars(day: str, sym: str) -> list:
    raw = subprocess.run(["git", "show", f"origin/archive:days/{day}/{sym}-1m.json"], cwd=ROOT, capture_output=True,
                         check=True).stdout
    return json.loads(raw)["bars"]


def fixture(occ: Path, out: Path, day: str = "2026-11-20", prev: str = "2026-11-19") -> None:
    """Trimmed inputs for tests/: OCC rows within 46 days and +-10% of the close, the last 40 vol rows, frozen prices."""
    out.mkdir(parents=True, exist_ok=True)
    close = {s: _bars(day, s)[-1] for s in ("NDX", "GSPC")}
    # the futures at the same minute as the index's last bar: a later bar would read as a clock skew to the mapping
    close.update({f: next(b for b in reversed(_bars(day, f)) if b[0] <= close[i][0]) for f, i in (("NQF", "NDX"), ("ESF", "GSPC"))})
    before = {s: _bars(prev, s)[-1][4] for s in ("NDX", "GSPC")}
    end = date.fromisoformat(day) + timedelta(days=46)             # the configs' max_dte is 45
    spot = {"NDX": close["NDX"][4], "SPX": close["GSPC"][4]}
    for f in sorted(occ.glob("occ_*.txt")):
        if f.stem[4:] not in spot:                     # QQQ, SPY: no saved price, so their merge is not covered
            continue
        sym, keep = f.stem[4:], []
        for line in f.read_text(encoding="utf-8").splitlines():
            c = [x.strip() for x in line.split("\t")]
            if len(c) >= 10 and all(c[i].isdigit() for i in (2, 3, 4, 5, 6)):
                if date(int(c[2]), int(c[3]), int(c[4])) > end or abs(int(c[5]) / spot[sym] - 1) > 0.10:
                    continue
            keep.append(line)
        (out / f.name).write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")
    for f in sorted(occ.glob("vol_*.csv")):
        lines = f.read_text(encoding="utf-8").splitlines()
        (out / f.name).write_text("\n".join(lines[:1] + lines[-40:]) + "\n", encoding="utf-8", newline="\n")

    def meta(bar, prev_close):
        return {"regularMarketPrice": bar[4], "chartPreviousClose": prev_close, "regularMarketTime": bar[0] + 60}
    prices = {
        "note": f"frozen from the archive's 1-minute bars (last bar of {day}, previous close = last bar of {prev}); "
                "QQQ and SPY were not saved: their ETF merge is not covered",
        "yahoo": {"^NDX": meta(close["NDX"], before["NDX"]), "^GSPC": meta(close["GSPC"], before["GSPC"])},
        "futures": {"NQ=F": {"price": close["NQF"][4], "time": datetime.fromtimestamp(close["NQF"][0] + 60, timezone.utc).isoformat()},
                    "ES=F": {"price": close["ESF"][4], "time": datetime.fromtimestamp(close["ESF"][0] + 60, timezone.utc).isoformat()}},
    }
    (out / "prices.json").write_text(canonical(prices), encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--inputs", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--code", type=Path)
    c = sub.add_parser("compare")
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    c.add_argument("--exclude", nargs="*", default=list(EXCLUDE_DEFAULT))
    f = sub.add_parser("fixture")
    f.add_argument("--occ", type=Path, required=True)
    f.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return run(a.inputs, a.out, a.code)
    if a.cmd == "compare":
        p = compare(a.a, a.b, a.exclude)
        print("\n".join(p) if p else "identical")
        return 1 if p else 0
    fixture(a.occ, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
