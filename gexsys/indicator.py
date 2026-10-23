"""The TradingView indicator's source, as shown on the website's Indicator page.

Read from pine/nq_es_gex_levels.pine every time, so the page always shows the file as it is now:
the local service serves it live (/api/indicator) and the hosted build copies it (data/indicator.json),
which happens on every push. The version is a hash of the code, so any edit changes it.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
PINE = ROOT / "pine" / "nq_es_gex_levels.pine"
GIT_FALLBACK = Path(r"C:\Program Files\Git\cmd\git.exe")


def _git() -> Optional[str]:
    g = shutil.which("git")
    return g or (str(GIT_FALLBACK) if GIT_FALLBACK.exists() else None)


def recent_changes(limit: int = 8) -> list[dict]:
    """The last commits that touched the script (empty when git or the history is unavailable)."""
    g = _git()
    if not g or not (ROOT / ".git").exists():
        return []
    try:
        out = subprocess.run([g, "log", f"-n{limit}", "--format=%h%x09%cI%x09%s", "--", str(PINE.relative_to(ROOT))],
                             cwd=ROOT, capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            rows.append({"commit": parts[0], "date": parts[1], "message": parts[2]})
    return rows


def info(path: Path = PINE, with_changes: bool = True) -> dict:
    code = path.read_text(encoding="utf-8")
    changes = recent_changes() if with_changes else []
    updated = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    if changes and os.environ.get("GITHUB_ACTIONS"):
        updated = changes[0]["date"]
    m = re.search(r'indicator\("([^"]+)"', code)
    v = re.search(r"//@version=(\d+)", code)
    return {
        "name": m.group(1) if m else "GEX PRO",
        "pine_version": int(v.group(1)) if v else None,
        "version": hashlib.sha256(code.encode("utf-8")).hexdigest()[:10],
        "updated": updated,
        "lines": code.count("\n") + 1,
        "inputs": len(re.findall(r"\binput\.\w+\(", code)),
        "filename": "GEX_PRO.pine",
        "code": code,
        "changes": changes,
    }
