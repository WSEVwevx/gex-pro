"""GEX PRO command line.

  python -m gexpro serve --auto                       local website + background work (START.bat)
  python -m gexpro serve --config a.json --config b.json [--port 8765]
  python -m gexpro build-site [--out _site] [--state .state]   hosted copy (GitHub workflow)

GEX-only tools (demo, snapshot, audit, replay, sensitivity) stay in `python -m gexsys`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from gexsys import config as cfgmod
from gexsys.__main__ import auto_configs

from .components import default_components

FREE_CONFIGS = ["configs/free_nq_cboe.json", "configs/free_es_cboe.json"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gexpro")
    ap.add_argument("--log-level", default="INFO")
    ap.add_argument("--env-file", default=".env")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve", help="run the local website and its background work")
    sv.add_argument("--config", action="append", help="GEX market configs (default with --auto: the free Cboe ones)")
    sv.add_argument("--auto", action="store_true", help="the free Cboe configs for NQ and ES")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    bs = sub.add_parser("build-site", help="write the website + fresh data as static files (for free hosting)")
    bs.add_argument("--config", action="append", help="default: the free Cboe configs")
    bs.add_argument("--out", default="_site")
    bs.add_argument("--state", default=".state", help="folder kept between runs (last good results, history, caches)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=getattr(logging, a.log_level.upper(), logging.INFO),
                        format='{"t":"%(asctime)s","lvl":"%(levelname)s","log":"%(name)s","msg":"%(message)s"}')
    cfgmod.load_dotenv(a.env_file)

    if a.cmd == "serve":
        from .server import serve
        paths = auto_configs() if a.auto else (a.config or [])
        if not paths:
            print("serve needs --config (one or more) or --auto", file=sys.stderr)
            return 2
        serve(default_components([cfgmod.load(p) for p in paths]), a.host, a.port)
        return 0
    if a.cmd == "build-site":
        from .site import build
        res = build(default_components([cfgmod.load(p) for p in a.config or FREE_CONFIGS]), a.out, a.state)
        print(json.dumps(res))
        return 0 if any(calc and calc != "UNAVAILABLE" for _, calc in res.values()) else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
