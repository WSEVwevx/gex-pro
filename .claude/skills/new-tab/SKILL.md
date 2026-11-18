---
name: new-tab
description: Add a new page (tab) to the GEX PRO website the house way - source proof first, then data in the Python engine, the page in dashboard/, a Data health row, tests, the size map, and a sweep. Use whenever the user asks for a new tab, page or section built on new data.
---

# /new-tab <what it shows>

Stop after step 1 and wait for the user's OK. Everything else follows CLAUDE.md.

1. Proposal (no code yet):
   - The source: URL, what it costs (must be free, no key or account), its terms, and how often it updates.
   - A raw response sample fetched now, from this PC and from GitHub (`.github/workflows/probe.yml`; add the source
     to `tools/probe_sources.py` on the branch and run the workflow on it). A source that refuses GitHub cannot feed
     the hosted site: say so and stop.
   - The exact math from raw fields to every number shown, with units and the "as of" time of each.
   - A wireframe (ASCII) at 1366px and 375px: the key number first, help text behind "?".
   - What a trader would do with it. If the answer is "nothing", propose dropping it.
2. Branch: `git switch -c tab-<name>`.
3. Engine: a feed module that returns data with its "as of" time, and `sources()` rows for Data health (status
   down / failing / late / partial / waiting / ok, with the reason in words). Missing data is "unavailable" and why,
   never stale numbers shown as current.
4. Page: a `button[data-p]` in `dashboard/index.html` and its view; rendering in `dashboard/assets/app.js`; add the
   new view's card heights to `DEFAULT_H` (wide and narrow) so nothing jumps while loading. NQ and ES, dark and light.
5. Hosted build: the data file is written by `build-site`, so the GitHub build serves it.
6. Tests: a unit test for every number (fixtures from the raw sample), a parse test for a bad or empty response,
   and the health row. Ask the `verifier` subagent to recompute the numbers from the raw sample.
7. Run `python -m unittest discover -s tests`, then `/check`. Sweep the local page with the `ui-auditor` subagent.
8. `/code-review` the diff, then push and open a PR whose body says what was verified and what was not. The user
   merges.
