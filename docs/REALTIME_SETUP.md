# Daily use: free data, hourly updates

## Start it

Double-click **START.bat**. It installs or updates the dependencies, starts the service, and opens
**http://127.0.0.1:8765**. Keep the black window open while you trade. Closing it stops the service.

## Data source

| Market | Options used | Source |
|---|---|---|
| NQ / MNQ | NDX index options | **Cboe** free delayed-quotes feed |
| ES / MES | SPX index options | **Cboe** free delayed-quotes feed |

* This is the best free source found (checked 2026-10-21). It needs no signup and has open
  interest, IV and Greeks for SPX and NDX in one request.
* Options quotes are **15 minutes delayed**. Open interest is **end-of-day**.
* **Real time:** not available for free. The options for paid or brokerage-account real-time data
  are in [DATA_PROVIDERS.md](DATA_PROVIDERS.md).
* Cboe's Greeks are rounded to 4 decimals, so gamma is recomputed from Cboe's IV.
* The feed is unofficial: no API contract, personal use only. If it breaks, the website shows the
  error and keeps the last good levels.
* **Futures prices on the website** use the measured basis: the median futures / index ratio of the last
  15 minutes both traded (Yahoo NQ=F / ES=F, free), the same rule the indicator uses on your chart. If those
  bars are unavailable, the cost-of-carry model stands in, F = index × e^((rate − dividend) × time to
  expiry); it drifted 4-44 NQ points from the market in Oct-Nov 2026, and the card says which one is in use.

## Updates (every hour)

**Every hour on the hour while NQ / ES futures trade**: from the Sunday 6 pm ET open to the Friday 5 pm
close, Sunday evening, holiday-evening reopens and holiday mornings (Thanksgiving and the like: futures trade
until 1 pm ET) included; none during the 5-6 pm daily break, on weekends, after an early close's 1:15 pm halt,
or on New Year's Day, Good Friday and Christmas:

1. A **Windows notification** appears ("GEX PRO levels updated").
2. On the website, click **Copy for TradingView**. One paste holds NQ and ES.
3. In TradingView, open the **GEX PRO** indicator settings, click into **Levels payload**, press
   Ctrl+A, then Ctrl+V, then click OK.

Use the same paste on your ES chart. Each chart draws only its own market's levels.

Between pastes, the indicator keeps converting index prices to your **real-time** futures price,
using the live `NASDAQ:NDX` / `SP:SPX` reference. Levels are marked `[STALE]` after 90 minutes (one missed hourly update).

## Change the schedule

Edit `"publish": {"times_et": [...], "all_day": true}` in `configs/free_nq_cboe.json` and
`configs/free_es_cboe.json`, then restart START.bat. `all_day: false` keeps only the times before the
cash close (16:00 ET, or 13:00 on early-close days). To stop the hourly Windows notifications, set
`"desktop_notify": false`; the website's Copy button still has each new paste.
