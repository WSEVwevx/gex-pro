"""The hosted website: the same dashboard as the local one, as plain files any free host can serve.

  python -m gexpro build-site --out _site --state .state

Every component writes its own data files into _site/data (what its local endpoints return); this
module adds the page itself, switched to static mode. `--state` is kept between runs by the GitHub
workflow (last good results, the scheduled paste, history, feed caches).
"""
from __future__ import annotations

from pathlib import Path

from .server import DASHBOARD

STATIC_FLAG = "<script>window.GEX_STATIC = true;</script>"


def build(components, out: str | Path, state: str | Path) -> dict:
    out, state = Path(out), Path(state)
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    status: dict = {}
    for c in components:
        status.update(c.build_static(data, state) or {})
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    (out / "index.html").write_text(html.replace("<script>", STATIC_FLAG + "\n<script>", 1), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return status
