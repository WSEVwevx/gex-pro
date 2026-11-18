---
name: check
description: The full GEX PRO check - tools/check.py (tests, lint, pricing, independent math, live audit, track record, hosted data), the hosted-site sweep (ui-auditor), and the Source probe result from GitHub. Run when the every-10-prompts hook asks, before calling any task done, and after a deploy.
---

# /check

Run all three parts, then report one table. Do not stop at the first failure; finish every part.

1. Local checks (about 2 minutes, run in the background):
   `python tools/check.py`
   Every line must read PASS. `--quick` skips the live parts; use it only if the user asked for a quick check.
2. Hosted-site sweep: start the `ui-auditor` subagent on https://wsevwevx.github.io/gex-pro/ (every page, NQ and ES,
   1366px and 375px, dark and light). If a website change is not deployed yet, also sweep the local site
   (http://127.0.0.1:8765/, `.claude/launch.json` "gexpro").
3. Sources from GitHub's servers: the latest "Source probe" run
   `gh run list -R WSEVwevx/gex-pro --workflow probe.yml -L 1` then `gh run view <id> -R WSEVwevx/gex-pro --log`
   and read its RESULT line. If it is older than 8 days, say so (do not start one unless the user asked).

Then:
- Fix what fails, on a branch, with a test that would have caught it (CLAUDE.md, Workflow). A fix that changes a
  number also goes past the `verifier` subagent.
- Report: part | result | details, then what was fixed, and what was not checked and why (e.g. the browser pane was
  hidden, the market was closed so live data was the last close). Never report a part as passing that did not run.
