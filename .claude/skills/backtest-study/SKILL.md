---
name: backtest-study
description: Run or add a GEX PRO backtest study the honest way - a versioned definition file written before any result, no look-ahead, fixed seeds, a null baseline, sample sizes, an independent recount by the verifier, and a plain verdict ("no edge found" is valid). Use for any question of the form "does X work / predict / hold".
---

# /backtest-study <question>

Stop after step 1 and wait for the user's OK.

1. Write the definition before looking at any result: the question; the exact rule as code-level steps; the universe
   (NQ, ES, dates from where to where, from which saved files); the outcome measured and its unit; the null or baseline
   it must beat (e.g. the same rule at random levels, seeded); the statistic and the threshold that counts as an edge,
   fixed now; how roll weeks (8 days before quarterly expiry, from `gexsys/marketcal.py`) and early closes are
   handled. Show it to the user.
2. Save it as a versioned definition file (`studies/<name>/v<N>.json` or the folder the backtest code uses) and
   commit it on a branch before running. The result shows the file's SHA-256. A changed definition is a new version;
   old versions and their results stay.
3. Inputs: only data knowable before the session's 09:30 ET (plans frozen at 09:30, futures mapping frozen with the
   plan). Never edit graded track-record files or archives. Random draws use a fixed seed, shown with the result.
4. Run it. Run `tools/stress/lookahead_audit.py` on it; it must pass.
5. Ask the `verifier` subagent to recount the result from the raw files with its own code, tolerances stated first.
6. Report: the result against the null, sample size (sessions, events), the spread or confidence interval, roll-week
   and non-roll results separately, the definition hash, the seed, what was not checked. Simulated trades are
   labelled hypothetical. If it does not beat the null, the verdict is "no edge found" - do not tune and rerun
   without a new version that says why.
7. Add tests for the study's counting code, then branch, `/code-review`, PR as in CLAUDE.md.
