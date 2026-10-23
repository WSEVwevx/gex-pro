# Data providers

START.bat picks the source automatically:

| | **Databento** (CME futures options) | **Cboe** (free fallback) |
|---|---|---|
| Options used | **NQ and ES options on the futures themselves** (CME Globex) | NDX and SPX index options |
| Levels are in | futures prices directly | index prices, translated to futures |
| Price | real time (Databento CME Standard plan) | 15 min delayed |
| Open interest | CME end-of-day | Cboe end-of-day |
| IV / Greeks | computed here (Black-76) from each option's live mid or official settlement | Cboe IV; gamma recomputed |
| Cost | Databento subscription (CME Standard, about $199/month in Oct 2026) | free, no key |
| Used when | a key has been saved with DATABENTO_SETUP.bat | no Databento key |
| Hosted website | not used (see Licensing) | yes |

Setup for Databento: [DATABENTO_SETUP.md](DATABENTO_SETUP.md).

## Databento details (`gexsys/providers/databento.py`)

Dataset `GLBX.MDP3`, through Databento's documented HTTP API (no extra Python packages). Each
refresh makes a few small requests; reference data is cached:

| Data | Databento schema | How often |
|---|---|---|
| Every listed option series: quarterly (`ES`/`NQ`), end-of-month (`EW`/`QNE`), Friday weeklies (`EW1-4`/`QN1-4`), Monday-Thursday dailies (`E1A-E5D`/`Q1A-Q5D`) | `definition` (parent symbology) | once per day |
| Open interest (stat 9) and settlement prices (stat 3) | `statistics` | every 2 hours |
| Bid/ask of the futures and of every option with open interest | `bbo-1m`, last 10 minutes | every refresh |
| Today's volume per option, since the 18:00 ET session open | `ohlcv-1h` | every refresh |

* **Why the product list matters:** `ES.OPT` alone is only the quarterly options. Most short-dated
  open interest is in the weeklies and dailies, which CME lists as separate products. A product code
  that doesn't exist is skipped and named in the website's warnings.
* **IV:** from the option's live mid when it has a fresh two-sided quote (spread no wider than 25% of
  mid), else from CME's settlement price against the future's settlement. Gamma is then computed at
  the live futures price.
* **Different futures months:** options on another contract (for example ESZ6 options while the
  chart has rolled to ESH7) are shifted by the calendar spread, so every level is in the chart
  contract's prices.
* **Window:** strikes within ±8% of the future and expirations within 45 days (configurable:
  `"provider": {"name": "databento", "strike_window": 0.08, "max_contracts": 8000}`).
* **Open-interest handling:** deleted statistics and Databento's "not set" values are ignored; the
  newest session's figure wins.
* **Multiplier:** $50 per point for ES options, $20 for NQ, from the contract specs (Databento's
  `contract_multiplier` is not a dollar multiplier).
* **Tested** against canned responses in Databento's CSV layout (`tests/test_databento.py`). **Not
  yet run against a live Databento account.**

## Cboe details (`gexsys/providers/cboe.py`, verified live 2026-10-21)

| | Cboe delayed-quotes JSON |
|---|---|
| Endpoint | `cdn.cboe.com/api/global/delayed_quotes/options/{_SPX,_NDX,SPY,QQQ}.json` |
| Requests | 1 per refresh (the whole chain) |
| Open interest | yes (end of day) |
| IV / Greeks | IV plus Greeks; gamma is rounded to 4 decimals, so it is recomputed from IV |
| Delay | 15 min |
| Terms | unofficial website feed, personal use |

## Other sources considered (2026-10-23)

| Source | Futures options | Price / month | Why not built |
|---|---|---|---|
| ThetaData | no (US equity/index options) | $40-160 | index options only |
| Massive (Polygon) | no | $29-199 | index options only |
| Interactive Brokers | yes | data fees + funded account | heavy API, account needed |
| tastytrade | yes (streaming) | free with account | real-time status for API users unconfirmed |
| Tradier, Schwab | no / – | – | built earlier, then removed at your request |

## CSV adapter (any other vendor)

Required columns: `root,type,strike,expiration,multiplier,open_interest`.
Optional columns: `symbol, expiration_time (ISO with offset), bid, ask, last, quote_time, iv, gamma, delta, volume, underlying_price, underlying_time`.
Multipliers: 50 for ES options, 20 for NQ, 5 and 2 for the micros. Timestamps need a timezone offset.
`tests/data/es_fop_sample.csv` is **hand-made test data**, not market data.

## Licensing

* Databento's CME data is licensed for your own use. Showing it, or levels built from it, on a
  public website can count as redistribution, so **the hosted GitHub site stays on Cboe**. Your
  local website (START.bat, only visible on your PC) uses Databento.
* `storage.store_raw` defaults to `false`, so only derived numbers are written to disk.
