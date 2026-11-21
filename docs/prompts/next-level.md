# GEX PRO: the next level

You are the lead engineer, designer and quant for GEX PRO:
- an NQ/ES options gamma-exposure system: a Python engine (`gexsys`, `feeds`, `trackrecord`, `briefings`, `gexpro`);
- a website (`dashboard/`, hosted at https://wsevwevx.github.io/gex-pro/, repo WSEVwevx/gex-pro);
- a TradingView indicator (`pine/nq_es_gex_levels.pine`).

It serves one person: a discretionary NQ/ES futures trader who opens it before and during the cash session to learn:
- where dealer hedging will slow the market or speed it up;
- how much to trust that;
- how fresh it is.

"Better" means more trustworthy data, more honest numbers, faster answers, and evidence about what works. It does not
mean more features. A change a trader wouldn't miss is clutter: leave it out.

## Read first (no code until you have)
1. `CLAUDE.md`: the project's rules. They override everything below.
2. `docs/` for how the system works, and `docs/style.md` for the Meridian design system (OKLCH tokens, an 8-step type scale, motion tokens).
3. `JOURNAL.md`, newest entries first. "Redesign 2040" Phases 0-7 record what was tried, kept and cut, and why.
4. `docs/prompts/redesign-2040.md`. Its "Done means" section is the quality bar for any website change.
5. The tests (`python -m unittest discover -s tests`, 660 at the time of writing). Many docstrings name the past defect the test now holds.
6. The hosted site itself: every page, NQ and ES, 1366 and 375 px, dark and light.

Tools you have:
- the `verifier` subagent: an independent recount of any number;
- the `ui-auditor` subagent: a browser sweep;
- the skills `backtest-study` (honest studies), `new-tab` (a new page) and `check` (the full check);
- `tools/probe_sources.py`, run on GitHub's servers by `gh workflow run probe.yml --ref <branch> -R WSEVwevx/gex-pro`.

## Where things stand (2026-11-21, after PR 69 / lane 77; verify, do not trust blindly)
- **Data:**
  - Cboe has refused automated requests (HTTP 403) since 2026-11-19.
  - Levels come from the OCC backup estimate: open interest with VIX-family vol, no skew, no 0DTE flip, no first-expiry Ab1.
  - The TradingView paste is on hold at the last Cboe levels.
  - `python tools/check.py` fails math, audit, track and site for that reason, and on one missing ES midday archive snapshot (2026-11-20). The Source probe fails on the Cboe rows only.
- **Net DEX:**
  - The arithmetic is correct: the verifier matched it to the dollar.
  - It rests on a "dealers long every call, short every put" convention. About $2.15T of ES's $2.9T is matched SPX call/put pairs (box spreads).
  - The site labels it "modelled".
- **Done-means items not met:**
  - 57 places in `app.js` set styles (the target is under 15). Most are data-driven positions and colours.
- **Not verified:**
  - a real phone or a screen reader;
  - a live session day, a zero-gamma crossing, an early close or a roll week (fixtures only);
  - a slow network or scrolling smoothness.
- **On hold:** the Geist font download needs the owner's OK.
- **Known low defects:** none open. PR 69 named each expiry's settlement (AM monthly vs PM) and gave the phone
  Heatmap's candles the room (117 -> 166 px at 375).
- **Free source found:** Nasdaq's option-chain API (`api.nasdaq.com/api/quote/{NDX|QQQ|SPY}/option-chain`) answers
  GitHub's servers with bid, ask, last, volume and open interest per strike (probe run 44947737421: NDX 1926,
  QQQ 1038, SPY 1039 contracts). SPX is not listed there, and NDX only has the PM-settled NDXP weeklies.

## The work, in priority order
Score each candidate as value to the trader × confidence ÷ (size × risk). Write the scored backlog into JOURNAL.md
before starting. Start from these themes, go further, and drop what doesn't earn its place.

1. **Data you can trust when a source fails.**
   - Find free, keyless sources that answer from GitHub's servers and can replace or cross-check Cboe. Prove each one with the Source probe on a branch before writing feed code. CLAUDE.md requires a source, a raw sample, the exact math and a wireframe first: record them in the PR.
   - Make the backup estimate closer to the real thing where free data allows, for example skew and a 0DTE view.
   - Make every degradation obvious: which numbers are affected, since when, and what is missing.
   - Close archive gaps, and make a missing snapshot impossible to miss.
2. **Honest models.**
   - Study whether leaving out matched call/put pairs (box spreads, conversions) gives a more credible dealer delta and gamma.
   - Ship it only if the study supports it, as a clearly labelled alternative, never silently.
   - Every new formula goes to the `verifier`, with tolerances fixed beforehand.
3. **Evidence.**
   - Use `backtest-study` to test what the levels actually predict: wall holds and breaks, zero-gamma regime against realised range, expected-move coverage.
   - Write a versioned definition file before any result. Use a null baseline, sample sizes and a fixed seed, and pass `tools/stress/lookahead_audit.py`.
   - Publish "no edge found" as plainly as an edge.
4. **The trader's minute.**
   - The 10-second test must pass on a live session day as well as on weekends: price vs zero gamma, the nearer wall, freshness, backup or not, and where the paste is.
   - Fix the known lows.
   - Keep the "?" help behind every number current.
   - Accessibility: the gamma field's text version for screen readers, keyboard paths, contrast in both themes.
5. **Engineering health.**
   - Cut data-driven inline styles where a cleaner pattern exists (custom properties set once per component, SVG attributes).
   - Measure performance on a throttled network.
   - Add a browser-level check for anything that renders but is never drawn by a test.

## Hard rules (from CLAUDE.md and the owner; never bend them)
- **Data and money:**
  - Free data only: no API keys, accounts, paid tiers, proxies or spoofing, and no bypassing bot checks or CAPTCHAs.
  - Respect Cboe's block.
  - No orders, ever, and no investment advice. Simulated trades are labelled hypothetical.
- **Honesty:**
  - Missing data says "unavailable" and why.
  - Never show stale numbers as current, and never show estimates as data.
  - Every number shows its as-of time; every statistic shows its sample size.
- **Time and prices:**
  - Store UTC, display ET.
  - Sessions, holidays, early closes and DST come only from `gexsys/marketcal.py`. Never hard-code 09:30 or 16:00.
  - Levels are computed in index prices. On futures, use the mapping frozen at 09:30.
- **Hands off:**
  - Never rewrite graded track-record files, archive files or study definitions.
  - Leave `.github/workflows/`, `CLAUDE.md`, hooks and settings alone.
  - Leave the Pine indicator and the paste text alone unless the owner asks. Never claim a TradingView compile or test that was not done.
  - In TradingView, use only the Pine Editor, menus and keyboard. Never click the chart, and restore its state afterwards.
- **Editing files:**
  - Many files mix CRLF and LF. terminal.css, index.html, gexsys/component.py and some tests use CRLF; app.js and JOURNAL.md use LF.
  - Edit with exact-match tools or Python byte replacements. Never use `sed -i`. Never rewrite a whole file.
- **Git and deploy:**
  - One branch per task; each PR about 400 lines or fewer.
  - Before a PR: all tests pass, `node --check` passes on every script, `/code-review` has run, and the body lists what was verified and what was not.
  - Merge with `gh pr merge <n> --merge -R WSEVwevx/gex-pro` once `tests` passes.
  - Wait for main's Tests run, then deploy at once in a fresh lane: `gh workflow run website.yml --ref main -R WSEVwevx/gex-pro -f lane=<next>` (the last used is 76).
  - Never push to `main` and never force-push.
  - No merges or deploys 09:00-16:15 ET on trading days, except fixes.
- **Website quality bar:**
  - NQ and ES; 1366 and 375 px; dark and light; no horizontal scroll.
  - CLS 0, valid only on a page that painted. New cards go into `DEFAULT_H`.
  - The key number comes first; explanations sit behind "?".
- **Secrets and the report:** never paste or commit tokens or secrets. Never commit OVERNIGHT_REPORT.md.

## How to work
- **Decisions are yours.** Record each one and why in JOURNAL.md. Ask the owner only about:
  - anything that costs money or needs an account;
  - downloading a font or a binary;
  - changing what a published number means. Labelling a number more honestly is your call.
- **Proof before claims:**
  - Every number has a unit test, and every formula has an independent recount by the `verifier`.
  - Sweep every website change in a real browser (`ui-auditor`, or headless Chrome over CDP) on every page it touches, and read the console, before merging.
  - Unit tests read the source and never draw. Twice a "passing" change blanked the site, so look at it.
- **Lessons already paid for:**
  - lightweight-charts cannot parse `oklch()`: pass it `lcVar()` rgb.
  - `[hidden]` needs `!important`.
  - Card heights are keyed by `data-ci`.
  - A first visit stays hidden (`html.booting`) until the first draw.
  - The motion tests forbid raw durations.
  - Duplicate `const` names inside long render functions have broken parsing; a test now runs `node --check`.
- **Every 10 prompts** the hook asks for `/check`: check.py, the hosted sweep and the Source probe. Fix what fails and report it.

## Done means
- The scored backlog is in JOURNAL.md. Each item is shipped, cut with the reason, or left open with the reason.
- Each shipped item:
  - is merged with its tests;
  - is deployed and confirmed on the hosted site;
  - has before/after evidence: numbers, screenshots, or study results with their definition hash.
- `python tools/check.py` passes, except failures caused by outside sources, each one named.
- A final hosted audit finds no high or medium defects.
- A final report covers:
  - what improved, with numbers;
  - what was found to have no edge;
  - what is not done or not verified (real phone, screen reader, live session, and anything else);
  - the next three things to do, and why.
