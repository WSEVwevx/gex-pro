# Daily use: free data, 2-hour updates

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
* **Real time:** with a Schwab brokerage account, follow [SCHWAB_SETUP.md](SCHWAB_SETUP.md). START.bat
  then uses Schwab automatically and falls back to Cboe if the weekly login lapses.
* Cboe's Greeks are rounded to 4 decimals, so gamma is recomputed from Cboe's IV.
* The feed is unofficial: no API contract, personal use only. If it breaks, the website shows the
  error and keeps the last good levels.
* **Futures prices on the website** come from the cost-of-carry model,
  F = index × e^((rate − dividend) × time to futures expiry). That's typically within a few points of
  the traded price. TradingView maps levels with your live chart instead.

## Updates (about every 2 hours)

At **09:45, 11:45, 13:45 and 15:30 ET** (trading days only; times after an early close are skipped):

1. A **Windows notification** appears ("GEX levels updated").
2. On the website, click **Copy for TradingView**. One paste holds NQ and ES.
3. In TradingView, open the **GEX Levels** indicator settings, click into **Levels payload**, press
   Ctrl+A, then Ctrl+V, then click OK.

Use the same paste on your ES chart. Each chart draws only its own market's levels.

Between pastes, the indicator keeps converting index prices to your **real-time** futures price,
using the live `NASDAQ:NDX` / `SP:SPX` reference. Levels are marked `[STALE]` after 150 minutes.

## Change the schedule

Edit `"publish": {"times_et": [...]}` in `configs/free_nq_cboe.json` and `configs/free_es_cboe.json`,
then restart START.bat.
