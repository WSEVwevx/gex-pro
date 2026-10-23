"""Command-line interface.

  python -m gexsys demo [--market NQ|ES]          synthetic end-to-end run (no credentials)
  python -m gexsys snapshot --config configs/free_nq_cboe.json [--futures-price 20345.25]
  python -m gexsys serve --config configs/nq.json --config configs/es.json [--port 8765]
  python -m gexsys build-site [--out _site] [--state .state]   static website for free hosting
  python -m gexsys replay --market NQ [--root data/snapshots]
  python -m gexsys sensitivity --config configs/free_es_cboe.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from . import config as cfgmod
from .models import to_jsonable


def _setup_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format='{"t":"%(asctime)s","lvl":"%(levelname)s","log":"%(name)s","msg":"%(message)s"}')


def _print_result(r: dict) -> None:
    s = r["mapped"] or r["summary"]
    print(json.dumps(to_jsonable({k: s.get(k) for k in (
        "market", "options_source", "source", "status", "regime", "net", "unit", "positioning",
        "zero_gamma", "zero_gamma_status", "call_wall", "put_wall", "max_positive", "max_negative",
        "concentrations", "clusters", "expected_move", "mapping", "mapping_note", "warnings")}), indent=2))
    print("\nPine payload (paste into the indicator's 'Levels payload' input):\n")
    print(r["pine"])


def auto_configs() -> list[str]:
    """The free Cboe configs: ES from SPX + SPY options, NQ from NDX + QQQ options."""
    print("Data: Cboe free feed (SPX+SPY options for ES, NDX+QQQ for NQ; 15-min delayed).")
    return ["configs/free_nq_cboe.json", "configs/free_es_cboe.json"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gexsys")
    ap.add_argument("--log-level", default="INFO")
    ap.add_argument("--env-file", default=".env")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--market", default="NQ", choices=["NQ", "ES", "MNQ", "MES"])
    sn = sub.add_parser("snapshot")
    sn.add_argument("--config", required=True)
    sn.add_argument("--futures-price", type=float)
    sv = sub.add_parser("serve")
    sv.add_argument("--config", action="append")
    sv.add_argument("--auto", action="store_true",
                    help="the free Cboe configs for NQ and ES")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    bs = sub.add_parser("build-site", help="write the dashboard + fresh data as static files (for free hosting)")
    bs.add_argument("--config", action="append", help="default: the free Cboe configs")
    bs.add_argument("--out", default="_site")
    bs.add_argument("--state", default=".state", help="folder kept between runs (last good result, history, caches)")
    au = sub.add_parser("audit", help="check live data, levels and the TradingView paste end to end")
    au.add_argument("--config", action="append", help="default: the configs START.bat would use")
    rp = sub.add_parser("replay")
    rp.add_argument("--market", required=True)
    rp.add_argument("--root", default="data/snapshots")
    se = sub.add_parser("sensitivity")
    se.add_argument("--config", required=True)
    a = ap.parse_args(argv)
    _setup_logging(a.log_level)
    cfgmod.load_dotenv(a.env_file)

    from .pipeline import run_once
    from .storage import SnapshotStore

    if a.cmd == "demo":
        src = "NDX" if a.market in ("NQ", "MNQ") else "SPX"
        c = cfgmod.from_dict({"market": a.market, "source": src, "provider": {"name": "synthetic", "live_clock": False},
                              "futures_ref": {"mode": "synthetic_basis", "factor": 1.0105},
                              "description": "SYNTHETIC demo - not market data"})
        _print_result(run_once(c, cfgmod.make_provider(c)))
        return 0
    if a.cmd == "snapshot":
        c = cfgmod.load(a.config)
        fr = (a.futures_price, datetime.now(timezone.utc)) if a.futures_price else None
        if fr:
            print("note: --futures-price is stamped with the current time; the mapping will refuse it if the "
                  "options reference price is older than mapping.max_skew_s", file=sys.stderr)
        st = SnapshotStore(c.storage.get("root", "data/snapshots"), c.storage.get("store_raw", False))
        _print_result(run_once(c, cfgmod.make_provider(c), st, futures_ref=fr))
        return 0
    if a.cmd == "serve":
        from .service import serve
        paths = a.config or []
        if a.auto:
            paths = auto_configs()
        if not paths:
            print("serve needs --config (one or more) or --auto", file=sys.stderr)
            return 2
        serve([cfgmod.load(p) for p in paths], a.host, a.port)
        return 0
    if a.cmd == "build-site":
        from .site import build
        res = build([cfgmod.load(p) for p in a.config or ["configs/free_nq_cboe.json", "configs/free_es_cboe.json"]],
                    a.out, a.state)
        print(json.dumps(res))
        return 0 if any(calc and calc != "UNAVAILABLE" for _, calc in res.values()) else 1
    if a.cmd == "audit":
        from .audit import audit, print_report
        fails = 0
        for p in a.config or auto_configs():
            c = cfgmod.load(p)
            fails += print_report(f"{c.market} from {c.source} ({p})", audit(c, cfgmod.make_provider(c)))
        return 1 if fails else 0
    if a.cmd == "replay":
        from .replay import stability
        print(json.dumps(stability(SnapshotStore(a.root).iter_summaries(a.market)), indent=2))
        return 0
    if a.cmd == "sensitivity":
        from .normalize import normalize
        from .replay import sensitivity
        c = cfgmod.load(a.config)
        snap = normalize(cfgmod.make_provider(c).fetch_snapshot(c.source, c.engine.max_dte, c.engine.include_0dte))
        print(json.dumps(to_jsonable(sensitivity(snap, c.engine)), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
