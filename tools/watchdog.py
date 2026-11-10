"""Keeps the hosted site rebuilding: run by .github/workflows/watchdog.yml every 15 minutes.

  python tools/watchdog.py [--simulate-stale MINUTES] [--dry-run]

The site is STALE when its build stamp (data/stamp.txt) is older than 30 minutes while the futures trade,
or 100 minutes while they are closed (it rebuilds hourly then). When stale:
  1. a recovery started less than 40 minutes ago is still going: wait for it;
  2. otherwise cancel every website run that is stuck (queued or waiting for over 20 minutes, or running for
     over 90), then start a new run in a fresh "lane" (its own concurrency group, so a run GitHub will not
     cancel cannot hold it up; on 2026-11-09 one held the queue for 8 hours), and the chain continues there;
  3. stale for over 90 minutes despite that: open an issue on the repository (GitHub notifies the owner),
     once. When the site is fresh again the issue is closed with a note.
--simulate-stale treats the site as that many minutes old, to test the recovery for real.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gexsys import marketcal  # noqa: E402

SITE = "https://wsevwevx.github.io/gex-pro/data/stamp.txt"
WORKFLOW = "website.yml"
ISSUE_TITLE = "Hosted site stopped updating"
STALE_TRADING, STALE_CLOSED = timedelta(minutes=30), timedelta(minutes=100)
RECOVERY_GRACE = timedelta(minutes=40)
STUCK_WAITING, STUCK_RUNNING = timedelta(minutes=20), timedelta(minutes=90)
ALERT_AFTER = timedelta(minutes=90)


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def is_stale(age: timedelta, now: datetime) -> bool:
    trading = marketcal.session_state(now) in ("RTH", "ETH")
    return age > (STALE_TRADING if trading else STALE_CLOSED)


def stuck(run: dict, jobs: list, now: datetime) -> bool:
    """A run that will not finish by itself: queued / waiting too long, a job waiting on its environment too
    long, or running far past the longest normal run (build + deploy + an hour's wait before the next)."""
    created = _t(run["created_at"])
    if run["status"] in ("queued", "waiting", "pending", "requested") and now - created > STUCK_WAITING:
        return True
    if run["status"] == "in_progress":
        if any(j.get("status") == "waiting" and now - _t(j.get("started_at") or run["created_at"]) > STUCK_WAITING for j in jobs):
            return True
        return now - _t(run.get("run_started_at") or run["created_at"]) > STUCK_RUNNING
    return False


def decide(age: timedelta, now: datetime, runs: list, jobs: dict, open_issue: bool) -> dict:
    """What to do: {"stale", "cancel": [run ids], "dispatch": bool, "open_issue": bool, "close_issue": bool, "why"}.
    runs: recent website runs (GitHub's API objects); jobs: run id -> its jobs."""
    out = {"stale": is_stale(age, now), "cancel": [], "dispatch": False, "open_issue": False, "close_issue": False, "why": ""}
    if not out["stale"]:
        out["close_issue"] = open_issue
        out["why"] = f"fresh: built {int(age.total_seconds() // 60)} min ago"
        return out
    live = [r for r in runs if r["status"] != "completed"]
    stuck_ids = [r["id"] for r in live if stuck(r, jobs.get(r["id"], []), now)]
    recovering = [r for r in live if r["id"] not in stuck_ids and r.get("event") == "workflow_dispatch"
                  and now - _t(r["created_at"]) < RECOVERY_GRACE and "lane" in (r.get("display_title") or "") ]
    out["cancel"] = stuck_ids
    if recovering:
        out["why"] = f"stale ({int(age.total_seconds() // 60)} min), a recovery run started {int((now - _t(recovering[0]['created_at'])).total_seconds() // 60)} min ago"
    else:
        out["dispatch"] = True
        out["why"] = f"stale ({int(age.total_seconds() // 60)} min): {len(stuck_ids)} stuck run(s), starting a new lane"
    out["open_issue"] = age > ALERT_AFTER and not open_issue
    return out


# ---------------------------------------------------------------------------- GitHub
class GitHub:
    def __init__(self, repo: str, token: str):
        self.repo, self.token = repo, token

    def call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(f"https://api.github.com/repos/{self.repo}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "gex-pro-watchdog"})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None


def stamp_age(now: datetime) -> timedelta:
    req = urllib.request.Request(f"{SITE}?t={int(now.timestamp())}", headers={"User-Agent": "gex-pro-watchdog", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return now - _t(r.read().decode().strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulate-stale", type=int, default=0, help="treat the site as this many minutes old")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    gh = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
    try:
        age = stamp_age(now)
    except Exception as e:                              # the site itself is unreachable: as stale as it gets
        print(f"stamp unreadable: {e}")
        age = timedelta(days=1)
    if a.simulate_stale:
        age = timedelta(minutes=a.simulate_stale)
    runs = gh.call("GET", f"/actions/workflows/{WORKFLOW}/runs?per_page=30")["workflow_runs"]
    jobs = {r["id"]: gh.call("GET", f"/actions/runs/{r['id']}/jobs")["jobs"] for r in runs if r["status"] != "completed"}
    issues = [i for i in gh.call("GET", "/issues?state=open&per_page=50") if i["title"] == ISSUE_TITLE and "pull_request" not in i]
    d = decide(age, now, runs, jobs, bool(issues))
    print(json.dumps(d))
    if a.dry_run:
        return 0
    for rid in d["cancel"]:
        for how in ("cancel", "force-cancel"):          # GitHub sometimes refuses both; the new lane does not need them
            try:
                gh.call("POST", f"/actions/runs/{rid}/{how}")
                print(f"{how} {rid}: sent")
                break
            except urllib.error.HTTPError as e:
                print(f"{how} {rid}: {e.code}")
    if d["dispatch"]:
        lane = f"w{os.environ.get('GITHUB_RUN_ID', int(now.timestamp()))}"
        gh.call("POST", f"/actions/workflows/{WORKFLOW}/dispatches", {"ref": "main", "inputs": {"lane": lane}})
        print(f"started a website run in lane {lane}")
    if d["open_issue"]:
        gh.call("POST", "/issues", {"title": ISSUE_TITLE, "body": (
            f"The hosted site's last build is {int(age.total_seconds() // 60)} minutes old while it should rebuild "
            f"every few minutes. The watchdog cancelled {len(d['cancel'])} stuck run(s) and started fresh ones, but the "
            f"site is still stale.\n\nCheck the Actions tab: https://github.com/{gh.repo}/actions\n\n"
            "This issue closes itself when the site updates again.")})
        print("opened an issue")
    if d["close_issue"]:
        for i in issues:
            gh.call("POST", f"/issues/{i['number']}/comments", {"body": f"The site is updating again ({d['why']}). Closing."})
            gh.call("PATCH", f"/issues/{i['number']}", {"state": "closed"})
            print(f"closed issue #{i['number']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
