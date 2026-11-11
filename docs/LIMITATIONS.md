# Data quality and limitations

## What the levels are

They are **model estimates** built from public open interest and an assumed dealer positioning.
They are not observed dealer hedging flows and not guaranteed support or resistance. Treat every
level as a *modeled concentration of option gamma*.

## Data categories, never substituted for one another

| Label | Meaning |
|---|---|
| RT | real-time quote (not produced by the free Cboe feed) |
| DL / DELAYED | exchange-delayed quote |
| EOD | end-of-day value. **Open interest is always EOD.** Intraday trading does not change today's OI until the next morning. |
| PROV | Greek/IV computed by the vendor (Cboe) |
| CALC | Greek/IV computed by this system from IV or from quote mids |
| SYN / SYNTHETIC | generated test data; never market data |
| STALE | older than the configured limit |
| NA / n/a | missing; shown as missing, never filled in |

## Main sources of error

1. **Positioning sign.** This is the largest effect. Run `sensitivity` to see how much the levels move.
2. **Stale OI.** 0DTE positions opened today are invisible until tomorrow's OI, and 0DTE volume
   often dwarfs OI.
3. **Vendor Greeks are stale relative to spot.** They were computed at the vendor's timestamp.
   `recompute_greeks: "always"` uses the current reference price instead, at the cost of relying on
   vendor IV.
4. **Sticky-strike profile.** Zero gamma assumes IV per strike stays fixed as price moves, and
   ignores time decay across the grid.
5. **American exercise (SPY/QQQ).** BSM gamma is an approximation. A test bounds the error near ATM.
6. **Proxy mapping.** Index and ETF options are not ES/NQ futures options. Basis drifts with rates
   and dividends, and ETF ratios drift with distributions and fees. Settlement, exercise style,
   trading hours and IV surfaces all differ.
7. **Reference price outside RTH.** Cash indices don't trade overnight. Pine holds the last factor,
   and the service refuses basis mapping when the prices are more than `max_skew_s` apart.
8. **TradingView is a snapshot.** Pine levels change only when you paste a new payload.
9. **Calendar.** NYSE holiday rules are coded from 2022 on. Unscheduled closures have to be added
   to `EXTRA_CLOSURES`. CME's abbreviated holiday sessions are modeled as Globex trading until 13:00 ET on
   every NYSE holiday except New Year's Day, Good Friday and Christmas (closed all day, with no session the
   evening before); CME occasionally changes a holiday's hours, which is not picked up automatically.
10. **Rollover.** The website's carry model prices the quarterly a continuous chart shows (NQ1!, ES1!: the
    expiring contract until its 09:30 settlement). If you roll your chart to the next month 8 days early,
    the indicator still maps correctly (it uses your chart); the website's futures prices are then a roll apart.
    Futures-options payloads must name the same contract month as the chart, or use `calendar_offset`.
11. **SPY/QQQ in index terms.** ETF options are converted with the live index/ETF price ratio. Dollar
    gamma is exact (exact converted strikes are used for all math), and the ETF's own IV, dividend yield and
    American exercise are kept. Levels group each ETF strike with the nearest listed index strike.

## Track record and backtest

- **Kept forever.** Every session is its own file plus a row in `history.csv`, in
  `%LOCALAPPDATA%\gexsys\trackrecord` and in the public `track-record` branch on GitHub. Neither is ever
  pruned (only the snapshots are, after 12 days). The local app copies in, every hour, any session the
  public record has that it is missing, so days the PC was off are filled from GitHub.
- **GitHub pauses scheduled workflows after 60 days without repository activity.** The workflow's own
  track-record commits may not count; push any change (or press "Run workflow") at least every couple
  of months so the public record keeps growing.

- **Short history.** Free historical open interest does not exist, so gamma levels can only be graded from
  the first saved session on (2026-10-21). Until about 20 sessions are graded the numbers mean little.
- **Rebuilt plans.** Sessions before the track record existed were frozen later from saved snapshots. They
  use only data timestamped before the open, and the page marks them "rebuilt".
- **Early bands were too narrow.** Plans for 2026-10-21 to 10-23 were frozen before the overnight
  expected-move fix, so their bands are 10-20% narrower than a close-to-close band. They stay as they were shown.
- **Index, not futures.** Plans are graded on SPX and NDX, so futures-only moves outside cash hours are not counted.
- **Price sources.** NDX daily bars come from Yahoo (unofficial); SPX from Cboe; same-day bars from Cboe 1-minute data.
- **The backtest is a proxy.** It uses the 30-day VIX / VXN, not GEX PRO's own same-day IV, and only tests
  the expected-move band. Hypothetical results: no orders, costs or slippage.
- **Level reactions need months.** The study measures only the first touch of each level per session, so a level
  type gathers about one touch every few sessions; most types need 30+ sessions for 15 touches. The free 1-minute
  source keeps about 30 days, so a session whose bars were not saved in time is left out for good. Levels are
  converted to futures with the 9:30 ratio, so a basis change during the day shifts them by a few points.
  Bounce, break and stall are fixed rules (a quarter of the move expected over the horizon), not a trading
  strategy: no entries, stops, costs or slippage.

## Behaviour on bad data

| Condition | Behaviour |
|---|---|
| Missing spot | calculation UNAVAILABLE, no levels |
| No OI or no Greeks anywhere | UNAVAILABLE |
| Some Greeks missing | those contracts are excluded, with a count in the warnings |
| IV coverage < 80% | no zero gamma |
| Stale spot | status DEGRADED, with a warning |
| Duplicate contracts | the most recently updated one is kept, with a count |
| Invalid or mismatched OCC symbols (Cboe) | dropped, with a count |
| Crossed quotes or negative OI | the field becomes missing, with a count |
| Provider down | last good result is still served; health shows `degraded`, then `stale`; stale alert |
| Bad credentials | `AUTH` error, retried hourly only |
| Wrong market in Pine | nothing drawn; the panel names the market the paste was for |
| Implausible mapping in Pine (a level over 8% from price) | BLOCKED, nothing drawn |
