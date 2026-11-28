# GEX PRO journal

Append-only. One entry per autonomous run: baseline, what was looked at, decisions and why, rejections and why,
lessons, open questions. Read the last 5 entries before deciding anything.

## 2026-11-19 run 1 (started 17:24 ET, after the close)

### Baseline
- main 2dfd893 (PR 24), last good lane 37. Next free lane 38.
- Tests: 475, all pass. check.py: tests, pyflakes, vulture, pricing, site PASS. math, audit and track FAIL:
  Cboe answers this PC with HTTP 403. cdn.cboe.com now 307-redirects to cdn-api.cboe.com, which serves a
  Cloudflare block page. Not a code fault. GitHub's servers still get the chains (Data health: NQ and ES chains ok,
  last_ok 22:20 UTC). Not retried around (no bot-check bypass).
- Probe (GitHub): PASS, 2026-11-18 22:59 UTC (1 day old).
- Hosted at 22:21 UTC:
  - NQ: ref 26,595, C1 27,280, P1 26,427.5, flip 27,619.5, ZG 27,764.25.
  - ES: ref 7,195.10, C1 none, P1 7,219.25, flip 7,504.75.
  - Published slot 16:30 ET (21:33 UTC); next 18:00.
- ES C1 = none is real data, not a bug. In tomorrow's expiry (Fri 11-20, monthly OpEx) no strike within 3% of price
  has positive net GEX; ranked_etf also has no calls. The plan then shows only the put-side rows, which is honest.

### Standard (1-5, before)
- TRUTH 4: the plan contradiction and the open-mapping drift were fixed today (PR 24). The expected-move centre is unstated.
- INSIGHT 3: the level-reaction study exists but is underpowered (22 sessions, no type at 20 touches).
- CLARITY 3: the ±1σ range is centred on the prior close during RTH but never says so; on a gap day it reads as
  today's range around today's price (sweep observation, 2026-11-19 10:24: NQ "expected high" 40-120 pts above price
  after a +1.7% gap).
- CRAFT 4. RELIABILITY 4: Cboe blocks this PC; hosted is fine. RESTRAINT 4. SAFETY 5.

### Backlog (value x confidence / size x risk)
- c) Say what the ±1σ range is centred on: value 4, confidence 5, size 1, risk 1 -> do first.
- a) Near-dated walls study: value 4, confidence 2 (22 sessions; level_reaction v2 already compares C1-C3/P1-P3, the
  first expiry, with CW/PW, all expiries, and no type has 20 touches), size 4, risk 2. Rejected for now: a new study
  would be just as underpowered. Revisit at about 60 sessions. A new study also needs the user's OK on its
  definition (backtest-study skill, step 1).
- d) 09:45 vs 09:30 paste: needs tomorrow's data (first 09:45 slot Fri 11-20). Next run.
- b) Per-level hit rate on Levels: the Backtest page already shows level_reaction with random baselines; repeating
  it on Levels while n < 20 would show anecdotes. Rejected until a type reaches 20 touches.
- e) Morning brief "what changed overnight": not yet checked against briefings/morning.py. Next run.
- f) Design-system pass: no evidence of inconsistency collected yet. Needs a sweep focused on it first.

### Design: c) the ±1σ range names its centre
- Question: "the expected range today, around what?" During RTH the band is centred on the previous close (a
  close-to-close 1σ, the same anchor the track record grades); outside RTH on the last close; in RTH without a
  previous close, on the live price.
- Source: gexsys/extras.py expected_moves(): anchor, anchor_kind (no consumer anywhere). Raw sample from hosted
  ES at 22:21 UTC: anchor_kind "last close/price", daily_points about 130, range 7,065 to 7,325.
- Math: none new. Add a field `anchor_label` = "prior close" (RTH with prev_close) | "last close" (outside RTH: the
  index spot is the last close) | "price" (RTH, no prev_close). Additive field; anchor_kind unchanged.
- Wireframe, measured on the hosted page at 375 px (NQ, 5-digit prices):
  - Key strip "Expected move today": `±705` over `25,890 – 27,300 · prior close`. One line: 16 px, the same as now.
    The longer "· from prior close" wrapped (+16 px), so it was rejected.
  - Plan: `Day ±1σ from prior close | 25,890 – 27,300`. The plan-kv height stays 93 px (the value-side
    variant wrapped: +19 px).
- Replaces "(1σ)" in the key-strip subtitle (σ is in the help) and "Day range ±1σ" in the plan.
- Contracts touched: none (the paste's ema is unchanged; Pine untouched).
- Could break: wrapping at 375 or 1366 (layout jump); a missing anchor_label on old cached results (fall back to the
  current text).
- Worked if: both places name the centre; heights unchanged at 375 and 1366; tests pin the three labels.

### Shipped (run 1)
- PR 25, lane 38 (c2205d2): the ±1σ range names its centre ("· prior close", "Day ±1σ from prior close"). Shows
  once a fresh chain is computed; the old text until then.
- PR 26, lane 40 (515caf1): no "data source failed" banner when the market is shut and the close's numbers are
  shown (health.holds_latest). From the user's screenshot at 17:30 ET in the daily break. Verified on the hosted page
  at 17:58 ET: no banner; Data health still red.
- PR 27, lane 41 (6d9ae97): a 403 reads "REFUSED … a free source blocking automated requests", not "check
  credentials"; retried every 15 min, not hourly. Verified in the hosted health.
- Lane 39 was spent on a redeploy of c2205d2 (PR 26 had a test conflict). No harm.
- Post-deploy, each time: levels unchanged vs baseline (NQ C1 27,280; ES C1 none), slot 16:30, no horizontal
  scroll at 1024.

### Incident: Cboe blocks us (since about 22:22 UTC, 2026-11-19)
- cdn.cboe.com now 307-redirects to cdn-api.cboe.com, which answers HTTP 403 with a Cloudflare block page. This
  happens from this PC and from GitHub's build servers (the build at 22:20 was ok, 22:26 was down).
- Not bypassed: no header, endpoint or retry tricks. The site shows the 16:14 ET chain with its time, which is the
  newest the delayed feed would give until 09:30 anyway. No new paste is published without fresh data.
- If it persists to the open, the site has no fresh levels. Needs the user: wait, or approve a look at another free
  source (show the source, a sample and the math first, per CLAUDE.md).

### Found, not fixed (next run)
- TRUTH, top: two 1σ moves for the same 11-20 expiry in one result. Engine summary.expected_move: NQ IV 38.2% ->
  435 pts. extras.expected_move (shown): IV 50.9% -> 703 pts. ES: 26.3% vs 34.8%. The ATM straddle (360 NQ pts mid)
  implies about 450, closer to the engine's. Hypothesis: atm_iv() keys on the expiry date only, so on a monthly
  expiry it may average the AM-settled monthly (T to 09:30) with the PM weekly. Not proven: saved summaries show
  differences on 11-16/17 too (39% vs 35.5%). Needs a raw chain; Cboe is blocked. Do not change it without one
  plus the verifier.
- CRAFT: when the banner appears after load it pushes #levelsView down 47 px (desktop) / 84 px (phone). Now rarer
  (PR 26), still real for a late hosted build.
- Data health: the paste row reads "Working" while the chains are down (it is the 16:30 paste, correctly timed);
  the summary count leaves out "Not checked yet" rows.
- Tests: one full-suite failure at exactly 18:00:xx ET didn't reproduce (3 runs here, 1 on main). Suspect a test
  reading the real clock at the Globex reopen. Find it.
- ES C1 = none on 11-20 (OpEx) is real: no positive net-GEX strike within 3%.

### Standard (after)
- TRUTH 4 (centre named; the EM discrepancy is open), INSIGHT 3, CLARITY 4 (+1), CRAFT 4, RELIABILITY 3 (-1: Cboe
  block, outside our control; the honesty of how it is shown improved), RESTRAINT 4, SAFETY 5 (no regressions, no
  gates loosened; one pinned string updated in the open, the same check).

### Lessons
- Read the line after a dict you extend: `len(out) > 3` counted keys.
- Test against a fixed clock: a worker test failed only because the 18:00 slot was 20 s away.
- Measure a label at 375 px with the real 5-digit NQ prices before choosing words.

## 2026-11-19 run 2 (started 19:21 ET, after the close; user delegated every decision)

### Baseline
- main 8573ea9 (PR 28). Next free lane 42. Tests: 480, all pass (on main, in a clean worktree).
- check.py: tests, pyflakes, vulture, pricing PASS; math, audit, track, site FAIL. All four fail on live data:
  Cboe refuses (HTTP 403) and the 18:00 paste was not published (no fresh chain). Not code faults.
- Hosted sweep 19:23 ET: 104/104 clean (13 pages x NQ/ES x 1366/375 x dark/light), 0 script errors.
  Levels at 1366x768 NQ: price+time, regime, key strip, plan and "Copy for TradingView" all above the fold;
  #levelsView top 173.8 px. Pane hidden: geometry only, no screenshots.
- Hosted levels: the 16:14 ET chain (NQ ref 26,594.97); paste slot 16:30 ET.
- Metrics: inline style= 64 in index.html, 106 in app.js; 18 distinct font sizes (CSS + JS); app.js 2,484 lines.
- Scores: TRUTH 4, INSIGHT 3, CLARITY 4, CRAFT 4, RELIABILITY 3 (Cboe block), RESTRAINT 4, SAFETY 5.

### Found in the baseline (not fixed yet)
- Data health says "no good copy yet" for both Cboe chains while every page shows the 16:14 copy (the hosted build
  is a fresh process: last_success is empty). The backup PR fixes the local side (Cboe's own last success).
- No page but Data health says the source is blocked; the numbers carry their time, so nothing looks current.

### Decisions
- D1. Backup levels in TradingView. Options: (a) paste them now, (b) website only until a Pine "estimate" label is
  compiled, (c) don't ship the backup. Scores (TRUTH x2, REV x2, VALUE, SIMPLE, CONF): a 2,4,4,4,3 = 23;
  b 5,5,3,4,4 = 31; c 5,5,1,5,4 = 30. Chose b. Undo: drop the `backup` check in service._maybe_publish.
- D2. Grade backup estimates in the track record? (a) yes, (b) exclude them from the open plan and the archive
  "usable" rule. a mixes two methods in one record (TRUTH 2); b keeps the record one method (TRUTH 5), costs graded
  days while Cboe is blocked. Chose b. Undo: remove `not s.get("backup")` in gexpro/context.py and gexpro/archive.py.
- D3. How often to ask Cboe while it refuses: (a) every refresh (as built), (b) every 15 min, the worker's own
  refusal back-off. a is the heavy polling a blocking site objects to; chose b. Undo: RETRY_PRIMARY_S = 0.
- D4. Phase 3, split app.js into modules. Options: (a) ES modules per page, (b) classic scripts cut at the section
  lines (a pure move; classic scripts share one global scope, so inline onclick handlers keep working), (c) keep one
  file with its 26 "// ----------" sections. Scores (TRUTH x2, REV x2, VALUE, SIMPLE, CONF): a 5,3,2,2,2 = 22
  (imports are read-only, so every shared `let` assigned across pages would need rewriting; inline handlers break);
  b 5,5,2,3,4 = 29 (a page's code is spread over several sections, so "one file per page" is not a pure move; it
  adds 10+ requests, a cache list and a test loader for no trader-visible gain); c 5,5,1,5,5 = 31. Chose c.
  The completion criterion "no JS file over 600 lines" is therefore not met, by decision. Undo: do b.
- D5. Type scale. Options: (a) 6 steps (the target), (b) 8 steps where each old size moves at most 1 px (20->22 and
  26->28 the exceptions), (c) leave 19 sizes. a moves 11.5 -> 12.5 on 21 rules (small labels grow, phones wrap):
  5,4,3,4,2 = 27; b 5,5,3,4,4 = 30; c 5,5,1,5,5 = 31 on the rubric, but the user's Phase 4 is a directive, not a
  choice, so c is out. Chose b: 19 sizes -> 8 tokens (--fs-xs..--fs-x3), a test keeps raw px sizes out.
  First cut rounded whole-pixel sizes up (11->11.5, 12->12.5, 13->13.5); the local sweep found new wraps at 375 px
  (level names 2->3 lines, "12:00 PM" on 2 lines in the calendar, Data health names). Now a size between two steps
  takes the lower one: only 10->10.5, 20/21->22 and 26->28 grow. Re-measured at 375: the times are one line again.
  The criterion "6 or fewer" is not met (8), by decision. Undo: revert the PR.

- D6. The banner that appears after load (Phase 2a). On first load render() fills the banner in the same call that
  swaps the placeholders for the data, so only placeholders move, in the frame they are replaced; it moves content when it appears later (a late hosted build, a failed refresh) while the
  reader is at the very top. Options: (a) reserve 47/84 px always, (b) a fixed overlay, (c) no change. a wastes the
  space on every normal visit (VALUE 1); b covers the key strip or the plan on a phone (TRUTH 4); c: the browser's
  scroll anchoring (not disabled anywhere) keeps a scrolled reader's place, and a new warning at the top moving the
  page is the warning doing its job. Scores: a 5,5,1,3,4 = 28; b 4,5,2,3,3 = 26; c 5,5,2,5,4 = 31. Chose c.
  Undo: reserve the space with a min-height on #banner.
- D7. Phase 5 (Levels hierarchy): the baseline sweep found price+time, regime, key strip, plan and the paste button
  all above the fold at 1366x768 already. Rearranging a page that meets its criterion: VALUE 1, risk 2. No change.
- D8. Phase 6 (13 pages -> about 8). Candidates scored value x confidence / (size x risk):
  - Drop the Live table's "Key levels" card: it sits beside the strike table as its context; a trader reading
    strikes would miss it (safeguard 8). 2x2/(1x2) = 2.0 but VALUE of removal is negative. Kept.
  - Merge Track record "How price reacted" with Backtesting "Levels vs random levels": two different methods (live
    5/15/60-min outcomes vs a pre-registered turn rate with a bootstrap interval), not one shown twice. 3x2/(2x2) = 1.5.
  - The page merges (Today / Evidence / Context / Learn): no usage data, 13 tabs with redirects, high risk:
    3x2/(5x4) = 0.3. None reach 2.0; not done. Revisit with evidence of what people use.
- D9. The Pine "estimate" label: the in-app browser has no TradingView session (an anonymous default chart). More
  decisive: indicators already installed would still print "15-min delayed" for an OCC paste, and their version
  is unknown, so backup pastes stay off whatever the new Pine says. Not done; backup stays website-only.
### Shipped (run 2)
- PR 29 (tests only): the republish test pinned to a fixed time (it failed when 18:00 ET fell between two clock reads).
- PR 30: Data health summary also counts "not checked yet" rows.
- PR 31, lane 42 (b70f086): the OCC backup chain. Hosted at 00:40 UTC: both markets on the backup, provider OCC, the
  banner shows, Data health: Cboe "down", backup "partial (website only)", the paste still the 16:30 Cboe one.
  Verifier: curve IVs exact, walls exact, zero gamma within 0.0007 pts (same dividends).

- PR 32, lane 45 (72b436a): the type scale (19 font sizes -> 8). Lane 43 and 44 built b70f086: 43 after a GitHub
  merge error (PR not merged), 44 dispatched 11 s after main's tests started (the deploy takes the newest TESTED
  commit). Lane 45 built 72b436a. Hosted: --fs-base 12.5px, no horizontal scroll, banner shown.
- This PR: the probe links each Cboe chain to its OCC backup (WARN "backup in use", not FAIL) and probes OCC QQQ/SPY.

### Run 2 report
- Tests 480 -> 503. check.py on main: tests, pyflakes, vulture, pricing, audit PASS (audit now passes: the backup
  gives a chain); math, track, site FAIL on Cboe's block only (no raw Cboe chain; the paste is the 16:30 one).
- Hosted sweep: 104/104 clean at baseline; local sweep 104/104 clean after the type scale (its wraps fixed).
- Font sizes 19 -> 8 (target 6: D5). Inline styles unchanged (64 / 106): not reached. app.js 2,484 lines, kept (D4).
- Standard after: TRUTH 4 (backup labelled; EM discrepancy still open, no raw chain), INSIGHT 3, CLARITY 4,
  CRAFT 4 (+consistency), RELIABILITY 4 (+1: fresh levels while Cboe blocks), RESTRAINT 5 (+1: nothing added for
  show; three phases declined on evidence), SAFETY 5.
- Stopped: no remaining candidate scores 2.0 (Phase 8 rule).
- Next 3: (1) RESOLVED below (the two 1σ moves are two different quantities; the shown one is right); (2) inline styles to classes, one
  page per PR, only where a class is reused; (3) revisit page merges when there is evidence of use.

### Run 2, continued ("keep going")
- PR 34, lane 46 (b543932): the NY AM / Asia briefs label backup levels "backup estimate (...; not graded)" instead
  of "15-min delayed", and grade() skips them (they would have been scored into scores.jsonl from Fri 11-20 09:00).
- PR 35, lane 47 (22bac23): Data health takes Cboe's last success from its saved history when the process has none
  (each hosted build is fresh). Hosted now: "Last try failed, worked 22:20 UTC" instead of "no good copy yet".
- Checked: the backup banner shows on every page (Levels, Live table, Bias, Indicator...), not only Levels.
- RESOLVED (by code, the open TRUTH item): the "two 1σ moves". extras.expected_moves already takes each expiry's IV
  from contracts with that exact expiration time (no AM/PM mixing: the hypothesis was wrong). The engine's
  summary.expected_move is a different quantity: the nearest expiration from now. On 11-19 that was the AM-settled
  monthly (settles at the 09:30 open, so it excludes Friday's session); the straddle quoted as support (360 mid) was
  that same AM contract. The site and the indicator show only the extras number (Pine reads emd; the paste's `em`
  token from the engine is parsed but never drawn). So the ±705 shown was the PM contract's full-session move: the
  right one for "today's range". Proof on the backup chain (flat IV per expiry): both IVs equal (NQ 42.46%), points
  differ only by time span (engine: now -> expiry 415; extras: last close -> 16:00 ET 574). Not proven: the small
  IV gap on 11-16/17 (engine 39% vs 35.5%) in the unshown engine number (engine IV vs vendor IV); needs a raw chain.
- D10. Backup pastes, revisited with new evidence: the installed indicator prints the paste's `st` in warning colour
  in its data row ("DL 5m ESTIMATE"), so st=ESTIMATE would label a backup paste without a Pine change; its info
  text would still say "15-min delayed". Options (TRUTH x2, REV x2, VALUE, SIMPLE, CONF): website only 5,5,2,4,4 = 30
  (no new TradingView levels while blocked); paste with st=ESTIMATE 4,5,4,4,4 = 30. A tie goes to the more
  conservative: website only stays. Undo/change: in export.pine_payload send st "ESTIMATE" when summary["backup"],
  and drop the backup check in service._maybe_publish.
- Stopped again: the remaining candidates (inline styles to classes 1.3, page merges 0.3) score under 2.0.

### Lessons (run 2)
- An architecture test caught gexsys importing feeds: write the provider against its own package.
- sed -i in Git Bash strips CR: restore CRLF files with Python, and check git diff --stat for whole-file changes.
- Wait for main's tests by sha, not "the latest run": a deploy dispatched seconds early builds the previous commit.
- Rounding sizes up to a scale wraps phone labels; take the lower step.

### Run state
- Run 2 finished. Last deployed lane 47 (22bac23). Next free lane 48. No open branches.
- Blocked (only the user): none needed. The Pine "estimate" label is declined (D9), not blocked.

## Redesign, Phase 0-1 (2026-11-19, 22:45 ET)
- Baseline: 104 screenshots (13 pages x 1366/375 x dark/light, NQ, fold + full page) from the local site at main
  0a83af0, taken with headless Chrome over CDP. Saved to the session scratchpad, folder `before/` (not committed).
  Measured: index.html 41 inline styles, app.js 106 `style=`, 61 distinct hex colours in terminal.css, 177 border
  rules. Backtesting at 375 px scrolls sideways by 2 px (scrollWidth 377).
- Critique, the 10 worst (screenshot in brackets):
  1. Phone: 350 px of chrome before the first number; the price is below the fold [levels-375-dark-fold].
  2. Phone: the backup banner takes 6 lines (140 px) on every page [ladder-375-light-fold].
  3. Everything is a bordered box with the same weight; nothing leads [levels-1366-dark-fold].
  4. The plan, the most useful block, starts at y=490 on desktop and is off-screen on the phone.
  5. Two strips repeat the same numbers (ticker, market strip, key-level cards) [levels-1366-dark-fold].
  6. The Levels page is 3,953 px tall at 1366 (6,095 at 375): 11 stacked blocks.
  7. Level history table wraps dates and "not reached" into two lines [levels-1366-light-full].
  8. Mono everywhere, including prose and labels; small sizes (12.5 px body) [levels-1366-dark-fold].
  9. Expiry tiles on the Live table repeat a bordered card inside a card [ladder-375-light-fold].
  10. The sidebar's keyboard hints (LVL, LIVE...) add noise for touch and mouse users.
- Phase 1: three directions of the Levels page with the real 22:45 ET numbers (A quiet pro, B level map first,
  C dense refined), published at https://claude.ai/artifact/WUxFg3UWGowYyUWwbZHz33 . Asked the owner to pick.
- Owner's pick (23:05 ET): "A + B's level map". Logged in docs/style.md. Order: tokens, shell, Levels hero with the
  level map, other pages, polish. Merge window tonight until 09:00 ET Fri.

### Redesign shipped (2026-11-20, 00:00-01:00 ET)
- PR 38, lane 49 (380e6cd): tokens. A 4 px spacing scale, three radii, new surfaces, borderless cards, 43 rgba tints
  -> color-mix of the semantic colour, tape/code palettes as tokens. /code-review: --ink4 on --raise was 4.42 / 4.19:1,
  fixed; a test now checks every text tier on every surface in both themes.
- PR 39, lane 50 (3e2c265): shell. Pages in one row under the top bar (no sidebar), market strip hidden, phone header
  one row, sticky page row, "Copy for TradingView" pinned to the bottom on phones, short backup banner on phones.
  Backtesting's 2-5 px sideways scroll at 375 fixed (paste table padding).
- PR 40, lane 51 (fc07154): Levels. Headline row (price + time, regime + distance, net gamma), the plan beside a level
  map drawn to one scale (off-scale levels pinned with an arrow and their real distance), "What changed" full width,
  "More numbers" and "Level history" folded (remembered per viewer). DEFAULT_H re-measured. /code-review: subtitle said
  "futures" when unmapped; a fold re-rendered the page. Both fixed.
- PR 41, lane 52 (28005d4): 41 -> 0 inline styles in index.html; phone tables keep numbers, dates and ranges on one line.
- Measured after: Levels 3,953 -> 2,433 px tall at 1366 (6,095 -> 4,023 at 375). At 1366x768 and 375x812 the first
  screen shows price + time, regime, key levels, the plan with "price is here" and the paste. 52 views, no sideways
  scroll. Tests 510 -> 524, all passing.
- Gallery: https://claude.ai/artifact/U9aSG6UzG47sPW4p916vu4 (before/after first screens, 13 pages x 2 widths x 2 themes).
- Not done: app.js still sets ~100 inline styles at runtime (most are runtime colours and positions); font sizes stay
  at 8 steps; no self-hosted font (system stack); two prose phrases still wrap on phones; real-phone safe areas
  untested.
- Lesson: Python's open() defaults to cp1252 here; a test file with σ was emptied by a failed write. Always pass
  encoding="utf-8".

## 2026-11-21 redesign 2040: Phases 0-1 (started Fri 20 Nov 23:00 ET, after the close)

### Baseline
- main ecbae09 (PR 45). Next free lane 57. Tests 556, all pass.
- Cboe refuses, so levels come from the OCC backup.
- Phase 0 study: `docs/redesign/phase0-study.md`. Its high and medium defects were fixed in PRs 44 and 45 before Phase 1.

### Phase 1: three directions
- Built on a snapshot of the hosted data taken Fri 20 Nov, 11:12 PM ET. It shows Levels at 1366 and 375 in both themes, a level-reactions page, the signature interaction, and a wireframe with exact math for each direction.
- The directions:
  - **Meridian:** price as a bead on a vertical axis; the gamma field as tone.
  - **Strata:** time × price landscape, with a scrub replay.
  - **Signal:** wayfinding. The sentence is the headline and price is a line with stops.
- Artifact: https://claude.ai/artifact/SzFNBPfhFKhy2tRskiMF6e (private).
- The user told me to make the Phase 1 decisions myself ("proceed with all phases and questions without my input").

### Decision: Meridian, with two borrowed pieces
- **Why Meridian:**
  - The first screen at both widths answers the 10-second questions: the price, the sentence, the backup plate, the field and the nearer wall.
  - Its vertical price axis matches the TradingView chart the trader reads beside it.
- **From Strata:** the time × price landscape becomes the Heatmap page, with hatched "no saved GEX" ground and the scrub replay. It was rejected for Levels for two reasons:
  - it pushes the plan below the fold;
  - it is honest only where snapshots exist, and on Fri 20 Nov none exist after Thu 17:20 ET.
- **From Signal:** the measuring tape, which shows Δ pts, % and σ from price to a chosen level.
- **Cut:**
  - Signal's 30 px sentence as the headline: on a phone it pushed the price and the plan below the first screen.
  - Meridian's dial arcs on the reactions page: they carried nothing the numbers did not. Use bars with n instead.

### Decision: the session-calendar export, yes
- `all.json.calendar` already carries holidays, early closes, Globex mornings and no-evening days from `marketcal`.
- It does not carry today's open and close times. `app.js` renderPlan hard-codes 570 and 960 minutes and weekends, a CLAUDE.md breach.
- The export adds the open and close instants in UTC for today and the next session, early closes included, from `marketcal`. The page compares the time now with them.
- Own PR, with tests.

### Open
- The tape overlaps the P1 label on Signal's desktop line. That is moot now that Signal was not picked.

## 2026-11-21 redesign 2040: Phases 2-5 so far (Sat 21 Nov, 00:30-02:00 ET, market closed)

### Shipped (PR, lane)
- **47** the session calendar export (sessions with UTC open and close, early and roll-week flags; state changes). The page clock and the Levels phase come from it, not from 09:30 / 16:00.
- **48** the OKLCH Meridian tokens (`docs/style.md` rewritten).
- **49** the command bar (pages, commands, today's levels, glossary terms; combobox ARIA).
- **50** density (Glance / Work / Study) and the day-aware Levels order.
- **51** (lane 59) the phone bottom bar and the price swipe. It also fixed a live defect from PR 44: a 375 px phone laid every page out at 439 px.
- **52** (lane 60) the sentence under the price, from fixed templates. The verifier confirmed 24 of 24 numbers.
- **53** (lane 61) the gamma field: strike tone, total curve, bead, probe and a text version. The verifier confirmed 6 of 6 numbers.
- **54** (lane 62) the states: the backup plate, ageing ink, and early-close and roll-week notes from the calendar.
- **55** (lane 63) Signal's measuring tape. The verifier confirmed 8 of 8 numbers.
- **56** (lane 64) the Heatmap: the hatched "no saved GEX" ground. It also fixed two live defects.

### Defects found after merge (and the tests that now hold them)
- PR 48: lightweight-charts 4.2 cannot parse `oklch()`. The Heatmap and the Screener stock chart were blank on the hosted site until PR 56. The chart now gets `rgb()` read back from a painted pixel (`tests/test_heatmap_ground.py`).
- PR 50: `.seg{display:flex}` beat `hidden`, so the density buttons showed on every page. A global `[hidden]` rule fixes it.
- Lesson: the unit tests read the source and never draw a chart. A token change has to be swept in a browser on every page, with the console read, before merge. The ui-auditor sweep now runs after each shell or token PR.
- Lesson: `sed -i` in Git Bash rewrote terminal.css's CRLF endings to LF (caught before commit, restored). Edit CRLF files with Python byte replacements only.

### Removed (not silently)
- The floating phone copy button became the bottom bar's "Copy paste" with its date.
- The faint gamma-by-price bars on the level map became the tone strip on the meridian, with exact values on the probe.
- The Heatmap's colour for candles more than 90 minutes after the newest snapshot became the hatched ground. That colour was an old snapshot stretched forward.

### Not verified so far
- A real phone: the swipe, the tap on the field, iOS safe areas.
- A screen reader reading the field's text version.
- A live day with a zero-gamma crossing, an early close or a roll week (fixtures only).
- The self-hosted Geist font: on hold until the owner OKs downloading it. System faces meanwhile.
- openmarket.xyz, suggested by the owner: it has no public data endpoint and needs a sign-in, so it fails the "free, no account, answers from GitHub" rules.

## 2026-11-21 redesign 2040: Phases 6-7 (Sat 21 Nov, 09:00-13:30 ET, market closed)

### Shipped (PR, lane)
- **59** (lane 67) sweep fixes: Heatmap profile width on phones, honest axis-label legend, inert closed drawer, Live table contrast, "60 min" ages, the bottom bar's paste date.
- **60** (lane 68) phone tap targets: every small control gets a 44 px hit box, nothing moves.
- **61** (lane 69) inline styles to classes: 122 -> 57 lines of `app.js` that set a style. Tooltips show through `tipAt` and `.tip.on`; toggles use `hidden`. The review caught two lost colours (`c-good` / `c-bad` missing; `.tk b` outranked `.c-pos`): colour classes are now doubled-class.
- **62** (lane 70) "Latest bias, no session today" on a day without a session; Heatmap axis thousands separators; Screener chart "as of". A duplicate `const day` blanked the whole site locally while every test passed: a test now parses every script with `node --check`.
- **63** (lane 71) sweep 2: Heatmap day labels were a day early (UTC-midnight marks formatted in ET); backup volume says "unavailable", not 0; the Screener "as of" carries its day and the tab reads "Last session".
- **64** (lane 72) Heatmap: the first view keeps its chosen span (it showed the library's default ~13 hours instead of "2 days"); a real resize re-frames it.
- **65** (lane 73) Net DEX labelled as a model. The verifier matched ES +$2,902B and NQ +$220B to the dollar; about $2,150B of ES is matched SPX call/put pairs (box spreads) that the "dealers long calls, short puts" convention counts as full long delta. The engine is unchanged; the card says "modelled dealer delta" and the help gives the caveat. The owner chose this.
- **66** (lane 74) 8 font sizes, all tokens (one off-scale size, the Briefings price 24 -> 22 px); the logo's colours from tokens (now themed in light).
- **67** (lane 75) CLS 0 on a warm load (below).
- **68** (lane 76) the final audit's findings: a first visit waits for the first data draw (it jumped 71 px at 1366, 143 px at 375); every compact dollar amount shows "$" (Net DEX read "+220.37B" beside "-$3.24B").

### Phase 7: the proof
- **Performance budget** (headless Chrome over CDP, 1 cold + 3 warm loads per width, the same hosted data files served locally for both builds; before = ecbae09, after = efa3359):
  - CLS warm, 1366: 0.12 / 0.08 / 0.08 before, 0 / 0 / 0 after; 375: 0 before and after. First visit: 0.04 at 1366 after PR 67 (the banner's height was not known yet); 0 at both widths after PR 68, which keeps a first visit hidden until the first data draw.
  - Largest paint, warm median: about 100 ms at both widths, before and after (budget 1.5 s).
  - Sizes, gzip: JS + CSS +9.0 KB (budget 60 KB); fonts 0 KB (budget 120 KB).
  - Main measured 0.10-0.50 at 1366 before PR 67. Causes: card heights were keyed by position and the day-aware Levels order moved cards after saving (Level history got the plan row's 1,273 px); the area painted before `app.js` laid it out; the banner and headline grew with the data; the clock, paste date and tabs changed width; the level history svg was 150 px empty. Each is held by `tests/test_no_jump_at_load.py`.
- **10-second test**: all five answers on the first screen at 1366 and 375, dark and light (price vs zero gamma and both wall distances in the sentence; freshness in the status strip; backup on the hatched banner and in the sentence; the paste in the top bar or the phone's bottom bar). On a day without a session the field sits below Level history; on a session day it follows the headline.
- **Gallery**: every page's first screen before and after, both widths, both themes, with the marked 10-second test and the budget: https://claude.ai/artifact/8CjDgoEXWaEbbuR5RkpBz5 (private).
- **Final audit** (ui-auditor, hosted, 104 page checks: 13 pages × NQ/ES × 1366/375 × dark/light): 0 high, 1 medium, 2 low, no script errors. The medium (first-visit jump) and one low (Net DEX without "$") are fixed in PR 68. Left: the Live table's expirations help lists 2026-12-18 twice (SPX AM and SPXW PM) with no root to tell them apart; a phone's "2 days" Heatmap squeezes the candles.
- **Done-means numbers**: 0 inline styles in `index.html`; every colour from a token (the browser's `theme-color` meta is the one literal); 8 font sizes; CLS 0 warm; budget met. Not met: "under 15 places in `app.js` that set styles". 57 remain, nearly all data-driven (band and gauge positions in %, bar widths, colours chosen per value, custom properties such as `--accent`, height reservations). Moving them to classes would mean a class per value; kept, and held at 57 by `tests/test_inline_styles.py`.

### Removed (not silently)
- "Today's" on the Bias card on a day without a session; the "Today · 5m" Screener tab label (now "Last session · 5m").
- The literal hex colours in the logo SVG.

### Not verified
- A real phone (swipe, field tap, iOS safe areas); phone captures are Chrome's mobile emulation.
- A screen reader.
- A live session, a zero-gamma crossing, an early close or a roll week (fixtures only).
- Scrolling smoothness (not measured); the hosted site's own load timings (measured on local copies of the same files).
- The Geist font: still on hold until the owner OKs the download.

## 2026-11-21 next level: scored backlog (Sat 21 Nov, 15:50 ET, market closed)
Prompt: `docs/prompts/next-level.md`. Score = value to the trader (1-5) × confidence (0-1) ÷ (size 1-5 × risk 1-3),
estimated before starting. PR 69 (lane 77) closed the two audit lows first.

| # | Item | V | C | S | R | Score |
|---|------|---|---|---|---|-------|
| 1 | Nasdaq option chain in the Source probe (proven from GitHub: run 44947737421) | 3 | 0.9 | 1 | 1 | 2.70 |
| 2 | Throttled-network load measurement (Slow 4G), budget written down | 2 | 0.9 | 1 | 1 | 1.80 |
| 3 | A missing archive snapshot shown on Data health (the 2026-11-20 ES midday gap went unnoticed) | 3 | 0.8 | 2 | 1 | 1.20 |
| 4 | Screen-reader text version of the gamma field | 2 | 0.7 | 2 | 1 | 0.70 |
| 5 | Study: leave out matched call/put pairs from Net DEX / GEX (labelled alternative only if supported) | 4 | 0.5 | 3 | 1 | 0.67 |
| 6 | Study: walls hold or break, against a null of random strikes the same distance away | 5 | 0.4 | 3 | 1 | 0.67 |
| 7 | Backup skew from Nasdaq QQQ/SPY mid prices (implied vol per strike; new formula, verifier first) | 4 | 0.6 | 4 | 2 | 0.30 |
| 8 | NDXP same-day volume from Nasdaq as a 0DTE cross-check | 3 | 0.5 | 3 | 2 | 0.25 |
| 9 | Inline styles in `app.js`, 57 -> under 15 | 1 | 0.8 | 3 | 2 | 0.13 |

Limits of the Nasdaq source, from a full pull on 21 Nov: NDX lists only NDXP (PM-settled weeklies, 1,921 rows, five
expiries to 30 Nov), no AM monthly; SPX is "Symbol not exists"; SPY lists 3,014 rows across the dates asked for.
Prices are as of the prior close on a weekend. Items 7-8 need a CLAUDE.md wireframe and the owner's review before code.

## 2026-11-21 next level: results (Sat 21 Nov, 15:45-16:30 ET, market closed)
- **69** (lane 77) the two audit lows: expiry titles name the settlement; the phone Heatmap's candles 117 -> 166 px.
- **70** the prompt and the scored backlog. **71** the Nasdaq option chain in the Source probe as a candidate; a
  failing candidate warns instead of failing the run (lane 78 deploys 70-71).
- **Backlog 2, throttled network** (headless Chrome, Slow 4G: 150 ms, 1.6 Mbit/s, CPU ×4, hosted site, 1 cold + 2 warm):
  1366 cold first paint 1,520 ms, largest paint 2,448 ms, CLS 0.028 (the banner); warm 360-372 ms, CLS 0. 375 cold
  372 ms largest paint (the sentence), warm 428-632 ms, CLS 0. The 1,500 ms first-screen budget holds on a warm load
  and misses on a cold 1366 load. Waterfall: the page, then 160 KB of scripts (done 1.5 s), then `stamp.txt`, then
  `all.json` (147 KB gzip). Tried: start the stamp and data from the head script. With gzip served locally (3 runs
  each) largest paint went 2.40 -> 2.25 s but first-visit CLS rose 0 -> 0.08: not shipped. What would help:
  `by_strike` is 52 KB of `all.json` (26 KB per market) and isn't needed for the first screen; load it with its page.
- **Backlog 3, missing snapshot**: already shown. Data health's History archive row is "failing" and names
  "2026-11-20 (ES midday snapshot: no usable snapshot within 30 minutes of 12:00 ET)". The backlog's premise was wrong.
- **Backlog 5, matched call/put pairs** (engine's own OCC path on the 21 Nov files, as of the 20 Nov close; matched =
  min(call OI, put OI) per root, expiry, strike, removed from both sides):

  | | Net DEX | Gross GEX | Net GEX | Call wall | Put wall | Abs gamma |
  |---|---|---|---|---|---|---|
  | NQ all | $220.4B | 13.66B | -3.23B | 25850 | 24700 | 27000 |
  | NQ unmatched | $105.9B | 8.47B | -3.23B | 25850 | 24700 | 27000 |
  | ES all | $2,901.9B | 202.06B | -44.23B | 7000 | 6200 | 7000 |
  | ES unmatched | $750.4B | 86.74B | -44.23B | 8100 | 6200 | 6200 |

  Net GEX is unchanged by construction (under "dealers long calls, short puts" a matched pair's gammas cancel), so
  zero gamma can't move. The removed DEX matches the verifier's independent recount to the $0.1B (ES $2,151.5B, NQ
  $114.5B). Verdict: **not shipped.** Removing pairs also removes straddles and two-sided interest at round strikes:
  the ES call wall jumps to 8100, 17% above spot, which no trader would call the wall. Net DEX stays "modelled" with
  its caveat. One day of data (n = 1 per market); there's nothing to say about prediction.
- **Not done:** backlog 4 (screen-reader text), 6 (wall hold/break study: the archive starts 2026-11-18 and Cboe
  chains stopped on 19 Nov, too few sessions for any threshold), 7-9.

## 2026-11-21 corrections to "next level: results" (Sat 21 Nov, 22:20 ET, market closed)
The entry above and its PR text got these wrong. Rechecked the same evening:
- **Phone cold load**: the 375 runs reused the 1366 run's cache (0 KB transferred), so they were warm. With a new
  browser profile per run (Slow 4G, CPU x4, hosted, n = 3 each): 1366 largest paint 2,444-2,504 ms, CLS 0-0.039; **375
  largest paint 2,308-2,664 ms, CLS 0.109 in 2 of 3 runs**. A first visit on a slow phone still jumps; the cause isn't
  traced (the 1.5 s `booting` fallback is the suspect).
- **Early data fetch**: the entry left out that first paint improved (about 1.4 -> 0.8 s) and that one old run had CLS
  0.057. Rerun with a new profile per run, n = 3: largest paint 1366 2,384-2,416 -> 2,772-2,924 ms; 375 2,296-2,352 ->
  2,680-2,832 ms, so slower, where the first comparison had 1366 faster (2.40 -> 2.25 s). The two disagree and the
  cause is unknown. No gain shown, so it stays dropped.
- **`by_strike`**: the Levels page draws it ("Gamma by price", `renderChart`). Whether it is below the first screen was
  not measured, so "isn't needed for the first screen" was not established.
- **NQ expected move**: not a new failure (an earlier check had it at 1,256.7), and the site shows +/-1,320 index
  (+/-1,324 futures), not the 1,066 quoted in chat, which is another field. It grows on frozen prices: the backup's
  vol curve is read at the time left from now (shrinking, so the vol rises toward VIX1D) while the variance is scaled
  by the time left from the quote (`extras.expected_moves` t0). Own recount, tolerance 0.5 NQ / 0.2 ES fixed first,
  matches the hosted values to 0.01: NQ 1,239 at the quote time, 1,320 at 22:08 ET Saturday, 1,456 by Sunday 18:00 ET;
  ES 272, 290, 320. Backup only. Not fixed: the engine's calculations are out of bounds without the owner's word.
- **Matched pairs**: "zero gamma can't move" holds here because the backup gives a strike's call and put one vol; with
  separate call and put vols the gammas would not cancel exactly. Why the ES call wall moves was inferred, not checked.
- **73** changed the Heatmap legend to "with its C / P / Ab levels". False: those marks are the latest calculation's,
  the profile is the newest saved one. Corrected here. PRs 70-73 were merged without a full `/code-review`.

## 2026-11-21 backup expected move (the owner said "Yes, fix it"; market closed)
- **Defect**: on the OCC backup the expected move grew on unchanged prices (NQ 1,257 -> 1,324 over Saturday): the vol
  curve was read at the time left from now, the variance counted from the last quote. Now both use the quote's clock.
- **Scope**: the snapshot carries the curve (`vol_points`); only `extras.expected_moves` reads it, only when the market is
  closed. Full engine output before/after on the saved 20 Nov files at five clock times: 48 values changed, all in
  `extras.expected_move`; none at Mon 11:00 ET.
- **Numbers** (quote time 22:00 UTC, replay): NQ 1,244 / 1,297 / 1,459 / 1,459 (Fri 19:00, Sat 16:00, Sun 18:00, Mon 09:29
  ET) -> 1,240.85 at all four; ES 272.5 / 284.1 / 319.4 / 319.4 -> 271.73. The `verifier` recounted 16 numbers with its
  own code from the raw files, tolerance 0.01 point fixed first: all pass. Hosted values differ slightly (other quote times).
- **Still wrong, not changed**: the weekend counts as calendar days, so a Friday-to-Monday "daily" is about 2.96 days of
  variance; it drops at Monday's open (replay: NQ 1,241 at 09:29, 810 at 11:00, same prices). VIX-family vols carry skew
  (wider than at-the-money), VIX1D may use business time, and NDX uses a 30-day ratio at every tenor. n = 1 weekend.

## 2026-11-22 study weekend_move v1 (the owner said "Yes, study it", then "Yes, run it"; market closed)
- **Question**: from one close to the next, is the index's one-sigma move better sized by calendar days on the backup's vol
  curve (A, what the site does) or by one VIX1D session (B)? Definition SHA-256 9d53ae9b8914..., committed (f15bc72)
  before the code and the result; seed 20261121, 10,000 week-block draws; 1,135 pairs per index, 0 dropped, 2022-05-13 to
  2026-11-20. Git shows the order only (the two commits are 1m51s apart); it can't prove that nothing was run earlier.
- **Verdict by its rule: B is better** (all four conditions, both indexes). A pass changes nothing on the site by itself.

  | group | n | A - B, QLIKE [95%] | A inside 1 sigma; r2/s2 | B inside 1 sigma; r2/s2 |
  |---|---|---|---|---|
  | SPX weekend or longer gap | 230 | +0.4485 [+0.3451, +0.5382] | 92.6%; 0.299 | 80.9%; 0.698 |
  | NDX weekend or longer gap | 230 | +0.3019 [+0.1240, +0.4414] | 89.1%; 0.387 | 73.5%; 0.933 |
  | SPX ordinary night | 882 | +0.0507 [+0.0040, +0.1054] | 62.7%; 1.360 | 70.1%; 0.939 |
  | NDX ordinary night | 882 | +0.1702 [+0.1154, +0.2296] | 56.8%; 1.746 | 64.7%; 1.206 |

  Without a verdict: two-day gaps n 5, early closes n 18. Weekends in roll weeks (n 18): SPX +0.4299, NDX +0.1100
  [-0.2840, +0.4407]. Weekends since VIX1D's launch (n 181; earlier values are back-calculated): SPX +0.4498, NDX +0.2681.
- **Recount**: the `verifier` rebuilt it from the raw files with its own code and calendar; tolerances first (counts exact,
  scores 0.0001, shares 0.05 pp): every claimed number matches. Look-ahead audit L10: 2,270 pairs, 0 violations.
- **What it does and doesn't show** (the verifier's attacks, outside the definition):
  - It is a day-count effect. On ordinary nights B is A x sqrt(365/252) exactly, one constant. On weekends, with the best
    constant fitted to each rule, they can't be told apart (SPX -0.0003 [-0.056, +0.055], NDX -0.032 [-0.102, +0.038]).
    One session at the curve's own vol does as well as B (SPX +0.036 [-0.004, +0.070], NDX -0.013 [-0.100, +0.047]). So
    "count one session, not calendar days" is supported; "use VIX1D" over the curve's vol is not.
  - SPX ordinary rests on tails: five pairs give 84% of it (without them +0.0083 [-0.0229, +0.0418]) and A wins 587 of 882.
    Not a robust ordinary-night edge. NDX: A wins 536 of 882.
  - NDX weekends, later half: mean +0.1660, interval [-0.149, +0.416] includes 0; the rule asked only for the mean.
  - Robust: five other seeds, 4-week blocks, and without the five pairs that favour B most.
  - B is still too wide on SPX weekends (80.9% inside) and too narrow on NDX ordinary nights (r2/s2 1.21).
  - If the band were read as the move to the 09:30 open, A would win ordinary nights; the docs state close to close.
- **Wording flaws in v1** (kept, it is frozen): "calendar days" means elapsed days (9 weekends cross a clock change; wall
  clock moves the numbers by up to 0.0017, every condition still passes); "number of pairs" means the pairs drawn.
- **Not checked**: VIX1D closes 15 minutes after the index, so later news can be in the vol (both rules); the live quote
  time; whether methodology v2.0 held for the whole sample; NDX against Cboe (403). Yahoo and FRED differ on one NDX close
  (2024-10-22, 3.3 bp; no effect on the verdict). SPX and NDX are not independent.
- **After the run** only a helper swap (`marketcal.rth_close_dt`), a docstring line and tests changed; output byte-identical.

## 2026-11-22 sweep fixes (hosted sweep after PR 76: 104 combinations, 8 with a layout defect; market closed)
- **Weekly recap releases were wrong**: Nasdaq files each US release under the day after it (33 of 33 fixed-weekday rows, 2025-07
  to 2026-10), so the recap named the next day and never saw Friday's releases (payrolls). It also printed "Retail Sales 6.82%",
  the first of two unlabelled rows (the other: 0.2% against 0.1%). Now the next day's page is read and dated the day before; a
  row with a consensus beats one without; two with one are both named; parts (U6, ISM employment, NFIB "optimism"...) are out.
  Replayed from saved responses: 20 Nov "Retail Sales 0.2% against 0.1% on Tuesday"; 2 Oct "Payrolls 29K against 89K on Friday".
- Recount (`verifier`, own code, saved pages, exact strings): every release in five weeks matches; 38 of 38 events matched by name
  and time to ForexFactory (16-20 Nov) are one day late; holidays too; no US data row elsewhere. Clock-change week not saved.
- If Nasdaq changes its dates, the fixed weekdays of Redbook, mortgage applications and jobless claims show it and the line is
  left out (logged). Older recaps stay as written, wrong days included; VERSION 6 rewrites only the current week's.
- Not checked: whether Friday's results are on Saturday's page by the recap's time; whether GitHub's servers still get this
  calendar (the 20 Nov recap has it); this PC gets HTTP 403 from Nasdaq since about 100 reads today, not retried.
- Small ones: Bias names "largest +GEX" when that is the magnet, sentence levels are rounded (7,017, was 7,016), the Levels footer
  and the missing -GEX strike name the backup, the plan's subtitle clears its "?", Live table names wrap.
- **Left for later** (reported): "today" on a no-session day; Live table "Later / rest"; "Last try failed" with one missing snapshot.

## 2026-11-22 briefs held by a missing zero gamma (sweep after PR 77)
- The Asia brief for Sun 19:00 ET was not written by 22:50 ET: a brief waited until some market had a zero gamma, and on the
  backup neither NQ nor ES has a crossing within 5%. Monday's NY AM would have waited too. Now any of zero gamma or a wall
  is enough, and the regime line says "with no zero-gamma crossing near price". The late Asia brief is written on the next
  build and marked late (existing rule).
- The sweep's other items: NQ's Bias sentence was right ("biggest gamma" 24,770 is now NQ's abs gamma); the "?" on Briefings
  sitting 2 px over the selector at 375 px is left for later.

## 2026-11-23 backup daily move: one session while closed (the owner: "Plan it first", then "Yes, build it")
- `extras.expected_moves`: on the OCC backup with the market closed, daily V = VIX1D^2 / 252 (VXN-scaled for NDX), the
  rule study weekend_move v1 passed. RTH, Cboe's own quotes and a missing VIX1D close keep the old rule. Weekly and monthly
  are never less than the daily (Thursday night: weekly = daily).
- Expected from the 20 Nov closes (16:00): NQ index +-1,248 -> +-1,021, ES +-273 -> +-223 (x0.818); ordinary nights x1.20.
- Limits carried over from the study: B is still wide on SPX weekends (80.9% inside), its gain is the session count not
  VIX1D itself (one session at the curve's vol did as well), holiday gaps and early closes had no verdict. Monday's 09:30 step
  remains (replay NQ about 1,021 -> 810): RTH was not studied.

## 2026-11-23 decision 001: rework path M, steps C1-C4 (the owner: "Form (42/45)", "Yes, go with M")

- Session 1 (read-only) gave the evidence; decision record `docs/decisions/001-rework-path.md` (PR 81). Look: racing
  form / Swiss print, 42/45, pick-out pass (n=1 per direction: anecdote).
- C2 (PR 83): the chart library loads when a chart opens. Hosted after deploy (24 Nov 00:37 UTC, market closed, Slow 4G
  + CPU x4, cold, n=3): 375 LCP 2,060 / 2,072 / 2,100 ms, CLS 0 (before, 23 Nov RTH: 2,288 / 2,312 / 2,432, CLS 0.162);
  1366 LCP 2,116 / 2,272 / 2,452, CLS 0 (before 2,416 / 2,460 / 2,628, 0.029). Different market state from the
  baseline: compare again in a session. Budget 1.5 s still missed.
- C3 (CLS reserve) dropped: CLS was 0 in every run after C2 (hosted n=6, local n=16); the shift came from the
  library's timing. Revisit if a session reading shows CLS >= 0.1.
- C1 (PR 84): expected_move.spot_sigma and the note "price +X.Xσ, outside the band" past 1 band width, RTH only.
  Verifier recount from the 23 Nov 17:39 UTC all.json: NQ +1.992, ES +1.786 (tolerance 0.01, PASS). Not yet read live
  in a session.
- C4 (PR 85): tools/merge_deploy.py. First runs: PR 84 merge to deploy done 00:41 -> 00:43 UTC (lane 88, built the
  merge commit), PR 85 00:43 -> 00:45 (lane 89). n=2: anecdote against the 5.2 min median (n=20).
- Test fix (PR 82): test_free_sources assumed a 16:00 expiry; on 24 Nov its expiry is Fri 27 Nov, a 13:00 early close.
- Not checked: hosted LCP during a session; the band note live; offline first chart open (library cached only after
  first use). Next in M: parity runner, v2 scaffolding, v2 Levels in the chosen look. Font download (Archivo) not
  yet approved.

## 2026-11-28 decision 002: OCC open interest + the previous session's LSE smile, local only (rework workstream 4)

- The owner: Cboe "completely expelled" (PR 91); estimates "as accurate as possible", no extra estimate
  label needed. So on this PC, with a London Strategic Edge key, each strike gets its own vol from the previous
  session's smile instead of one VIX-family vol per expiry (no skew). Hosted site, GitHub and the archive: unchanged.
- Method `gexsys/smile.py` rules v1 (METHODOLOGY 4d). Two changes made during review: bins average x and IV over the
  same rows (a median IV with a mean x biased the fit by 0.83 vol pts; now 0.007 on synthetic truth); the stale-bin
  screen uses a Theil–Sen line over 3 bins each side (a line through the two neighbours let two nearby stale bins
  hide each other). On ~8 bins, two spikes can still shield each other: documented, not fixed.
- Verifier (own code from the written rules, synthetic LSE-shaped rows, tolerances fixed first): 70 claims PASS on
  the first rules, 51 PASS on the Theil–Sen rules. It noted its E3 case does not separate the two screens;
  tests/test_smile.py does (two adjacent stale bins, 30 bins).
- Parity (tools/parity.py, origin/main vs branch): identical except the new `summary.chain` field.
- Not checked: a live LSE session (the 10-call exploration budget is spent); whether the smile beats the VIX curve
  (workstream 7 study, pre-registered first). Plan, paste and grades stay off occ+lse until then.

## 2026-11-28 study occ_lse_accuracy v1 written (rework workstream 7), sha256 607b25a6...641737

- Written before any comparison. A (IV level vs Cboe's own close quotes, 10-19 Nov, n at most 12 pairs) needs LSE
  Greeks history for 9-19 Nov: not yet budgeted. B: not possible (no historical OI from OCC). C: runs once START.bat has
  cached LSE chains. D: not run (Cboe removed). Pass bar proposed, waiting for the owner; the paste stays held either way.
- 2026-11-28: the owner approved the pass bar ("Approve pass bar"), recorded in studies/occ_lse_accuracy/approval.json
  against the v1 hash; v1.json itself is unchanged. Still nothing computed.

## 2026-11-28 study occ_lse_accuracy v2 part A: "better" (n = 10), verifier PASS

- v2 (sha256 a75e602d...9cffc0) written before any call or result: the first after-close Cboe snapshot (not the last:
  Cboe reprices its frozen 1-day quotes overnight), the engine's index-only daily_iv as truth, LSE flow prints (the
  chain serves only the newest session) collapsed per contract. Pass bar identical to the approved v1 bar.
- 10 LSE calls of the owner's 20. NQ and ES x sessions 9, 10, 16, 17, 18 Nov; none dropped. ES flow truncated at 5000
  prints (the last ~6 minutes), as v2 allows. Secondary (one session late) not run.
- Verdict "better": the smile closer to Cboe than the VIX curve in every pair, the bar's interval below 0. Numbers stay
  local (LSE licence): %LOCALAPPDATA%/gexsys/studies/occ_lse_accuracy/result_v2.json.
- Verifier: own code, every claim PASS (smile IVs within 2e-15). It used its own calendar (zoneinfo), equivalent here.
- Limits: 10 pairs, 2 weeks, one-day expiries at the money only; agreement with Cboe's closing quotes, not a forecast of
  the next session; B and D impossible, so levels were never checked against a full chain.

## 2026-11-28 decision 003: the smile estimate unlocked locally (rework workstream 8; the owner: "Yes, unlock both")

- After study occ_lse_accuracy v2 part A ("better", n = 10): on this PC only, plans and Bias may come from occ+lse
  snapshots, labelled as the estimate, graded in their own series (trackrecord/smile_series.py,
  %LOCALAPPDATA%/gexsys/trackrecord-smile, /api/trackrecord-smile, a card on the Track record page). Never mirrored,
  never built into the hosted site, never in the archive (archive.py excludes occ+lse explicitly).
- Unchanged: the main record still takes no estimate; briefs from an estimate stay ungraded (their data line now names
  the smile); the TradingView paste stays on hold (B and D could not check levels against a full chain).
- Not checked yet: a live session through START.bat with GEX_LSE=1 (the first plan can freeze on Mon 30 Nov).
