# Feature status (2026-10-20)

Legend: **Working**: implemented, with automated tests passing in this build. **Partial**:
implemented, with a known gap. **Unverified**: implemented but never run against the real external
system. **Awaiting credentials**: needs your provider account. **Simulated**: test or demo only.

| Area | Feature | Status |
|---|---|---|
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
| Pine | Panel header shows the folded-in ETF (`etf=` payload token, e.g. CBOE SPX+SPY); header text updated | Static tests pass; **not yet compiled in TradingView by me** - paste the updated script |
| Data | Tradier, Schwab, Databento adapters | **Removed** 2026-10-23 (free data only) |
| Data | Cboe free delayed feed (SPX, NDX, SPY, QQQ) | **Working with live data** (checked 2026-10-21 overnight; RTH behaviour not yet observed) |
| Data | Schwab Trader API | **Removed** 2026-10-23 (API access denied) |
| Math | Vanna and charm exposure, absolute gamma strike, hedge size in contracts, zero-gamma distance in σ | Working: vanna/charm validated by finite differences; live numbers hand-checked |
| Testing | `python -m gexsys audit`: live end-to-end checks (data, vendor Greeks vs independent recalculation, levels, accounting, payload) | Working: 36/36 checks passed on live Cboe NQ and ES data (2026-10-21) |
| Testing | Pine static checks (define-before-use, built-in shadowing, unused inputs, brackets, panel size, payload keys) | Working: runs with the unit tests; not a substitute for TradingView's compiler |
| Bias | Rule-based daily bias (factors, day type, range, base case) + session chart with cone and path | Working: scenario tests; checked live on NQ/ES. Not backtested, so it's a reading of positioning, not a validated signal |
| Alerts | Level-shift alerts compare like with like (index points) | Fixed 2026-10-21: before, the futures basis showed up as false ~600-tick "shifts" |
| News | ForexFactory calendar via the faireconomy.media weekly export: 30-min cache, disk copy, last copy kept on failure | Working: checked live 2026-10-21; the feed has no "actual" values |
| Trump posts | Truth Social public API, with the trumpstruth.org RSS as fallback: 5-min cache, disk copy, market-topic tags | Working: checked live 2026-10-21 in a browser (text, ReTruths, quotes, thumbnails) |
| Hosted website | `build-site` writes static files; GitHub Actions rebuilds every ~15 min in market hours and deploys to Pages; state cached between runs | Working: live at https://wsevwevx.github.io/gex-levels/ (repo WSEVwevx/gex-levels). First GitHub run 2026-10-23: NQ and ES OK, calendar loaded. Truth Social blocks GitHub's servers, so the hosted feed uses the trumpstruth.org archive |
| Single instance | Exclusive port bind (SO_EXCLUSIVEADDRUSE); a second START.bat exits with "ALREADY RUNNING" | Working: tested (unit test plus a manual second start) |
| Website | Market stats strip, gamma by expiration, News tab with impact/currency filters and countdown | Working: checked in a browser against live data |
| Data | Carry-model futures fair value for website prices (F = S·e^((r−q)T)) | Working (hand-checked test); a few points from the traded price by design |
| Data | Plausibility guard (exposure far from price, so the source is refused) | Working: caught a broken feed live |
| Website | START.bat; regime/price/net cards; level ladder with a short explanation per level and group filters; GEX-by-price chart with hover and table view; max pain table; Copy for TradingView | Working: checked in a browser against live Cboe data (2026-10-21, overnight) |
| Levels | 0DTE/next-expiration ZG and walls, volume walls, OI walls, max pain per expiration, daily/weekly expected-move bands, GEX profile bins | Working (unit tests with hand-checked values; live Cboe check 2026-10-21) |
| Service | Keeps the last good result when a refresh is unusable (free feeds can blank out overnight); restores it after a restart | Working (tested) |
| Pine | New level groups, on-chart GEX profile, cut-off paste detection, info panel (Minimal/Compact/Full, hideable) | **Unverified**: not compiled in TradingView |
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
| Pine | v6 indicator: payload parser, live/snapshot mapping, levels, dashboard, alerts, safety blocks | **Unverified**: not compiled in TradingView; see the checklist in TRADINGVIEW_SETUP.md |
| Replay | Stability metrics, sensitivity across models | Working (stored summaries / synthetic) |
| Replay | Strategy evaluation | Not built: methodology only (METHODOLOGY.md §12) |
