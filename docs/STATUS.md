# Feature status (2026-11-10)

Legend: **Working**: implemented, with automated tests passing in this build. **Partial**:
implemented, with a known gap. **Unverified**: implemented but never run against the real external
system. **Awaiting credentials**: needs your provider account. **Simulated**: test or demo only.

| Area | Feature | Status |
|---|---|---|
| Stress | Quant stress test 2026-11-10 (tools/stress/: 18 scripts, each states its tolerance before running): Greeks, IV solver, independent GEX recompute, zero-gamma stability, ETF merge, chart mapping, roll/expiry, Pine parity, expected-move calibration, bias, reaction-study null, look-ahead, feed fuzzing, calendar 2026-2027, service stress, hosted/local parity | **21 defects fixed** with regression tests. Still failing as specified: chart mapping vs a 4% carry model (the model, not the chart, is off); bias not shown to beat a coin (no graded calls since the fix); band calibration unproven (28 sessions) |
| Math | BSM / Black-76 gamma, delta, price; IV solver; CRR American check | Working (finite-difference and hand-checked) |
| Math | GEX in 3 units with conversion; 4 positioning models | Working |
| Math | Aggregation by strike, side, expiry, DTE bucket; density; totals | Working |
| Math | Zero gamma via sticky-strike profile; multiple and no crossings; coverage guard | Working |
| Levels | Call/put wall, ±GEX max, concentrations, clusters, regime, expected move, gamma-weighted distance | Working |
| Levels | Snapshot diff (level shifts, regime change, concentration shift) | Working |
| Data | Normalization (dupes, OCC validation, bad fields, stale quotes) | Working |
| Data | HTTP retry, backoff, Retry-After, rate limiter, auth classification | Working (tested with simulated responses) |
| Data | SPY merged into SPX (ES) and QQQ into NDX (NQ): exact strikes x ratio (grouped at index strikes for levels), OI and volume / ratio | **Working with live data** (2026-10-23): dollar gamma identical before and after conversion; audit 18/18 for NQ and ES |
| Math | Full audit 2026-10-23: pricing formulas vs finite differences and identities over 840 strike/time/vol/rate/dividend combinations; expected move moved to implied total variance (the old IV·√(1/252) overstated it 1.2-1.4x); calendar, roll, carry, payload parsing as Pine does it, and 61 website number/control checks | **All pass** |
| Math | Independent recomputation from raw Cboe data (own BSM, IV solver, OCC parsing, zero-gamma search) | **Matches** (2026-10-23): net GEX within 0.006% / 0.002%, walls and abs-gamma identical, ZG within 0.001 / 1.2 pts; fixed: Cboe's rounded gamma no longer used for options without IV; rate/dividend now applied |
| Pine | Panel header shows the folded-in ETF (`etf=` payload token, e.g. CBOE SPX+SPY); header text updated | Static tests pass; Pine Editor shows no errors (2026-11-10); not yet tested on a chart: see the checklist in TRADINGVIEW_SETUP.md |
| Data | Tradier, Schwab, Databento adapters | **Removed** 2026-10-23 (free data only) |
| Data | Cboe free delayed feed (SPX, NDX, SPY, QQQ) | **Working with live data** (checked 2026-10-21 overnight; RTH behaviour not yet observed) |
| Data | Schwab Trader API | **Removed** 2026-10-23 (API access denied) |
| Math | Vanna and charm exposure, absolute gamma strike, hedge size in contracts, zero-gamma distance in σ | Working: vanna/charm validated by finite differences; live numbers hand-checked |
| Testing | `python -m gexsys audit`: live end-to-end checks (data, vendor Greeks vs independent recalculation, levels, accounting, payload) | Working: 36/36 checks passed on live Cboe NQ and ES data (2026-10-21) |
| Testing | Pine static checks (define-before-use, built-in shadowing, unused inputs, brackets, panel size, payload keys) | Working: runs with the unit tests; not a substitute for TradingView's compiler |
| Bias | Rule-based daily bias (factors, day type, range, base case) + session chart with cone and path | Working: scenario tests; checked live on NQ/ES. Charm made a tie-breaker 2026-11-09 (it had made every graded call Bullish, 5 of 14 right); intraday momentum tested over 2 years and rejected. Not a validated signal |
| Alerts | Level-shift alerts compare like with like (index points) | Fixed 2026-10-21: before, the futures basis showed up as false ~600-tick "shifts" |
| News | ForexFactory calendar via the faireconomy.media weekly export: 30-min cache, disk copy, last copy kept on failure | Working: checked live 2026-10-21; the feed has no "actual" values |
| Trump posts | Truth Social public API, with the trumpstruth.org RSS as fallback: 5-min cache, disk copy, market-topic tags | Working: checked live 2026-10-21 in a browser (text, ReTruths, quotes, thumbnails) |
| Hosted website | `build-site` writes static files; GitHub Actions rebuilds about every 3 min in cash hours, 6 min overnight while futures trade, hourly when closed, and deploys to Pages; a watchdog restarts it when a run gets stuck; state cached between runs | Working: live at https://wsevwevx.github.io/gex-pro/ (repo WSEVwevx/gex-pro). First GitHub run 2026-10-23: NQ and ES OK, calendar loaded. Truth Social blocks GitHub's servers, so the hosted feed uses the trumpstruth.org archive |
| Briefings | NY AM (09:00 ET, trading days) and Asia (19:00 ET, evenings before trading days), catch-up when the app starts late, Windows notification, 40 kept, local copy filled hourly from the public site | Working: 7 tests; a live Asia briefing written 2026-10-22 and checked on the page |
| Single instance | Exclusive port bind (SO_EXCLUSIVEADDRUSE); a second START.bat exits with "ALREADY RUNNING" | Working: tested (unit test plus a manual second start) |
| Website | Market tape: 18 real quotes (Yahoo chart data, 60 s cache locally, each site build hosted), scrolling, pause on hover, stale marking | Working: 2 tests; checked live 2026-10-24 against the reference screenshot's prices |
| Website | Heatmap: Lightweight Charts candles (Yahoo) with GEX history underneath (per-snapshot `heat` profile, gexsys/heatmap.py), level step lines, hover readout, 1m/5m/15m | Working: 3 tests; checked on NQ and ES in both themes 2026-10-24 |
| Website | Live table (GEX ladder): net DEX / GEX / OI / volume by strike and expiration (gexsys/ladder.py), expiry strip, level chips, side panel | Working: 2 tests; checked live on NQ and ES 2026-10-23 (expiration totals equal net GEX) |
| Website | Market stats strip, gamma by expiration, News tab with impact/currency filters and countdown | Working: checked in a browser against live data |
| Data | Website futures prices from the measured basis (15-minute median NQ=F/NDX, ES=F/SPX ratio), carry model as fallback | Working: 3 tests; the carry model alone was 4-44 NQ points off over 20 sessions (stress test C1) |
| Data | Plausibility guard (exposure far from price, so the source is refused) | Working: caught a broken feed live |
| Website | START.bat; regime/price/net cards; level ladder with a short explanation per level and group filters; GEX-by-price chart with hover and table view; max pain table; Copy for TradingView | Working: checked in a browser against live Cboe data (2026-10-21, overnight) |
| Levels | 0DTE/next-expiration ZG and walls, volume walls, OI walls, max pain per expiration, daily/weekly expected-move bands, GEX profile bins | Working (unit tests with hand-checked values; live Cboe check 2026-10-21) |
| Service | Keeps the last good result when a refresh is unusable (free feeds can blank out overnight); restores it after a restart | Working (tested) |
| Pine | New level groups, on-chart GEX profile, cut-off paste detection, info panel (Minimal/Compact/Full, hideable) | Pine Editor shows no errors (2026-11-10); not yet tested on a chart: see the checklist in TRADINGVIEW_SETUP.md |
| Pine | Level tags with strength bars and hover analysis (ranked C1-C7 / P1-P7 / Ab1-Ab3 from the first expiry or all expiries, confluence count, gamma zones, regime, data age); paste tokens `R`, `R0` | Static tests pass; Pine Editor shows no errors (2026-11-10); not yet tested on a chart: see the checklist in TRADINGVIEW_SETUP.md |
| Data | CSV adapter (ES/NQ futures options, any vendor export) | Working (sample file is hand-made) |
| Data | Synthetic provider | Simulated: labeled SYNTHETIC everywhere |
| Data | Paid feeds (Databento, IBKR, Polygon/Massive) | Not built: free data only. Use CSV or add a `Provider` subclass |
| Mapping | ratio / offset / identity / calendar_offset with skew and cross-index guards, tick rounding | Working |
| Calendar | NYSE holidays and early closes, Globex sessions, DST, roll schedule, expiry times | Working (rules-based; ad-hoc closures are manual) |
| Service | Background refresh workers, session-aware cadence, recovery backoff, `/health`, `/api/levels`, `/api/pine` | Working (synthetic) |
| Service | Snapshot storage (derived only by default) | Working |
| Alerts | Service alerts: regime change, level shift, appear/vanish, stale, unavailable; cooldown; webhook | Working (webhook POST not exercised against a real endpoint) |
| Publish | Scheduled publish slots (ET, holidays, early closes, DST), Windows toast, json/discord webhook, `/api/pine?which=published` | Working (toast fires without error, but on-screen display not confirmed; webhook tested with stubs) |
| Dashboard | Copy-to-clipboard of the scheduled payload | Working (not yet clicked in a browser) |
| Dashboard | Local web dashboard | Working: checked visually against the synthetic service in a browser |
| Pine | v6 indicator: payload parser, live/snapshot mapping, levels, dashboard, alerts, safety blocks | Pine Editor shows no errors (2026-11-10); not yet tested on a chart: see the checklist in TRADINGVIEW_SETUP.md |
| Replay | Stability metrics, sensitivity across models | Working (stored summaries / synthetic) |
| Replay | Strategy evaluation | Not built: methodology only (METHODOLOGY.md §12) |
| Math | Overnight expected move: outside RTH the variance now runs from the quote time (the close), not from the current time. The free quotes and IVs stay frozen overnight, so the band used to shrink all night (NQ 2026-10-22: ~507 at the close to 425 by 23:08) | Fixed 2026-10-23, with a test. Plans frozen before the fix keep the narrower band they showed |
| Track record | Plans frozen from the last snapshot before 09:30 ET, graded after the close (expected move, walls, zero gamma, bias, regime range, magnet) with Wilson 95% ranges; missed sessions kept; hosted copy committed to the `track-record` branch | Working: 12 tests; seeded 2026-10-23 from the snapshots saved 2026-10-21 to 10-23 (4 graded, marked "rebuilt"). The workflow's branch push has not run on GitHub yet |
| Backtest | Expected-move band from VIX (SPX, 1990-) and VXN (NDX, 2009-), same IV x sqrt(days/365) convention | Working: checked live 2026-10-23 (SPX 9,264 sessions, close inside 78%; NDX 4,303, 75%). A proxy: 30-day vol index, not GEX PRO's same-day IV |
| Track record | Level reactions: first touch of each 9:30 level on 1-minute futures, bounce / break / stall at 5, 15, 60 min vs random strikes at the same distance, day-clustered t tests with a Holm correction across the page; 1-minute bars saved per session | Working: 10 tests with known answers; null test on 1,000 random-walk runs: 4.9% of pages show any false verdict (was 52% with per-test ranges); a planted 13-point edge is found on 35% / 66% / 98% of pages after 30 / 60 / 120 sessions; 14 sessions so far (2026-10-21 to 11-06), no level type with enough touches for a verdict yet |
| Backtesting | Every 9:30 paste, and whole weeks in one paste (token W: each day's levels drawn on its own session only) | Working: tests for the week paste; Pine side checked in the editor, not yet on a chart |
| Hosted website | Watchdog (every 15 min): restarts a stuck site in a fresh concurrency lane, opens / closes a GitHub issue | Working: tested live 2026-11-10 (simulated stale site: recovery run started; simulated outage: issue opened, then closed by the next real check) |
| Calendar | Holiday futures sessions: Globex until 13:00 ET on most cash holidays (Thanksgiving, MLK, ...), none before New Year's Day / Good Friday | Working: dry run of the Thanksgiving and Christmas 2026 weeks against publish, track record, bias and briefing schedules |
