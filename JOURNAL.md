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
