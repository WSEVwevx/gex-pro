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
