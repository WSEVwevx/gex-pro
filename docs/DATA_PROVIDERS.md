# Data-provider setup guide

## Default: Cboe free delayed feed (verified against live responses 2026-10-21)

| | Cboe delayed-quotes JSON |
|---|---|
| Endpoint | `cdn.cboe.com/api/global/delayed_quotes/options/{_SPX,_NDX,SPY,QQQ}.json` |
| Requests | 1 per refresh (the whole chain) |
| Open interest | yes (end of day) |
| IV / Greeks | IV plus Greeks; gamma is rounded to 4 decimals, so it is recomputed from IV |
| Delay | 15 min |
| Terms | unofficial website feed, personal use |
| Cost | free, no key, no signup |

### Why Cboe (search of free sources, 2026-10-21)

| Source | SPX / NDX | Open interest | IV / Greeks | Real time | Catch |
|---|---|---|---|---|---|
| **Cboe delayed feed** | yes | yes | yes | no (15 min) | unofficial endpoint |
| Yahoo Finance (removed) | yes | SPX OI missing near the money; all OI blanked overnight | IV only | no | unreliable for GEX |
| FlashAlpha free tier | not stated (stocks/ETFs) | yes | yes | not stated | index options not confirmed |
| Eulerpool free tier | not stated | yes | yes | paid tiers only | index options not confirmed |
| Tradier sandbox | yes | yes | yes (ORATS) | no | needs signup; same delay as Cboe |
| TrendSpider | yes | yes | yes | yes | needs a paid OPRA subscription |

### Upgrade path: real-time for free with a brokerage account

Tradier's production API (with a Tradier brokerage account) gives real-time chains, and its adapter
already exists (`configs/*_tradier.json`). A Schwab adapter was built earlier and then removed
(2026-10-23) after API access was denied.

The rest of this document covers keyed and paid options.

## Provider comparison

Only the Tradier chain endpoint was checked against its current documentation for this build. The
other rows reflect general knowledge of each vendor's published offering. **Check current
documentation, licensing and pricing before you subscribe.** Nothing here has been checked against
live responses.

| Provider | SPX/SPY | NDX/QQQ | ES/NQ futures options | Greeks/IV | OI | Real-time | Built-in adapter |
|---|---|---|---|---|---|---|---|
| **Tradier** | yes (SPX/SPXW via `includeAllRoots`)¹ | yes¹ | no | yes (ORATS) | yes (EOD) | depends on account/entitlement; sandbox delayed | **yes** |
| Polygon.io / Massive | yes | yes (indices on separate plans) | no | yes (snapshot) | yes | paid tiers | no (add a `Provider` subclass) |
| ThetaData | yes | yes | no | yes | yes | paid tiers; local terminal process | no |
| Databento | OPRA raw | OPRA raw | **yes (GLBX.MDP3)** | no (compute from quotes) | yes (`statistics` schema) | yes (licensed) | via **CSV adapter** |
| CME DataMine | – | – | yes (historical/EOD) | settlement-based | yes | no | via CSV |
| Interactive Brokers API | yes | yes | yes | model Greeks | yes | with subscriptions | no |

¹ Index-option availability and entitlements on Tradier are not stated on the chain page. Confirm
with Tradier for your account type.

**Default choice: Tradier.** It provides SPX/NDX/SPY/QQQ chains with OI and vendor Greeks in one
documented REST call, at modest cost for retail accounts. For **ES/NQ futures options**, which are
the preferred source for futures-specific exposure, export a licensed feed (for example Databento:
`definition` for strikes and expirations, `statistics` for OI, `mbp-1` or `bbo` for quotes) into
the CSV schema below. The engine computes Black-76 Greeks from IV or from mid prices.

## Tradier

1. Open a Tradier account (production market data needs one) or a developer sandbox (15-minute
   delayed).
2. Create an API access token in the Tradier dashboard.
3. Copy `.env.example` to `.env` and set:
   ```
   TRADIER_TOKEN=your-token
   TRADIER_BASE_URL=https://api.tradier.com/v1      # or https://sandbox.tradier.com/v1
   TRADIER_QUOTE_QUALITY=DL                          # set RT ONLY if your account is entitled to real-time options data
   ```
4. Test the connection:
   ```
   python -m gexsys snapshot --config configs/es_spx_tradier.json
   ```

Data labels applied:
- Quotes get whatever `TRADIER_QUOTE_QUALITY` declares. Sandbox is always DL.
- OI is always `EOD`.
- Greeks are `PROV` with the ORATS `updated_at` timestamp. That timestamp has no timezone, so it is
  interpreted as America/New_York (**unverified assumption**).

Rate limiting: a client-side limiter (default 60 req/min, configurable) plus retry with
exponential backoff, which honours `Retry-After` on HTTP 429. Each refresh makes
1 quote + 1 expirations + N chain requests (N = expirations in the basket). Keep `max_dte` modest.

## CSV adapter (futures options, any other vendor)

Required columns: `root,type,strike,expiration,multiplier,open_interest`.
Optional columns: `symbol, expiration_time (ISO with offset), bid, ask, last, quote_time, iv, gamma, delta, volume, underlying_price, underlying_time`.

* `multiplier`: 50 for ES options, 20 for NQ options. Micro options (MES/MNQ options) use 5 and 2.
* All timestamps need a timezone offset. Rows without one are rejected.
* Declare honest quality labels in the config:
  `"provider": {"name": "csv", "path": "...", "quote_quality": "DL", "greeks_quality": "PROV", "spot_quality": "DL"}`.
* The sample `tests/data/es_fop_sample.csv` is **hand-made test data**, not market data.

## Licensing

* Display of real-time OPRA and CME data is licensed per user and per device. A local, personal
  dashboard is the use case assumed here.
* Don't publish payloads or dashboards built from licensed real-time data without checking your
  vendor and exchange agreements.
* `storage.store_raw` defaults to `false`, so only derived numbers are written to disk.
