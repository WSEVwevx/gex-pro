"""UserPromptSubmit hook: on every 10th prompt, remind Claude to run the full GEX PRO check.

The count lives outside the repo (%LOCALAPPDATA%/gexsys/prompt-count.txt) and carries across sessions.
"""
import os
import sys
from pathlib import Path

EVERY = 10
f = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "gexsys" / "prompt-count.txt"
try:
    n = int(f.read_text().strip() or 0) + 1
except (OSError, ValueError):
    n = 1
try:
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(str(n))
except OSError:
    sys.exit(0)
if n % EVERY == 0:
    print(f"Standing rule (prompt {n}): after handling this request, run /check (the full GEX PRO check: "
          "python tools/check.py, the hosted-site sweep and the GitHub source probe). Fix what fails and report the results.")
