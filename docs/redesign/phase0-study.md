# Phase 0: the site as it is (2040 redesign)

Studied on the hosted site (deploy 7c743fa), Friday 20 Nov 2026 22:00–22:30 ET, after the close.

**Conditions:**
- Cboe refuses requests, so levels come from the OCC backup.
- NDX fell 5.6% today and VIX closed at 35.9.

**Screenshots** (local only, not committed): every page × NQ/ES × 1366/375 × dark/light, first screen and full
page. Folder: the session scratchpad `p0/NQ`, `p0/ES`.

**Text:** the visible text of every page (NQ, 1366, folds opened).

**Mechanical checks:**
- no sideways scroll in any cell (104 of 104: 52 NQ, 52 ES);
- the Levels page is 2,433 px tall at 1366, and 3,963 px (NQ) or 3,886 px (ES) at 375.

---

## The critique

### What a trader misreads (verified; these are data problems, not taste)

1. **Two NQ prices on the first screen, 191 points apart.**
   - The ticker shows `NQ $25,291`: NQ=F at its 16:59 close, written with a dollar sign on index points.
   - The headline below it says `NQ FUTURES · NOV 20, 5:15 PM ET  25,099.91`. That number is the NDX 16:00 close
     (25,028.98) × the frozen basis (1.002834). It is a futures equivalent of the index close, not the futures price
     at 5:15 PM.
   - A trader comparing it with their chart sees a different number with no explanation.
   - ES has the same gap: the ticker shows `ES $6,967`, the headline `ES FUTURES · NOV 20, 4:35 PM ET 6,926.92`.
2. **The Heatmap and Levels show different "current" levels.**
   - The Heatmap's right-edge column is labelled "GEX now" and shows ZG 27,761.25 and PW 26,424.75. Its own header
     says the latest snapshot is "Thu, Nov 19, 5:20 PM ET", so these are Thursday's Cboe levels.
   - Levels says zero gamma is unavailable and the put wall is 24,770.00 (today's backup).
   - The heatmap file's `source` says "Cboe options", which is true only of those old columns. Friday has no GEX
     columns at all, on a -5.6% day.
3. **The same code means two different prices.**
   - The plan and the paste take C1, P1 and Ab1 from `session.levels`. The Live table builds them from `s.ranked`
     (`app.js` ~1782).
   - Today the plan shows `Ab1 (magnet) -`, while the Live table shows `Ab1 24,770.00`.
   - The Live table's "C1 Call wall 1" is 24,123.50, which is −3.89%, below price.
4. **One label, two numbers.**
   - "Put/call OI" is 1.07 under Levels › More numbers (the whole chain) and 12.04 on the Live table.
   - The Live table's number counts only the price rows on screen (`app.js` ~1827), and the label doesn't say so.
5. **The paste button has no date.**
   - "Copy for TradingView · 16:30 ET" on every page copies **Thursday's** 16:30 paste on Friday night.
   - Data health lists both pastes as "Working" while saying "the paste on the site is the 2026-11-19 16:30 ET one".
   - "Next paste: on hold" is the only clue.
6. **ES: a put wall above the call wall, and a plan built on it.**
   - P1 (put wall 1) is 7,117.00, which is 190 points **above** the price (6,926.92) and above the call wall
     (7,016.75).
   - The plan still reads "Below P1 7,117: hedging adds to selling".
   - The zones assume C1 > zero gamma > P1. When the backup's first-expiry put strike lands above price, the zone
     words stop matching the picture.
7. **To verify:** on Bias, the "open" line is drawn along the chart's top edge (27,177) in the plan for Monday. It
   may be clamped there because it is off the scale, with no ↑ marker.

### Also found by the hosted audit (ui-auditor, same night, 104 cells; not re-verified by me)

**High:**
- **ES P1 differs between pages:** the plan and the level map show 7,117.00, while the Live table shows "Put wall 1
  6,515.50".
- **Zero gamma shows "-" with no reason** on Levels, and the Live table has no ZG row.
- **The banner contradicts the page.** It says zero gamma is "kept", yet it is missing. It says Ab1 is "left out",
  yet the Live table and Bias show Ab1.
- **Bias shows "Abs gamma 27,077"**, Thursday's level, next to today's walls.

**Medium:**
- **Backtesting and Track record ignore the site's NQ/ES switch.** Track record keeps its own "All" toggle;
  Backtesting stays on NQ.
- **Bias, ES, 1366:** the "Call wall · Abs gamma 7,017" label is cut off at the chart's right edge.
- **Heatmap, phone, 2-day view:** "Thu 19 open", "Fri 20 open" and "GEX now" are drawn on top of each other.
- **Layout jumps on first open of 10 pages:** the placeholder heights are taller than the content. For example,
  Glossary goes from 13,954 to 5,471 px, and Track's "Every session" moves from 3,709 to 2,337 px.

**Low:**
- **Contrast** is 4.1–4.4:1 on four small labels: "price is here", ±EM in light theme, the regime icon and Bias "◆".
- **Level map:** the axis labels sit under the gamma bars.
- **News on phones:** forecast and previous values are hidden.
- **Dashes with no reason** in More numbers.
- **Screener:** the NQ future price has no "as of" time.

**Clean everywhere (script checks):**
- no sideways scroll, nothing past the edge;
- no NaN or undefined, no empty cards, no wrapped numbers, no overlapping text;
- 0 script errors;
- every "?" help opens and closes;
- copy works;
- theme and market survive a reload.

### What a trader ignores or has to dig past
- **The backup banner on every page.** It is 3–4 lines and about 190 px of each phone first screen, including on
  Track record, Library and Glossary, where it says nothing about what is shown.
- **13 tabs in one row.** On a phone, 5 are visible. There is no grouping a trader would recognise
  (before / during / after the session).
- **Levels repeats itself.** The same walls appear in:
  - the headline strip;
  - the plan;
  - the level map;
  - the 14-row Levels list (which mixes key levels, max pain, weekly bands and OI walls);
  - and again in "More numbers".

  Max pain also has its own table. A trader has to decide which of five views to believe.
- **Bias sits at the top level although the site's own track record says it has no edge.**
  - "Bias direction right" is 26% (5 of 19) against a baseline of 68%.
  - It is labelled honestly, but its prominence says more than the data does.
- **The command box exists but no one would find it.** It sits in the header (`/`, codes such as LIVE and TRK). Its
  placeholder is cut off at 1366 and the box is hidden on phones.
- **Charts of empty space.** With a ±1,250-point expected move, the level map's ±3.3σ scale spans about 8,000
  points, and the walls and price sit in one narrow band of it.

### What earns its place
- **The headline strip:** price, regime, the walls and the expected move. It is the first thing read, but needs
  the fixes above.
- **The plan:** one zone line, "Below P1 24,770: hedging adds to selling".
- **The paste:** it is the product's job.
- **Track record and Backtesting:** honest sample sizes, ranges, "no edge so far". This is rare and is the site's
  strongest trust signal.
- **Data health:** every source, its age and the reason it failed.
- **Briefings:** plain-English weekly and daily recaps with the numbers in them.

### The 10-second test today (NQ, first screen)

| Question | 1366 | 375 |
|---|---|---|
| Where is price against zero gamma? | "-" (no crossing; the reason is only in the Levels list further down) | same |
| Which wall is nearer? | yes: "330 pts below · 0.3σ" against 3,782 above | yes |
| How fresh is this? | "Updated 36 min ago", plus a time on the price that means something else (see 1) | yes |
| Is this backup data? | yes: the banner | yes: the banner, at the cost of about 190 px |
| Where is the paste? | yes: top right, but with no date (see 5) | yes: the bottom bar |

---

## Inventory

Each page's sections, what they show, where the data comes from, and whether the section shows its own time.
**Source file** is under `data/`. **Time?** is whether the section itself shows an as-of time, as seen tonight.

### Global (every page)

| Item | What | Source | Time? |
|---|---|---|---|
| Ticker | ES, NQ, SPX, NDX, DOW, RUT, VIX, DXY, 10Y: price, % change | quotes.json (Yahoo) | no (per-quote `time` in the data, not shown) |
| Status line | data source, options kind, "Updated N min ago", "Next paste" | all.json | yes |
| Clock | ET time, "Futures closed/open" | browser clock | yes |
| Backup banner | why the levels are an estimate | all.json `backup` | no |
| Copy for TradingView | copies the latest paste | pastes.json | time only, no date |

**Controls:**
- the command box (`/`);
- Explain this page (X);
- theme (T);
- notes under numbers (D);
- keyboard shortcuts (?);
- NQ / ES;
- 13 tabs.

### Levels (all.json: `workers[].result`)

| Section | Numbers | Unit | Time? |
|---|---|---|---|
| Headline | futures-equivalent price; regime; net gamma (all expiries) | pts, $ per 1% | yes |
| Key strip | zero gamma; call wall and put wall with points and σ away; expected move ± and range | pts, σ | inherits the headline |
| Today's plan | regime; price; day ±1σ; Ab1; the current zone and its meaning | pts | yes |
| Level map | CW, P1, PW, price on a ±3.3σ scale; gamma by price; day ±1σ | pts, σ | no |
| What changed today | level moves since 18:00 ET; levels at the 9:30 open | pts | relative ("since 6 pm") |
| Levels list | 14 levels in four groups: key levels, max pain, expected move, volume & OI. Each has its price and distance. A note lists what is unavailable | pts | no |
| Gamma by price | bars by strike; table toggle | $ per 1% | no |
| Max pain by expiration | 8 expiries: max pain, OI | pts, contracts | no |
| Gamma by expiration | 8 expiries: net gamma, share | $, % | no |
| More numbers (fold) | regime; reference price and index close; net GEX; expirations included; hedging per 1%; charm flow; vanna; zero-gamma move; put/call OI and volume; ATM IV; next-expiry share | mixed | the reference price only |
| Level history (fold) | chart of 23 sessions; table of regime, ZG, CW (held / broke / not reached), PW, Ab, band, range, close | pts | the session dates |

### Live table (all.json: `ladder`)

| Section | Numbers | Time? |
|---|---|---|
| Expirations | per expiry: date, DTE, net gamma; Σ All; LATER | no |
| GEX live table | rows by strike: net DEX, GEX, OI, volume; level chips; Tight/Normal/Wide | no (the backup note only) |
| Side panel | price; net GEX; net DEX; regime | yes |
| Key levels | CW, EM±, PW, C1, P1, Ab1, PX, each with % from price | inherits |
| Chain activity | put/call OI (rows shown); put/call volume; most traded; biggest GEX strike | no |

### Heatmap (`heatmap-<m>-<tf>.json`)
- **Shows:** gamma by price every 5 minutes (`columns`); price candles; ZG, CW and PW labels "now"; the latest
  profile at the right edge; its colour scale.
- **Time?** Yes: the latest snapshot and the last candle.
- **Controls:** Today / 2 days / All; 1m / 5m / 15m; the Heat slider; the Levels toggle.

### Screener (screener.json, screener-charts.json)
- **Shows:**
  - NQ futures price and change;
  - the top 15 stocks' combined move in points, their share of the index, the pre-market or after-hours
    implication, up/down counts, biggest lift and drag;
  - points contribution per stock;
  - earnings ahead;
  - a drivers table: 20-day chart, price, today, pre/after, weight, index points, relative volume, earnings.
- **Time?** Yes: prices at 9:27 PM, weights dated.

### Bias (all.json `bias`, positioning.json, bias-history)
- **Shows:**
  - bias, confidence, day type and score (−0.75 to +0.75);
  - the base case and model range;
  - a session path chart with a ±1σ cone, walls, Ab and the open, plus a replay slider and "Back to now";
  - the factors (charm, vanna) with their scores;
  - CFTC positioning: net, weekly change, 3-year rank.
- **Time?**
  - **Bias card:** no.
  - **Chart:** the session date.
  - **CFTC:** "as of Nov 17".

### Track record (trackrecord.json)
- **Shows:**
  - the headline: sessions graded, close inside the expected move, walls held, bias right — each with n and a
    baseline;
  - a scorecard of 12 tests with results, counts and 95% ranges;
  - reactions at each level (5 / 15 / 60 min) against random levels;
  - daily move against the band;
  - where it worked;
  - every session, with a CSV download;
  - the backtest detail (fold): by year, move size, VIX group.
- **Time?** It shows the start date and the session dates, but no "computed at" time.

### Backtesting (studies.json, archive.json, pastes.json)
- **Shows:**
  - a verdict, sessions, level types with 20+ touches, splits tested, rule trades;
  - the sample needed (have / need / reached by);
  - levels against random levels;
  - when it works (7 splits);
  - the rule tester;
  - the history archive;
  - whole weeks;
  - the 9:30 pastes.
- **Time?** Yes: "computed Nov 20, 5:26 PM ET", plus each definition's version hash.

### Briefings (briefings.json)
- **Shows:** NY AM, Asia and Weekly recaps (with a picker for earlier ones); weekly index changes; written prose
  with numbers; headlines; market-moving posts.
- **Time?** Yes: when each was written, and when the next one is due.

### News (news.json, posts.json)
- **Shows:** the economic calendar (impact and currency filters, forecast and previous values); Truth Social posts
  (all or market-related).
- **Time?** Yes: "last updated 37 min ago", and each post's time.

### Indicator (indicator.json, pine-published*.txt)
- **Shows:** Pine version and hash, when it was updated, lines, settings; install steps; the paste (16:30 ET, no
  date); source code; recent changes.
- **Controls:** Copy code; Download .pine; Copy levels; Past days' 9:30 levels; Show source.

### Library, Glossary
- **Library:** 26 lessons with read progress, and a search box.
- **Glossary:** terms with a search box.
- Neither has numbers that change.

### Data health (sources.json)
- **Shows:** 21 sources, each with its provider, status, last success, error and the pages that use it.
- **Time?** Yes: "checked 38 min ago".

---

## What this means for Phase 1

1. **Fix the six misreads before or with the redesign; a prettier screen would only carry them.**
   - Items 1–6 above are data honesty, not design.
   - Each needs a decision about what the number is, then one label, everywhere.
2. **Phase 1 directions must answer:**
   - "which NQ price?";
   - "how do levels from different times look different?";
   - "what does the paste's date look like?"
3. **The inventory shows the same walls in five places.** The gamma field should become the single place where
   levels live; tables become a mode of it (Study), not separate cards.
4. **Bias and Screener are candidates to move into Study or Work, not the front.** The track record's own numbers
   argue for it. That is a design decision to record, not a removal.
