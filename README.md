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

Every check at once (tests, lint, pricing, independent math, live audit, hosted data; `--quick` skips the live ones):

```bash
python tools/check.py
```

```bash
python -m gexsys demo --market NQ
```

```bash
python -m gexpro serve --config configs/nq_demo_synthetic.json --config configs/es_demo_synthetic.json
```

Then open http://127.0.0.1:8765. The demo data is **SYNTHETIC** and labeled as such everywhere.

With real data (see [DATA_PROVIDERS](docs/DATA_PROVIDERS.md)):

```bash
python -m gexsys snapshot --config configs/free_es_cboe.json
```

```bash
python -m gexpro serve --auto
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

A terminal-style workspace: a command line (type `LIVE`, `TRK`, `NQ`, `ES`, `COPY`, `LIGHT`, `HELP` and press
Enter, or press `/`), a ticker strip with both markets, a sidebar of pages (keys `1`-`8`), and an **Explain**
panel (the `?` on every module, the Explain button in the top bar, or `X`) that says in plain English
what each module shows and what to watch, with the live numbers for the current market. The screen stays
clean by default; **Notes** in the sidebar (or `D`) adds a one-line note under each number. A sun/moon button in the top
bar (or `T`, or the `LIGHT` / `DARK` commands) switches between night and light mode; the choice is saved in
your browser, and the first visit follows your system setting.

* **Market tape:** a scrolling strip across the top with real quotes for ES, NQ, SPX, NDX, Dow, Russell,
  VIX, the dollar index, the 10-year yield, gold, oil, BTC, ETH, SOL, NVDA, AAPL, MSFT and TSLA: price
  and change from the previous close (Yahoo Finance's public data; exchange prices delayed). Hover to
  pause; hover a quote for its time.
* **Heatmap:** NQ or ES futures candles (1, 5 or 15 minutes; Yahoo Finance, delayed) drawn with
  TradingView's free Lightweight Charts library, with GEX history painted underneath: one column per
  saved snapshot, each cell the net dealer gamma in that price band (blue positive, orange negative,
  brighter = more), plus zero gamma and the walls as step lines. Hover for the numbers; a slider sets
  the heat strength. History grows as snapshots are saved (about 12 days in the app, 5 hosted).
* **Live table:** a strike ladder like a trader's GEX matrix: net DEX, net GEX, net OI and net volume
  for every strike near price, in futures prices, with level chips (C1-C5, P1-P5, Ab1-Ab3, zero gamma,
  walls, expected move), the price row highlighted and a hover readout. An expiry strip on top picks
  which expirations it adds up (the nearest, every Friday, every monthly, then the rest pooled); a side
  panel shows net GEX and DEX for that pick, the key levels with distances, and put/call activity.
* **Track record:** every session's plan (the levels from the last calculation timestamped before the
  09:30 ET open, frozen once) graded after the close against the index's open, high, low and close:
  expected-move hit rate, walls held when touched, zero-gamma crosses, bias calls against a baseline,
  range by gamma regime, each with a 95% range. Missed sessions are listed. The hosted site commits every
  plan and grade to the public `track-record` branch,
  where `history.csv` holds every session ever graded (kept forever; the local app syncs its copy from it). Plus a **historical backtest** of the expected-move
  band from VIX (S&P 500, since 1990) and VXN (Nasdaq-100, since 2009): by year, by vol level, and the
  distribution of daily moves against a normal curve. Hypothetical, not trading results.
* **Library:** a beginner course in 19 short lessons (options basics, dealers and the Greeks, GEX levels,
  volatility, using GEX PRO), each with an example, diagrams, a link into the terminal and a quick check;
  an A-Z glossary; search; progress saved in your browser. Every Explain panel links to its lesson.
* **Levels:**
  - regime, price and net-GEX cards;
  - market stats: put/call OI and volume, ATM IV, nearest-expiration share, changes since the last update;
  - a level ladder with explanations;
  - a GEX-by-price chart;
  - max pain and gamma by expiration.
* **Briefings** (the local app also copies in the ones the hosted site wrote while your PC was off): a NY AM briefing at 9:00 AM ET on trading days and an Asia session briefing at 7:00 PM ET
  the evening before each trading day: both markets' regime, levels, expected range, bias and game plan, the
  relevant calendar (overnight Asia/Europe events for the Asia one) and market-moving posts. A Windows
  notification when each is written; a missed one is written late when the app starts.
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
(`python -m gexpro build-site`, `.github/workflows/website.yml`). Setup: [docs/HOSTING.md](docs/HOSTING.md).

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
- [Architecture: packages, components, adding features](docs/ARCHITECTURE.md)

## Layout

Four independent packages; only the app shell joins them (a test enforces it). How to add a
feature: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```
gexpro/            app shell: website server, hosted-site build, `python -m gexpro serve` (START.bat),
                   context (what briefings and the track record read from gex + feeds)
gexsys/            GEX only: providers/{base,cboe,csvfile,synthetic}, pricing, engine, levels, extras,
                   mapping, marketcal, pipeline, storage, alerts, publish (hourly paste), export (Pine
                   payload), bias, indicator (script info), service (market workers), component
                   (its website endpoints), audit, replay, config, __main__ (GEX tools CLI)
feeds/             market news: forexfactory (calendar), truthsocial (posts), component
briefings/         NY AM and Asia session briefings: schedule, compose (the text), component
trackrecord/       track record and backtest: score (plan + grading rules), prices (free history), backtest, component
dashboard/         the website (one page; reads each component's endpoints)
pine/              TradingView Pine v6 indicator (GEX PRO)
configs/           NQ / ES configurations
tests/             unit + integration tests, tests/data synthetic fixtures
tools/             check.py (all checks), verify_math.py (independent re-derivation), pricing_stress.py
docs/              documentation
```

*Not investment advice. Options-positioning models are uncertain. Alerts can be delayed, missed or
duplicated.*
