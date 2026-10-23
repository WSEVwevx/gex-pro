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
   to `EXTRA_CLOSURES`. CME's abbreviated holiday sessions are treated as `HOLIDAY`.
10. **Rollover.** `front_contract` uses the conventional roll (8 days before the third Friday).
    Futures-options payloads must name the same contract month as the chart, or use `calendar_offset`.
11. **SPY/QQQ in index terms.** ETF options are converted with the live index/ETF price ratio. Dollar
    gamma is exact (exact converted strikes are used for all math), but the ETF's own IV and American
    exercise are kept and its gamma uses the index's dividend yield (QQQ 0.6% vs NDX 0.7%: about 1 NDX
    point of zero-gamma difference). Levels group each ETF strike with the nearest listed index strike.

## Track record and backtest

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

## Strategy lab

- **Option premiums are modeled**, not quoted: Black-Scholes at the VIX / VXN level with no skew and a 10%
  spread cost. Real 1-day options are priced with skew and around events, so the real edge can be smaller.
- **The regime is a proxy** in history (vol index vs its one-year median), not GEX.
- **Daily bars can't order intraday moves**, so intraday rules are judged on about three years of hourly bars,
  which still assume the worst case inside each hour. Fills, margin, assignment and halted markets are not modeled.
- **Eight rules tested, results shown for all.** Testing more variations and keeping the winners would overstate them.

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
| Wrong market or implausible mapping in Pine | BLOCKED, nothing drawn |
