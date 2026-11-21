# GEX PRO: the 2040 redesign

Paste everything below the line as the task.

---

You are the design director and lead front-end engineer for GEX PRO
(repo WSEVwevx/gex-pro, hosted at https://wsevwevx.github.io/gex-pro/, local via `.claude/launch.json` "gexpro" at
http://127.0.0.1:8765). The site maps the options gamma exposure of NQ and ES: where dealer hedging tends to slow
price down or speed it up.

You are not polishing the current site. You are giving it a new identity. Two words govern every decision:
**innovative** and **ambitious**. Read `CLAUDE.md` first: its rules override anything below.

## The brief

Make GEX PRO look and feel like a trading instrument from 2040: something a serious trader opens at 09:25 and
trusts at a glance. It must be:
- **easy to use**: a first-time visitor understands the screen in 10 seconds;
- **sophisticated and clean**: the key number first, explanations behind the "?" help, and nothing on screen that a
  trader would not miss;
- **new**: not a restyle of today's site, and not another dark dashboard made of cards.

"2040" means the future as it will actually feel: calm, precise, light, quietly intelligent. It does not mean
science fiction. Banned:
- neon, glow, scanlines, glitch effects;
- HUD corner brackets, hexagons, "terminal" green on black;
- sci-fi or pixel fonts, fake 3D;
- animation that carries no information;
- gradients that exist only to look expensive.

Think of the best physical instruments: a modern watch dial, a cockpit's primary flight display, a museum
wayfinding system, a high-end audio meter. Information is a place you look into, not a list you scroll.

## The identity (invent it, then live by it)

Before any code, give the design language a name and a one-paragraph manifesto. It must answer:
- **Material:** what are surfaces made of? Light, depth and tone, not borders and boxes.
- **Space:** how is price shown as a place you move through, rather than numbers in tables?
- **Voice:** how does the interface speak? Short, plain, descriptive sentences. It describes the market; it never
  tells anyone what to trade.
- **Time:** how does the site know what part of the trading day it is, and change because of it?
- **Truth:** how do freshness, backup data and missing data become part of the visual language, so a trader can
  feel how much to trust a number before reading its label (the label always stays)?

## Ideas to start from (go further; keep only what earns its place)

These are prompts for your imagination, not a checklist. Propose better ones.

1. **The gamma field.**
   - Replace the level list with a continuous field: the real gamma profile by price (`extras.profile` in the data:
     `base_fut`, `width_fut`, `values`), drawn as a calm band of tone, positive and negative.
   - It can extend through time. `data/heatmap-<market>-5m.json` already holds:
     - `columns`: every 5 minutes, gamma by price (`t`, `base`, `w`, `v`) with that moment's `zg`, `cw` and `pw`;
     - `candles`: `[t, open, high, low, close]`;
     - `unit` ("$M of dealer gamma per 1% move"), `source` and `built`.
   - The price is a point moving through the field, with the session's trail from the candles.
   - Walls and zero gamma are where the field changes, not lines someone drew.
   - Exact numbers on hover and tap, and a text version for screen readers.
   - Futures prices come only from the engine's frozen 09:30 mapping (`w.result.mapped`); the page never computes
     its own ratio.
2. **One sentence of state.**
   - Under the price, one sentence built from the data by fixed templates, not AI.
   - The shape, for illustration only: "NQ is below zero gamma, where dealer hedging tends to add to moves. The put
     wall, <price>, is <distance>% below."
   - Every number in it is on the page in the same units, with its time.
   - A historical tendency appears only with its sample size from the track record.
   - Banned words: buy, sell, should, target, will. ("Expected move" is the site's own term and is allowed.)
3. **A day-aware Levels page.**
   - Before the open it leads with the plan and the paste. During the session it leads with live position in the
     field. After the close it leads with how the levels held.
   - The nav order never changes; only the order of sections on Levels does, and a quiet label says which phase it
     is.
   - Today the page does not know the session: `app.js` hard-codes 09:30, 16:00 and weekends (the `phase` line in
     the plan card), which breaks `CLAUDE.md`. Sessions, holidays and early closes must come from
     `gexsys/marketcal.py`, so this idea needs a small engine export (see "Scope").
4. **Trust as material.**
   - Fresh data is crisp. Ageing data visibly quiets (still at least 4.5:1 and never blurred).
   - Backup estimates have their own distinct surface and say "Backup estimate" in words.
   - Missing data is an honest empty shape with the reason. Colour is never the only signal.
5. **Calm motion with meaning.** Numbers that change roll briefly; a level that moved since yesterday glides from
   its old place to its new one, once. `prefers-reduced-motion` turns all of it off.
6. **Glance, work, study.**
   - One switch for density:
     - **Glance:** the price, the sentence, the field, the paste.
     - **Work:** today's full screen.
     - **Study:** history, statistics, sample sizes, methods.
   - No mode ever hides a time, a sample size or a backup/stale label.
7. **Command bar.**
   - Ctrl+K, or "/" when no text box has focus, opens one search box.
   - From it: jump to any page, level or glossary term, or switch market or theme.
   - Fully usable by keyboard and screen reader.
8. **The phone is a first-class instrument.**
   - One-thumb use with a bottom bar; nothing is hidden under the bar; iOS safe areas respected
     (`env(safe-area-inset-*)`).
   - The whole plan is on the first screen.
   - A swipe between NQ and ES works only on the price area, so it never fights a scrolling table or the nav. The
     buttons stay.
9. **Typography as the interface.**
   - One variable typeface with tabular numbers, a deliberate scale, and big numbers set like a watch face.
   - Fonts are self-hosted (open licence, woff2, system fallbacks), so no visitor data goes to a third party and
     the offline copy still works.
   - Colour comes from OKLCH tokens on a perceptual scale.
   - The light theme is as considered as the dark one, not an inversion.

## Scope and what must not change

- **Honesty** (from `CLAUDE.md`):
  - every number shows its "as of" time; every statistic its sample size;
  - missing data says "unavailable" and why; backup data is labelled;
  - stale numbers are never shown as current;
  - "No edge found" stays a valid result.
- **Safety:** no investment advice, no orders; simulated trades are labelled hypothetical.
- **Nothing lost silently.** Phase 0 lists every number and control the site shows today. Each one is either kept,
  or its removal is listed in `JOURNAL.md` with the reason, and named in the final report.
- **Files you may change:**
  - `dashboard/` (including `sw.js` if its cache name must change);
  - `tests/`, `docs/`, `JOURNAL.md`.
- **The one engine exception.** The session-calendar export for idea 3 may add a small, tested piece to the Python
  build that writes the day's session times from `marketcal.py` into the data. It needs my yes in Phase 1 and goes
  in its own PR, following `CLAUDE.md` ("show the source, a raw response sample, the exact math, a wireframe").
  Without that yes, drop idea 3, keep the label as it is, and name the hard-coded times as a known `CLAUDE.md`
  breach in the final report.
- **Never changed:**
  - the engine's calculations, the data files' existing fields, the paste text, the Pine indicator;
  - `.github/workflows/`, `CLAUDE.md`, hooks and settings;
  - graded track-record files, archive files and study definitions.
- **Data:** if a design needs data the site does not have, stop and ask. Never invent or estimate a value.
- **Proof** (`CLAUDE.md`):
  - every new number on screen (a distance in the sentence, a percentage, a scale) has a unit test;
  - every new formula is re-computed independently by the `verifier` subagent, with tolerances fixed before
    running.
- **Tech:**
  - vanilla HTML, CSS and JS, with no framework and no build step;
  - SVG or Canvas 2D (no WebGL); a Canvas drawing has an SVG or text equivalent for screen readers;
  - it works on GitHub Pages.
- **Quality bar:**
  - NQ and ES; 1366 px and 375 px; dark and light;
  - no sideways scroll; no layout jump while loading (keep `DEFAULT_H` in `dashboard/assets/app.js` current);
  - text contrast at least 4.5:1; tap targets at least 44 px on phones;
  - full keyboard use with a visible focus ring;
  - no `aria-live` on ticking prices.
- **Tests:**
  - never weaken one; the count stays at or above 528;
  - the design-token tests in `tests/test_design_tokens.py` read hex and `rgb()`. Extend them to read `oklch()` so
    that no literal colour and no contrast failure can slip through; never loosen them.
- **Performance budget (hosted site, measured before and after):**
  - CLS 0, valid only on a page that painted;
  - the Levels first screen drawn in under 1.5 s on a warm load;
  - smooth scrolling;
  - the site's JS and CSS grow by no more than 60 KB gzipped in total; fonts no more than 120 KB woff2 in total.
  - How to measure:
    - `PerformanceObserver` entries for `layout-shift` and `largest-contentful-paint` in headless Chrome, 3 warm
      loads each at 1366 and 375; report the median;
    - sizes with `gzip -c <file> | wc -c`.

## Process

**Decision authority.** I decide two things in Phase 1: the direction, and yes or no to the session-calendar
export. You decide everything else and record why in `JOURNAL.md`.

0. **Study (no code).**
   - Screenshot every page today, NQ and ES, at both widths, in both themes.
   - Write a one-page critique: what a trader uses, ignores or misreads.
   - Inventory every number and control: where it comes from, its unit, its time.
1. **Three directions.**
   - Three clearly different identities, each with:
     - a name and a manifesto;
     - the Levels page at 1366 and 375 in both themes;
     - one other page;
     - its signature interaction;
     - a wireframe of the gamma field and the sentence with their exact math.
   - Build them on a snapshot of the real hosted data files, labelled with the snapshot time; no placeholders.
   - Publish them as one clickable artifact. I pick one, or mix them, and answer the export question.
2. **Design system.**
   - Tokens: OKLCH colour, type scale, spacing, radii, materials, motion durations and easings, and the
     trust/freshness states.
   - `docs/style.md` rewritten.
   - Tests that hold the system in place.
3. **Shell.**
   - Navigation, the command bar, market and theme switches, density modes, the phone bottom bar.
   - The session-calendar export, if approved, in its own PR.
4. **Levels.**
   - The gamma field, the sentence, the plan and the paste.
   - Every state works:
     - live and stale;
     - backup;
     - unavailable;
     - no zero-gamma crossing;
     - a level beyond the scale;
     - the futures roll week;
     - an early close;
     - a weekend or holiday.
5. **Every other page** in the new language, one PR per group of pages.
6. **Polish.**
   - Motion; empty states.
   - The "?" help behind every number.
   - Move the JS's runtime styles into classes: today about 120 lines of `app.js` set `style=` or `.style`.
     Target: under 15.
7. **Prove it.** Run the audit below on the hosted site. Then the before/after gallery, the journal entry and the
   final report.

Start from `origin/main` (not an old local branch).

## Rules for every PR

- **Size:** a branch per task, about 400 lines or fewer, one idea each.
- **Before opening:**
  - tests pass: `python -m unittest discover -s tests`;
  - `/code-review` on the diff;
  - screenshots of what changed;
  - the PR body lists what was verified and what was not.
- **Merge and deploy:**
  - merge with `gh pr merge <n> --merge -R WSEVwevx/gex-pro` once `tests` passes;
  - wait for `tests` on the merge commit on `main`;
  - deploy at once in a fresh lane with
    `gh workflow run website.yml --ref main -R WSEVwevx/gex-pro -f lane=<next>` (the next free lane was 55 on
    20 Nov 2026; check `gh run list` for the highest lane used);
  - confirm "building <sha>" in the run log.
- **Never:**
  - push to `main` or force-push;
  - merge a PR whose checks failed;
  - merge or deploy 09:00–16:15 ET on a trading day, except a fix.
- **If a deploy breaks the site:** revert it at once with a revert PR.
- **Line endings:** files mix CRLF and LF. Edit with exact-match tools, open files with `encoding="utf-8"`, keep
  each file's endings, never `sed -i`.
- **Never commit:** `OVERNIGHT_REPORT.md` or any secret. Stage files by name.
- **The routine check:** when the every-10-prompts hook asks, run `/check` (check.py, the hosted sweep, the
  source probe) and report it.

## The audit

This is the gate for Phase 7, and runs after every page PR on the pages it touched. The `ui-auditor` agent runs it
read-only. You prepare the special states it needs.

Audit the site like a picky trader on a phone at 09:25 and a QA lead who must sign off.

**Coverage.**
- Every `button[data-p]` page × NQ/ES × 1366x900 and 375x812 × dark/light.
- Open every closed `<details>`, then close it again.
- On Levels, each density mode in every market, width and theme. The command bar once per width and theme.
- Keep a coverage table. A cell counts only if its data loaded.

**Measure in every cell:**
1. Sideways scroll (`scrollWidth - innerWidth > 1`); anything past the right edge or clipped by a parent.
2. Overlap: any two visible text boxes, including SVG `<text>`, that intersect. On phones, anything under the bottom
   bar at first paint.
3. A number, price, date, time or range that wraps.
4. "NaN", "undefined", "null", "[object Object]", "Infinity", "-0", or an empty value.
5. An empty card, a skeleton after 5 s, a spinner that never stops.
6. Layout shift: element positions at 0.5 s and 5 s differ by more than 4 px.
7. Contrast below 4.5:1, computed from the colours actually rendered, including opacity and translucency.
8. On phones, tap targets under 44 px. On any width, a control unreachable by keyboard or without a visible focus
   ring.
9. Script errors (`error`, `unhandledrejection`, the console).
10. With reduced motion on, anything that still animates.

**Look in every cell.** Read the screenshot and write one line: "clean", or what is wrong. Look for:
- misalignment and uneven spacing;
- a label on the wrong line;
- a chart label outside its box;
- a colour that disappears in light theme;
- anything that looks unfinished.

**Truth checks:**
- Every number has its time, every statistic its n, backup data is labelled, missing data says why.
- Times are compared with the freshness stated on the Data health page.
- Zero gamma, the walls and the expected move show the same price, in the same units, on Levels, the field, the
  sentence, the paste and the Live table.
- Switching NQ ↔ ES changes every number.
- Every source label matches the data actually used. For example, the heatmap file's `source` says "Cboe options"
  while the site runs on the OCC backup: check whether each column really came from Cboe.
- The sentence contains no banned word and no claim the page does not show.
- The stale, backup, unavailable and closed-market states are each seen at least once. Use the local site serving
  copies of the data files edited to that state (in the scratchpad, never committed), or report "not checked".

**Interactions:**
- every "?" opens help that fits the screen and closes;
- copy copies the paste (read it back on the page; never paste it anywhere else);
- the theme, market and density choices survive a reload;
- the command bar finds a page, a level and a glossary term;
- the phone swipe changes the market and does not scroll a table.

**Report:**
- the coverage table;
- defects worst first, one line each, with repeats grouped:
  severity | market | width | theme | page | what | measured value | screenshot path.
  Severity: high = wrong or misleading data, or a broken page; medium = hard to read or use; low = cosmetic;
- totals;
- what was not checked and why.

Never report a check that did not run.

## Done means

- **The identity:** it has a name and a manifesto, and the gallery shows every page speaking it.
- **The 10-second test:** on the first screen, at both widths, with a screenshot marking each answer:
  1. Where is price against zero gamma?
  2. Which wall is nearer?
  3. How fresh is this?
  4. Is this backup data?
  5. Where is the paste?
- **The numbers:**
  - 0 inline styles in `index.html`; under 15 places in `app.js` that set styles;
  - every colour from a token;
  - at most 8 font sizes;
  - CLS 0;
  - the performance budget met, with before and after numbers.
- **The audit:** clean on the hosted site, with no high or medium defects.
- **Tests:**
  - at or above 528;
  - new tests for the sentence templates (including the banned words), the field's scale, the freshness states,
    the command bar and the density modes;
  - every new formula passed by the `verifier`.
- **Checks:** `python tools/check.py` passes, except failures caused by an outside source the site does not control
  (for example Cboe's HTTP 403). Each such failure is named in the report.
- **Shipped:**
  - deployed and confirmed ("building <sha>");
  - `JOURNAL.md` records what was tried, kept and cut, and why, including every removed number or control.
- **Gallery:** a before/after gallery artifact for every page, at both widths and in both themes.
- **The report:** a final report that lists what is not done or not verified, including real-phone testing.
