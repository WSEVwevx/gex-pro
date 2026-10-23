# Data quality and limitations

## What the levels are

They are **model estimates** built from public open interest and an assumed dealer positioning.
They are not observed dealer hedging flows and not guaranteed support or resistance. Treat every
level as a *modeled concentration of option gamma*.

## Data categories, never substituted for one another

| Label | Meaning |
|---|---|
| RT | real-time quote from an entitled feed (user-declared for Tradier) |
| DL / DELAYED | exchange-delayed quote |
| EOD | end-of-day value. **Open interest is always EOD.** Intraday trading does not change today's OI until the next morning. |
| PROV | Greek/IV computed by the vendor (ORATS for Tradier) |
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
11. **Tradier `updated_at` timezone** is assumed to be ET and has not been verified.

## Behaviour on bad data

| Condition | Behaviour |
|---|---|
| Missing spot | calculation UNAVAILABLE, no levels |
| No OI or no Greeks anywhere | UNAVAILABLE |
| Some Greeks missing | those contracts are excluded, with a count in the warnings |
| IV coverage < 80% | no zero gamma |
| Stale spot | status DEGRADED, with a warning |
| Duplicate contracts | the most recently updated one is kept, with a count |
| Invalid or mismatched OCC symbols (Tradier) | dropped, with a count |
| Crossed quotes or negative OI | the field becomes missing, with a count |
| Provider down | last good result is still served; health shows `degraded`, then `stale`; stale alert |
| Bad credentials | `AUTH` error, retried hourly only |
| Wrong market or implausible mapping in Pine | BLOCKED, nothing drawn |
