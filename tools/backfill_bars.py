"""Futures 1-minute bars for sessions before the archive began (gexpro/archive.py FIRST_DAY), for the rule tester.

The archive keeps bars from 2026-11-18 on. The graded track record starts 2026-10-21, and Yahoo still served those
days' 1-minute NQ=F / ES=F bars (it keeps about 30 days) when they were downloaded on 2026-11-19. This writes each
saved raw Yahoo response, unchanged in content, in the archive's own file format (archive.bar_record: the Globex day,
contracts, roll-week flag) to studies/backfill/bars/<day>/, marked "backfilled" with when it was downloaded and the
SHA-256 of the raw response. These bars were NOT captured on the day; only the outcome side of a session uses them
(the levels still come from the plan frozen at that session's 09:30), so they add no look-ahead.

Files are written once: an existing file is never replaced, and days the archive covers are refused. Each file's
SHA-256 is listed in studies/backfill/manifest.json; tests/test_backfill_bars.py fails if a file no longer matches.

  python tools/backfill_bars.py <folder of raw responses named YYYY-MM-DD_NQF-1m.json>
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gexpro import archive as A  # noqa: E402

OUT = ROOT / "studies" / "backfill" / "bars"
MANIFEST = OUT.parent / "manifest.json"
SYMS = {A.file_name(v["futures"]): (m, v["futures"]) for m, v in A.MARKETS.items()}


def record(name: str, raw: bytes, downloaded_at: datetime) -> tuple[str, dict]:
    """('YYYY-MM-DD/NQF-1m.json', the archive-format record) for one saved raw response."""
    day, fname = name.split("_", 1)
    d = date.fromisoformat(day)
    if d >= A.FIRST_DAY:
        raise ValueError(f"{name}: the archive covers {d} itself")
    m, sym = SYMS[fname]
    lo, hi = A.futures_window(d)
    bars = [b for b in A.parse_bars(raw) if lo.timestamp() <= b[0] < hi.timestamp()]
    if not bars:
        raise ValueError(f"{name}: no bars in the Globex day")
    rec = A.bar_record(m, sym, d, lo, hi, bars)
    rec["backfilled"] = {"downloaded_at": downloaded_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
                         "raw_sha256": hashlib.sha256(raw).hexdigest(),
                         "note": "downloaded after the day from Yahoo's 30-day 1-minute history, not captured on the day"}
    return f"{day}/{fname}", rec


def main(argv=None) -> int:
    src = Path((argv or sys.argv[1:])[0])
    man = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    wrote = 0
    for p in sorted(src.glob("*_*-1m.json")):
        rel, rec = record(p.name, p.read_bytes(), datetime.fromtimestamp(p.stat().st_mtime, timezone.utc))
        out = OUT / rel
        if out.exists():
            print(f"kept {rel} (written before; never replaced)")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        b = A._json(rec)
        out.write_bytes(b)
        man[rel] = {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b), "raw_sha256": rec["backfilled"]["raw_sha256"]}
        wrote += 1
        print(f"wrote {rel}: {len(rec['bars'])} bars, roll week {rec['roll_week']}, contracts {[c['contract'] for c in rec['contracts']]}")
    if wrote:
        MANIFEST.write_text(json.dumps(dict(sorted(man.items())), indent=1) + "\n")
    print(f"{wrote} files written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
