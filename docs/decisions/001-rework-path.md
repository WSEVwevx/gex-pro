# 001: How to rework GEX PRO

Decided: Mon 23 Nov 2026 (owner, after the close). This series is separate from the older
`docs/ADR-001-architecture.md`.

Evidence: the session 1 evidence page, https://claude.ai/artifact/B8t1ZNkxkXNMakoTtsSzR9 (private to the owner),
files `speed_*.json`, `freshness.json`, `build_to_live.json`, `look/judge.md`, `redteam/v0-v2.json`.

## Problem
- The phone first screen is slow on Slow 4G (375 px, cold, n=3): LCP median 2,312 ms (2,288-2,432), max CLS 0.162,
  against budgets of 1.5 s and 0.1. The 1366 px LCP median is 2,460 ms. Measured 23 Nov 12:35-13:00 ET, hosted site.
- The look reads as generic: 7 of the 8 banned patterns are on the Levels page.
- The expected-move band is centred on the prior close. On 23 Nov 17:39 UTC, NQ price was 1.99σ outside it with no
  note on the page (`gexsys/extras.py` anchor, `daily_points`).
- Merge to live has a median of 5.2 min and a max of 48.8 min (n=20, PRs 60-80). Runs left to the push trigger take
  12-49 min.

## Rubric (written before the options)
Scored 1-5, 5 best: truth ×3, trader value ×3, risk ×2, size ×1, data cost ×1. Maximum 50.

## Options and scores (fresh judge)
| Option | Truth | Value | Risk | Size | Data | Total |
|---|---|---|---|---|---|---|
| A. Rebuild site and engine | 3 | 4 | 2 | 1 | 5 | 31 |
| B. Engine rework behind parity + v2 beside v1 | 3 | 4 | 4 | 2 | 5 | 36 |
| C. Smallest: C1 band note, C2 lazy chart library, C3 CLS reserve, C4 merge-and-deploy script | 4 | 2 | 5 | 5 | 5 | 38 |
| **M. Merge: all of C, then B's parity runner and v2, with a pre-rendered first screen** | 4 | 4 | 4 | 2 | 5 | **39** |

Dropped from M: the engine module rework and A's rebuild. Neither fixes a measured number. Both are deferred until a
defect shows, and the parity runner will gate them.

## Red team on M
Written before the test: M sinks if (a) removing the chart library saves < 200 ms of median LCP, or (b) a no-JavaScript
page has median FCP > 1,300 ms. Local gzip copy of the hosted site, 375 px, Slow 4G + CPU ×4, cold, n=5.
The local copy ran 16% slower than the hosted site.

| Variant | KB | FCP median | LCP min / med / max | CLS max |
|---|---|---|---|---|
| As shipped | 199 | 1,380 | 2,516 / 2,692 / 2,780 | 0.295 |
| No chart library | 149 | 1,144 | 1,972 / 2,096 / 2,168 | 0 |
| No JavaScript | 29 | 1,016 | 1,760 / 1,864 / 2,028 | 0 |

Result: not sunk. C2 saves 596 ms and removed the layout shift in all 5 runs. Warning: even with no JavaScript, LCP is
about 1.6 s after the bias correction, so the 1.5 s budget is unproven until a pre-render test is measured.

## Choice
M, in this order:
1. C2, C3, C1, C4. One PR each.
2. A parity runner and v2 scaffolding.
3. The v2 Levels page in the owner's chosen look, racing form / Swiss print. It scored 42/45 on the look rubric and
   passed the blind pick-out and the 10-second test.
4. The switch to v2, on the owner's word.

## Revisit if
- C2 + C3 measured on the hosted site do not cut the 375 Slow 4G LCP median by ≥ 200 ms, or CLS stays ≥ 0.1.
- A pre-render test cannot reach LCP 1.5 s. Then the budget or the page weight needs an owner decision.
- A defect is traced to an engine module. Then the dropped engine rework comes back for that module only.

## Owner's words
- Look: "Form (42/45)" (23 Nov 2026).
- Decision: "Yes, go with M" (23 Nov 2026).
