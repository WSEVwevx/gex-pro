# Data providers

Everything on the hosted site runs on **free** data with no account, key or payment. Option levels are an
estimate: end-of-day open interest from OCC, with implied vols that are not per-strike quotes.

| Market | Options used | Hosted site and this PC | This PC only, with a London Strategic Edge key |
|---|---|---|---|
| ES / MES | **SPX + SPY** | OCC open interest + one vol per expiry from the VIX-family closes | the same OI + each strike's vol from the previous session's smile |
| NQ / MNQ | **NDX + QQQ** | the same, scaled by VXN / VIX | the same |

## OCC chain (`gexsys/providers/occ.py`)

| | |
|---|---|
| Open interest | `marketdata.theocc.com/series-search?symbolType=U&symbol={NDX,SPX,QQQ,SPY}`: end of day, all exchanges |
| Vols | Yahoo daily closes of ^VIX1D, ^VIX9D, ^VIX, ^VIX3M (SPX curve) and ^VXN (NDX scale); no skew |
| Prices | Yahoo chart meta for ^NDX, ^GSPC, QQQ, SPY |
| Source label | `occ+vix`, snapshots under `NQ-OCC` / `ES-OCC` |
| Cost | free, no key, no signup; proven from GitHub's servers by the Source probe |

## Previous session's smile (`gexsys/smile.py`, this PC only)

With `GEX_LSE=1` (START.bat sets it) and a key in `%USERPROFILE%\.lse_key` or `LSE_KEY`, each contract instead gets
an implied vol read off the previous session's per-strike smile, fitted from London Strategic Edge's option rows
(roots NDX + NDXP, SPX + SPXW, QQQ, SPY; strikes within 25% of the price; 1 to 46 days). The method is in
METHODOLOGY section 4d. Source label `occ+lse`, snapshots under `NQ-OCCLSE` / `ES-OCCLSE`; the chain's Data health row
and the site's footnote name the credit ("Data: London Strategic Edge").

* Never on GitHub, the hosted build, the archive branch or the repo: `gexsys/config.py` gives the provider no LSE
  client when `GITHUB_ACTIONS` or `GEX_NO_LSE` is set, and tests use synthetic rows only.
* One session's chain is fetched once, after a 1-row probe shows its Greeks have landed, and kept in
  `%LOCALAPPDATA%\gexsys\lse\chains`. When nothing usable has landed for two sessions, or LSE refuses, the VIX-family
  curve is used and the snapshot's warnings say why.
* 0DTE contracts get no vol from it (the engine leaves them out): yesterday's smile is not today's one-day smile.
* Plan, paste and track record stay off this source until the accuracy study (rework workstream 7) passes.

## Why SPY and QQQ are included

A lot of the S&P and Nasdaq-100 options positioning sits in the ETFs, not only the indexes. QQQ in
particular is much larger than NDX options, so NDX alone missed most of the Nasdaq hedging flows. On
2026-10-23, adding QQQ moved NQ's net gamma from -$1.7B to -$10.0B per 1% move, and adding SPY moved
ES from -$56B to -$69B.

How an ETF option joins the index chain (`provider.include_etf`, on in both free configs):

* ratio r = index price / ETF price, from the same price snapshot (about 10 for SPY, 41 for QQQ);
* strike × r, kept exact for the math and grouped with the nearest listed index strike (within 0.75 of
  the usual strike spacing) for levels, walls and max pain;
* open interest and volume ÷ r, so 10 SPY contracts count as 1 SPX contract;
* the ETF's own IV is kept; gamma is recomputed at the index price.

Because option gamma scales as 1/r when price and strike both scale by r, the converted contract has
**exactly** the ETF option's own dollar gamma (checked on live data and in
`tests/test_free_sources.py`). Walls, max pain and put/call ratios are then all in index-contract
units. If the ETF chain fails to load, the levels come from the index alone, with a warning.

## Free sources considered (2026-10-23)

| Source | Why not used |
|---|---|
| CME's website (futures-options OI, settlements, quotes) | blocks scripts, and CME's terms forbid scraping |
| Yahoo Finance | removed: SPX open interest missing near the money, all OI blanked overnight |
| tastytrade API (free brokerage account) | needs an account; real-time status and futures-options OI for API users not confirmed |
| Paid feeds (Databento, ThetaData, Massive, IBKR data) | not free. Tradier, Schwab and Databento adapters were built earlier and removed |
| Cboe delayed quotes | refused GitHub's servers (HTTP 403); removed from the project in November 2026 |

## CSV adapter (any other source)

Required columns: `root,type,strike,expiration,multiplier,open_interest`.
Optional columns: `symbol, expiration_time (ISO with offset), bid, ask, last, quote_time, iv, gamma, delta, volume, underlying_price, underlying_time`.
Multipliers: 50 for ES options, 20 for NQ, 5 and 2 for the micros. Timestamps need a timezone offset.
`tests/data/es_fop_sample.csv` is **hand-made test data**, not market data.

## Licensing

* `storage.store_raw` defaults to `false`, so only derived numbers are written to disk.
* London Strategic Edge values stay on this PC (see above) and are shown with their credit.

## Other free feeds (not used for option levels)

| Source | Used for | Where |
|---|---|---|
| Yahoo Finance | index, sector and stock closes for the weekly recap; Screener prices | `feeds/weekinfo.py`, `feeds/drivers.py`, `trackrecord/prices.py` |
| Nasdaq.com calendars | past earnings with the surprise, economic data with actual vs consensus | `feeds/weekinfo.py` |
| Google News RSS | headlines from the week's biggest days, shown with their source | `feeds/weekinfo.py` |
| CFTC Traders in Financial Futures | weekly E-mini positioning (Tuesday's data, published Friday) | `feeds/positioning.py` |

Each one is optional: if a source fails, its sentence or card is left out and the rest still works.
