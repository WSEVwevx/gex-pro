# Data providers

Everything runs on **free** data: Cboe's public delayed-quotes feed. No account, key or payment.

| Market | Options used | Source |
|---|---|---|
| ES / MES | **SPX + SPY** options | Cboe free feed |
| NQ / MNQ | **NDX + QQQ** options | Cboe free feed |

## Cboe details (`gexsys/providers/cboe.py`, verified live 2026-10-21 and 2026-10-23)

| | Cboe delayed-quotes JSON |
|---|---|
| Endpoint | `cdn.cboe.com/api/global/delayed_quotes/options/{_SPX,_NDX,SPY,QQQ}.json` |
| Requests | 2 per market per refresh (index chain + ETF chain) |
| Open interest | yes (end of day) |
| IV / Greeks | IV plus Greeks; gamma is rounded to 4 decimals, so it is recomputed from IV |
| Delay | 15 min |
| Terms | unofficial website feed, personal use |
| Cost | free, no key, no signup |

## Why SPY and QQQ are included

A lot of the S&P and Nasdaq-100 options positioning sits in the ETFs, not only the indexes. QQQ in
particular is much larger than NDX options, so NDX alone missed most of the Nasdaq hedging flows. On
2026-10-23, adding QQQ moved NQ's net gamma from -$1.7B to -$10.0B per 1% move, and adding SPY moved
ES from -$56B to -$69B.

How an ETF option joins the index chain (`provider.include_etf`, on in both free configs):

* ratio r = index price / ETF price, from the same Cboe snapshot (about 10 for SPY, 41 for QQQ);
* strike × r, snapped to the nearest listed index strike (within 0.75 of the usual strike spacing);
  ETF strikes that land on the same index strike are added together;
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

## CSV adapter (any other source)

Required columns: `root,type,strike,expiration,multiplier,open_interest`.
Optional columns: `symbol, expiration_time (ISO with offset), bid, ask, last, quote_time, iv, gamma, delta, volume, underlying_price, underlying_time`.
Multipliers: 50 for ES options, 20 for NQ, 5 and 2 for the micros. Timestamps need a timezone offset.
`tests/data/es_fop_sample.csv` is **hand-made test data**, not market data.

## Licensing

* Cboe's feed is for personal use. `storage.store_raw` defaults to `false`, so only derived numbers
  are written to disk.
