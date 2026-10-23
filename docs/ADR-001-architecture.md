# ADR-001: Architecture for NQ/ES options-positioning levels on TradingView

> **Update 2026-10-23:** the Tradier, Schwab and Databento adapters were removed (free data only). Live data comes from Cboe's free feed: SPX + SPY options for ES, NDX + QQQ for NQ. See DATA_PROVIDERS.md. The rest of this record is kept as the original decision.

Status: accepted (2026-10-20)

## Context

The goal is GEX-derived levels for NQ/MNQ and ES/MES, shown in TradingView, computed from real
options chains (NDX/QQQ, SPX/SPY, or CME futures options).

Facts checked against documentation while writing this ADR:

| Question | Finding | Source |
|---|---|---|
| Current Pine version | Pine Script v6 (released Dec 2024). New features land only in v6. | tradingview.com/blog "Pine Script v6 has landed" |
| Can Pine make HTTP requests? | No. Pine has no general-purpose network access. | Pine docs (`request.*` lists only TradingView data sources) |
| Pine Seeds / `request.seed()` | The function still exists, but **new Pine Seeds repositories are suspended**. Pine Seeds was also end-of-day only. | github.com/tradingview-pine-seeds/docs |
| Can a webhook push data into an indicator? | No. Webhooks go *out* of TradingView (alerts); nothing pushes into a running Pine script. | Pine/alerts docs |
| Tradier chain fields | `/v1/markets/options/chains?greeks=true` returns bid/ask, last, volume, `open_interest`, `contract_size`, `root_symbol`, and a `greeks` object (delta, gamma, …, `mid_iv`, `smv_vol`, `updated_at`) "courtesy of ORATS". Real-time vs delayed is not stated in the response. | docs.tradier.com (Get Options Chains) |
| CME futures options OI | Published as the prior day's value. Databento exposes OI via its `statistics` schema. | cmegroup.com, databento.com |

## Options considered

1. **Pine-only.** Pine can't see option chains, so it can't compute GEX. Rejected.
2. **Pine Seeds feed.** Closed to new repos, EOD only. Rejected.
3. **External service, plus a payload pasted into a Pine input, plus a local dashboard.** Feasible
   with documented features only. **Selected.**
4. **Replace TradingView with a self-hosted chart (TradingView Lightweight Charts, etc.).** This
   gives full live integration but drops the user's TradingView workflow. Partially adopted: the
   local dashboard is the live view, and TradingView stays the execution chart.
5. **Broker platforms with custom-data APIs (Sierra Chart, NinjaTrader, MotiveWave).** These are
   viable later. They are outside the "TradingView" requirement.

## Decision

```
 provider (Tradier | CSV export | synthetic)
        │  rate-limited, retried, quality-tagged
        ▼
 normalize ──► engine (BSM/Black-76, GEX, profile, zero gamma) ──► levels ──► mapping (ratio/offset/identity)
        │                                                                     │
        ▼                                                                     ▼
 snapshot store (derived JSON)  ◄── diff / alerts (log + optional webhook)   Pine payload (text)
        │                                                                     │
        ▼                                                                     ▼
 local HTTP service: /health /api/levels /api/pine  + dashboard     TradingView indicator (pasted)
```

* **Engine:** Python 3.12, stdlib only. The single runtime dependency is `tzdata`, because Windows
  ships no tz database. This keeps the math auditable and the install trivial.
* **TradingView bridge:** a compact `GEX1;key=value;…` text payload pasted into an
  `input.text_area`. Level prices travel in **options-underlying space**. Pine maps them live by
  reading the reference symbol (`NASDAQ:NDX`, `SP:SPX`, `NASDAQ:QQQ`, `AMEX:SPY`) through
  `request.security`. While the cash index is closed, Pine holds the last factor from bars where
  both instruments traded.
* **Live view:** a local dashboard (no CDN, no external calls) that refreshes from the service every 15 s.
* **Default provider:** Tradier, for SPX/NDX/SPY/QQQ chains with vendor Greeks and OI in one call.
  ES/NQ futures options come in through the CSV adapter (Databento / CME DataMine / broker exports),
  because no inexpensive documented REST source of CME options *with* OI was verified.

## Consequences

* TradingView levels update only when the user pastes a new payload. They are a snapshot, and the
  indicator shows how old it is and marks it STALE.
* Recalculation-shift and regime-change alerts come from the service, because Pine never sees two
  snapshots.
* Operating costs: a market-data subscription (Tradier production access needs a brokerage account,
  and index options may need extra entitlements). TradingView real-time CME data for NQ/ES charts is
  a separate subscription. Otherwise the chart data is delayed. The service is free to run locally.
* No raw quotes are redistributed. Only derived summaries are stored by default.
