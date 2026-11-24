"""Merge a PR, wait for main's tests on the merge commit, deploy it in a fresh lane, and confirm what was built.

    python tools/merge_deploy.py <pr number> [--fix] [--dry-run]

Decision 001, C4. Merge to live had a median of 5.2 min but up to 48.8 min (PRs 60-80, n=20) when the deploy was
left to the push-triggered run, which often builds the previous commit because main's tests are still running.
Steps (CLAUDE.md, Workflow):
  1. refuse during the quiet window (08:30 ET to 15 min after the close on trading days) unless --fix;
  2. gh pr merge <n> --merge, only when the PR's `tests` check passed;
  3. wait for the `Tests` run on main's merge commit to succeed;
  4. lane = the highest "lane N" among Website runs + 1; gh workflow run website.yml -f lane=<lane>;
  5. wait for that run's build job and read its "building <sha>" line; the built commit must be the merge commit or
     a later main commit (git merge-base --is-ancestor).
Places no orders and touches no data: it only drives gh and git.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gexsys import marketcal  # noqa: E402

REPO = "WSEVwevx/gex-pro"
QUIET_START = (8, 30)              # ET, trading days only (rework method, section 2)
QUIET_AFTER_CLOSE = timedelta(minutes=15)


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")


def in_quiet_window(now: datetime) -> bool:
    """True from 08:30 ET until 15 min after the cash close (13:00 on early closes) on a trading day."""
    et = now.astimezone(marketcal.NY)
    d = et.date()
    if not marketcal.is_trading_day(d):
        return False
    start = datetime.combine(d, datetime.min.time(), marketcal.NY).replace(hour=QUIET_START[0], minute=QUIET_START[1])
    return start <= et < marketcal.rth_close_dt(d) + QUIET_AFTER_CLOSE


def next_lane(run_titles: list[str]) -> int:
    lanes = [int(m.group(1)) for t in run_titles for m in [re.search(r"\blane (\d+)\b", t or "")] if m]
    return max(lanes, default=2) + 1


def built_sha(log: str) -> str | None:
    m = re.search(r"\bbuilding ([0-9a-f]{7,40})\b", log)
    return m.group(1) if m else None


def wait(what: str, check, timeout_s: int, every_s: int = 15):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        got = check()
        if got is not None:
            return got
        time.sleep(every_s)
    raise SystemExit(f"timed out after {timeout_s // 60} min waiting for {what}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pr", type=int)
    ap.add_argument("--fix", action="store_true", help="a live-data fix: allowed inside the quiet window")
    ap.add_argument("--dry-run", action="store_true", help="check and print the steps without merging or deploying")
    a = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    if in_quiet_window(now) and not a.fix:
        print(f"quiet window ({now.astimezone(marketcal.NY):%H:%M} ET): no merge or deploy until 15 min after the "
              "close; pass --fix for a live-data fix")
        return 2

    pr = json.loads(gh("pr", "view", str(a.pr), "-R", REPO, "--json", "state,statusCheckRollup,mergeCommit"))
    if pr["state"] != "MERGED":
        tests = [c for c in pr.get("statusCheckRollup") or [] if c.get("name") == "tests"]
        if not tests or tests[-1].get("conclusion") != "SUCCESS":
            print(f"PR {a.pr}: the tests check has not passed ({tests[-1].get('conclusion') if tests else 'not run'})")
            return 1
        if a.dry_run:
            print(f"would merge PR {a.pr}")
        else:
            gh("pr", "merge", str(a.pr), "--merge", "-R", REPO)
            pr = json.loads(gh("pr", "view", str(a.pr), "-R", REPO, "--json", "mergeCommit"))
    merge = (pr.get("mergeCommit") or {}).get("oid")
    if not merge:
        print("dry run: stops before waiting for the merge commit" if a.dry_run else "no merge commit found")
        return 0 if a.dry_run else 1
    print(f"merge commit {merge[:7]}")

    def tests_done():
        runs = json.loads(gh("run", "list", "-R", REPO, "--workflow", "tests.yml", "--commit", merge,
                             "--json", "status,conclusion,event"))
        runs = [r for r in runs if r["event"] == "push"]
        if not runs or runs[0]["status"] != "completed":
            return None
        return runs[0]["conclusion"]
    result = wait("main's tests on the merge commit", tests_done, 20 * 60)
    if result != "success":
        print(f"main's tests on {merge[:7]}: {result}; not deploying")
        return 1
    print("main's tests passed")

    titles = [r["displayTitle"] for r in json.loads(gh("run", "list", "-R", REPO, "--workflow", "website.yml",
                                                        "-L", "300", "--json", "displayTitle"))]
    lane = next_lane(titles)
    if a.dry_run:
        print(f"would deploy in lane {lane}")
        return 0
    started = datetime.now(timezone.utc) - timedelta(seconds=90)    # room for this PC's clock running ahead of GitHub's
    gh("workflow", "run", "website.yml", "--ref", "main", "-R", REPO, "-f", f"lane={lane}")
    print(f"deploy started in lane {lane}")

    def our_run():
        runs = json.loads(gh("run", "list", "-R", REPO, "--workflow", "website.yml", "-L", "20",
                             "--json", "databaseId,displayTitle,createdAt"))
        for r in runs:
            if r["displayTitle"].endswith(f"(lane {lane})") and \
                    datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")) >= started:
                return r["databaseId"]
        return None
    run_id = wait("the deploy run to appear", our_run, 3 * 60, 5)

    def build_job():
        jobs = json.loads(gh("run", "view", str(run_id), "-R", REPO, "--json", "jobs"))["jobs"]
        b = next((j for j in jobs if j["name"] == "build"), None)
        d = next((j for j in jobs if j["name"] == "deploy"), None)
        if not b or b["status"] != "completed" or not d or d["status"] != "completed":
            return None
        return b, d
    b, d = wait("the build and deploy jobs", build_job, 30 * 60)
    if b["conclusion"] != "success" or d["conclusion"] != "success":
        print(f"run {run_id}: build {b['conclusion']}, deploy {d['conclusion']}")
        return 1
    log = subprocess.run(["gh", "api", "--allow-escape-sequences", f"repos/{REPO}/actions/jobs/{b['databaseId']}/logs"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    sha = built_sha(log)
    if not sha:
        print(f"run {run_id}: no 'building <sha>' line in the build log; check it by hand")
        return 1
    git("fetch", "-q", "origin")
    ok = git("merge-base", "--is-ancestor", merge, sha).returncode == 0
    print(f"run {run_id} built {sha} ({'the merge commit or later' if ok else 'OLDER than the merge commit'}); "
          f"deploy done {d.get('completedAt', '')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
