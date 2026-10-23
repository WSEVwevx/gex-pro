# GEX PRO: NQ / ES options gamma-exposure levels for TradingView

An analytical system that turns options chains (SPX/SPY, NDX/QQQ, or CME ES/NQ futures options)
into **modeled** gamma-exposure (GEX) levels for NQ/MNQ and ES/MES traders. It does not trade and
does not predict.

```
provider ─► normalize ─► GEX engine ─► levels ─► futures mapping ─► { local dashboard, Pine payload, alerts }
```

TradingView can't call external APIs, and Pine Seeds is closed to new repositories (see
[ADR-001](docs/ADR-001-architecture.md)). So:

* the **service** computes everything and serves a live local **dashboard**;
* the **Pine v6 indicator** draws the levels from a text **payload** you paste in. It maps them to
  the futures chart live and shows how fresh the data is.

## Everyday use

**Double-click `START.bat`.** It starts the service with free Cboe data (SPX + SPY options for ES, NDX + QQQ
options for NQ) and opens the website at http://127.0.0.1:8765. See [Daily use](docs/REALTIME_SETUP.md).

## Developer quick start (Windows PowerShell; macOS/Linux are the same with `python3`)

```bash
pip install -r requirements.txt
```

```bash
python -m unittest discover -s tests -t .
```

```bash
python -m gexsys demo --market NQ
```

```bash
python -m gexsys serve --config configs/nq_demo_synthetic.json --config configs/es_demo_synthetic.json
```

Then open http://127.0.0.1:8765. The demo data is **SYNTHETIC** and labeled as such everywhere.

With real data (see [DATA_PROVIDERS](docs/DATA_PROVIDERS.md)):

```bash
python -m gexsys snapshot --config configs/free_es_cboe.json
```

```bash
python -m gexsys serve --auto
```

Other commands: `replay --market NQ` (level-stability statistics over stored snapshots) and
`sensitivity --config <cfg>` (levels under every dealer-positioning model).

## TradingView

1. Add the **GEX PRO** indicator: the website's **Indicator** page always has the current code (Copy
   code, or Download .pine), with install steps. It reads `pine/nq_es_gex_levels.pine` directly, so every
   edit to the script shows up there.
2. Paste the `GEX1;…` payload from `snapshot` or from `/api/pine?market=NQ`.

Details, the repainting notes and the **manual validation checklist** (the script has not been
compiled in TradingView yet) are in [TRADINGVIEW_SETUP](docs/TRADINGVIEW_SETUP.md).

## Configurations

| File | Market | Options source | Notes |
|---|---|---|---|
| `configs/free_nq_cboe.json` | NQ/MNQ | NDX + QQQ via Cboe free feed | **used by START.bat** and the hosted site |
| `configs/free_es_cboe.json` | ES/MES | SPX + SPY via Cboe free feed | **used by START.bat** and the hosted site |
| `configs/es_fop_csv.json` | ES/MES | ES futures options (CSV) | identity mapping; points at the hand-made sample file |
| `configs/*_demo_synthetic.json` | NQ / ES | synthetic | demo only |

Unknown or misspelled config keys are rejected. Invalid combinations are rejected too, for example
QQQ with `offset` mapping, `include_etf` on an ETF source, or SPX options for NQ.

## Conventions in one paragraph

GEX = sign × OI × Γ × multiplier × S² × 0.01: dollars of modeled dealer delta change per 1%
move. Units `usd_per_point` and `delta_per_point` are also available.

The default sign is the *conventional approximation*: dealers long calls, short puts. That is an
assumption, not observed positioning.

Zero gamma is estimated by re-pricing every contract's gamma over a ±5% price grid (sticky-strike)
and taking the sign change nearest the reference price. It is reported only if a crossing exists.

Walls are the strikes with the largest call-side and put-side gamma exposure.

Full details: [METHODOLOGY](docs/METHODOLOGY.md). Caveats: [LIMITATIONS](docs/LIMITATIONS.md).

## Website

* **Levels:**
  - regime, price and net-GEX cards;
  - market stats: put/call OI and volume, ATM IV, nearest-expiration share, changes since the last update;
  - a level ladder with explanations;
  - a GEX-by-price chart;
  - max pain and gamma by expiration.
* **Indicator:** the GEX PRO TradingView script, always the current version, with Copy / Download
  buttons, install steps, version and last-updated time, and the script's recent changes.
* **Bias:** a transparent, rule-based reading of today's positioning:
  - bias and confidence, day type (range / trend / pivot), base case and expected range;
  - a session chart with an illustrative path, ±1σ cone and key levels;
  - a factor-by-factor table showing why. A scenario, not a prediction.
* **News:** this week's economic calendar from ForexFactory's export feed (impact, forecast,
  previous; times in ET), with a header countdown to the next high- or medium-impact USD event.
  Beside it, a feed of Donald Trump's recent Truth Social posts. It comes from Truth Social's
  public API, falls back to the trumpstruth.org archive, and is checked every 5 minutes. Posts
  about market topics (tariffs, the Fed, China, oil, ...) are tagged and highlighted, and a
  "Market-related" filter shows only those.

**Hosted copy:** the same website can run for free on GitHub Pages, updated by GitHub every ~15 minutes in market hours and every hour otherwise
in market hours with Cboe delayed data, so you can open it on any device without your PC
(`python -m gexsys build-site`, `.github/workflows/website.yml`). Setup: [docs/HOSTING.md](docs/HOSTING.md).

Only one copy of the service can run at a time. If START.bat is already open, a second copy
prints "GEX PRO is ALREADY RUNNING" and exits. To pick up updates, close the old window first.

## Scheduled updates (every hour)

The service publishes a TradingView payload every hour on the hour, around the clock (00:00 to
23:00 ET) on trading days; weekends and market holidays have none. It sends a
Windows notification (and an optional Discord/webhook message), and the dashboard's **Copy** button
puts the payload on your clipboard. See [REALTIME_SETUP](docs/REALTIME_SETUP.md).

## Documentation

- [Daily use: free data and hourly updates](docs/REALTIME_SETUP.md)

- [Architecture decision record](docs/ADR-001-architecture.md)
- [Mathematical methodology](docs/METHODOLOGY.md)
- [Data-provider setup](docs/DATA_PROVIDERS.md)
- [TradingView setup and validation](docs/TRADINGVIEW_SETUP.md)
- [Data quality and limitations](docs/LIMITATIONS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Feature status: what works and what is unverified](docs/STATUS.md)

## Layout

```
gexsys/            models, pricing, engine, levels, mapping, marketcal, normalize,
                   providers/{base,cboe,csvfile,synthetic}, pipeline, storage, alerts,
                   export (Pine payload), service (HTTP), replay, config, __main__ (CLI)
pine/              TradingView Pine v6 indicator
dashboard/         local dashboard (no external network calls)
configs/           NQ / ES example configurations
tests/             unit + integration tests, tests/data synthetic fixtures
docs/              documentation
```

*Not investment advice. Options-positioning models are uncertain. Alerts can be delayed, missed or
duplicated.*
