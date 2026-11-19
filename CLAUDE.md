# GEX PRO — rules for Claude

NQ/ES options gamma-exposure system: Python engine (`gexsys`, `feeds`, `trackrecord`, `briefings`, `gexpro`), a website
(`dashboard/`, local at http://127.0.0.1:8765 via START.bat, hosted at https://wsevwevx.github.io/gex-pro/ by
`.github/workflows/website.yml`) and a TradingView indicator (`pine/nq_es_gex_levels.pine`). How it works: `docs/`.

## Data
- Free only: no API keys, no accounts, no paid tiers, no bypassing bot checks or CAPTCHAs.
- A source counts only if it answers from GitHub's build servers (the hosted site is built there). Prove it with
  `.github/workflows/probe.yml`, not just from this PC: Truth Social answers locally but refuses GitHub with HTTP 403.
- Before writing code for a new source or feature: show the source, a raw response sample, the exact math, a wireframe.

## Time, calendar, prices
- Store UTC, display ET. Sessions, holidays, early closes, DST: only `gexsys/marketcal.py`. Never hard-code dates or
  09:30 / 16:00.
- Levels are computed in index prices. On futures, use the mapping frozen with the plan at 09:30, never a later ratio.
- Futures roll weeks (8 days before the quarterly expiry) are flagged in every study.

## Honesty
- Every outside source has a Data health row (`sources()` on its component, `gexpro/health.py`).
- Missing data says "unavailable" and why. Never stale numbers shown as current, never estimates shown as data.
- Every number shows its "as of" time; every statistic its sample size. "No edge found" is a valid result.
- Report what was not verified. Never claim a TradingView compile or test that was not done.

## Proof
- Every number has a unit test. Every formula gets an independent re-computation sharing only the raw input
  (as in `tools/verify_math.py`; the `verifier` subagent), with tolerances fixed before running.
- Random draws use a fixed seed. Studies have a versioned definition file; its hash is shown with the result.
- No look-ahead: inputs to a session's result must be knowable before its 09:30. Studies pass
  `tools/stress/lookahead_audit.py`.
- Never rewrite graded track-record files (lookahead_audit S2) or archive files.

## Safety
- No orders, ever. Simulated trades are labelled hypothetical. No investment advice.
- Never paste or commit tokens or secrets.
- TradingView: only the Pine Editor, toolbars, menus, the settings dialog, the object tree and the keyboard. Never click
  on the chart itself. Restore the chart's state afterwards.

## Quality bar (website)
- NQ and ES; desktop 1366px and phone 375px; dark and light; no horizontal scroll; no layout jump while loading
  (add new cards to `DEFAULT_H` in `dashboard/assets/app.js`).
- The key number first; explanations behind the "?" help. If a trader wouldn't miss it, leave it out: no clutter.

## Workflow
- A branch per task. Before opening a PR: all tests pass (`python -m unittest discover -s tests`), `/code-review` on
  the diff, PR body lists what was verified and what was not. Claude merges its own PR once its `tests` check passes
  (`gh pr merge <n> --merge -R WSEVwevx/gex-pro`); never push to `main` directly or merge a PR whose checks failed.
- `main` is protected: the `tests` check must pass. The website deploys only commits whose tests passed
  (`.github/scripts/tested_commit.py`).
- After a merge, deploy at once in a fresh lane; never wait for the queue:
  `gh workflow run website.yml --ref main -R WSEVwevx/gex-pro -f lane=<next number>`.
- Every 10 prompts the hook asks for `/check` (check.py plus the hosted sweep). Fix what fails; report results.
- Done means: tests pass, `python tools/check.py` passes, the hosted sweep is clean, deployed.

## Files that mix line endings
Many files mix CRLF and LF. Edit with exact-match tools, not whole-file rewrites; keep each file's existing style.
