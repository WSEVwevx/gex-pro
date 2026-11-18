"""Which commit may the website build? The newest one on this branch whose "tests" check passed.

  python .github/scripts/tested_commit.py <owner/repo>      (in the website workflow; needs GH_TOKEN)

Walks the branch's first-parent history from HEAD (newest first) and asks GitHub for each commit's "tests" check run
(.github/workflows/tests.yml). A commit that failed, or is untested or still testing, is skipped and logged, so a
broken commit never goes live and the site keeps refreshing on the last good code meanwhile.

Bootstrap: if none of the recent commits has any "tests" result (the gate itself just arrived), HEAD is used with a
warning. If some were tested but none passed, nothing is built (exit 1): the live site stays as it is.
Prints the chosen SHA on stdout; the reasons go to stderr.
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Callable, Optional

DEPTH = 40
CHECK = "tests"


def choose(shas: list[str], conclusions: Callable[[str], list[Optional[str]]]) -> tuple[Optional[str], list[str]]:
    """(the SHA to build or None, log lines). conclusions(sha) -> the "tests" runs' conclusions (None = not finished)."""
    log, seen_any = [], False
    for i, sha in enumerate(shas):
        got = conclusions(sha)
        seen_any |= bool(got)
        if "success" in got:
            if i:
                log.append(f"building {sha[:7]}, the newest commit whose tests passed ({i} newer skipped)")
            return sha, log
        why = "untested" if not got else "still testing" if None in got else "tests " + "/".join(sorted(set(got)))
        log.append(f"skip {sha[:7]}: {why}")
    if not seen_any and shas:
        log.append(f"no commit in the last {len(shas)} has a tests result yet (gate just added): building HEAD {shas[0][:7]}")
        return shas[0], log
    log.append("no commit with passing tests: nothing built, the live site stays as it is")
    return None, log


def _gh_conclusions(repo: str) -> Callable[[str], list[Optional[str]]]:
    def get(sha: str) -> list[Optional[str]]:
        out = subprocess.run(["gh", "api", f"repos/{repo}/commits/{sha}/check-runs?check_name={CHECK}&per_page=20"],
                             capture_output=True, text=True, check=True).stdout
        return [r.get("conclusion") for r in json.loads(out).get("check_runs", [])]
    return get


def main() -> int:
    shas = subprocess.run(["git", "rev-list", "--first-parent", f"-n{DEPTH}", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.split()
    sha, log = choose(shas, _gh_conclusions(sys.argv[1]))
    for line in log:
        print(line, file=sys.stderr)
    if sha is None:
        return 1
    print(sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
