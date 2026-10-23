# TradingView setup and validation

> **Not compiled here.** There is no automated access to the TradingView compiler from this build
> environment. `pine/nq_es_gex_levels.pine` was written for Pine v6 and reviewed by hand. Run the
> checklist below before you rely on it.

## Install

1. Open TradingView and load an NQ, MNQ, ES or MES chart. Continuous contracts such as
   `CME_MINI:NQ1!` work, and so do specific months such as `CME_MINI:NQZ2026`.
2. Open **Pine Editor**, choose **New → Indicator**, and replace the contents with
   `pine/nq_es_gex_levels.pine`.
3. **Save**, then **Add to chart**.
4. Get a payload, either:
   - `python -m gexsys snapshot --config configs/nq_ndx_tradier.json` (last block of the output), or
   - `http://127.0.0.1:8765/api/pine?market=NQ` while the service runs.
5. In the indicator settings, paste the whole `GEX1;...` line into **Levels payload**.

## Mapping modes

| Mode | Use when | Behaviour |
|---|---|---|
| Live reference (default) | NDX/SPX/QQQ/SPY sources | Reads `tv=` from the payload (for example `NASDAQ:NDX`) through `request.security`. Ratio = chart close / reference close on bars where both trade. Outside cash hours the last factor is **held**, and the dashboard says so. |
| Snapshot factor | Service had a futures price | Uses `fac`/`off` from the payload. If the service had no futures reference, the dashboard shows UNAVAILABLE. |
| None | Chart is the options underlying itself | Draws raw strikes. |

Futures-options payloads (`map=identity`) are drawn as-is.

The chart needs data for the reference symbol. Index data (NDX, SPX) and real-time CME data may
need TradingView exchange add-ons. Without them, quotes are delayed.

## What you will see

### Settings

Everything is on the **Inputs** tab, in eight numbered groups. Each level is **one clean row: an
on/off switch and a colour swatch**. Line thickness and dash style are fixed per level type:
- key levels 2 px;
- zero gamma dashed;
- walls solid;
- ±GEX, OI walls and max pain dotted;
- volume walls and expected move dashed.

The dialog's separate Style tab has nothing to change.

| Group | Contents |
|---|---|
| 1 - Data | Levels payload, price mapping |
| 2 - Key levels | Zero gamma, call wall, put wall, absolute gamma (on/off + colour each), largest ±GEX and concentrations (on/off), extra concentrations (count, min %) |
| 3 - More levels | 0DTE levels (on/off), volume walls, OI walls, max pain, expected move (on/off + colour each), max-pain expirations, expected-move range |
| 4 - Lines & labels | Where lines start (session open / full chart / right of price), labels (short / full / off), label size, label background, label offset, expected-move band shading, session tint by gamma side |
| 5 - GEX profile | On/off, source, width, gap, opacity |
| 6 - Info panel | On/off, detail, position, text size |
| 7 - Alerts | Approach (ticks), wall cross, zero-gamma cross, stale update, cooldown |
| 8 - Advanced | More levels from, source filter, reference override, stale time, safety distance, manual levels |

### On the chart

* **Lines** start at the session open by default and extend right. Key levels and max pain are 2 px,
  others 1 px.
* **Labels** sit right of the GEX profile on a dark pill: short code plus price with separators,
  e.g. `CW  29,883.25`. Codes: `ZG`, `CW`, `PW`, `+GEX`, `-GEX`, `+G 12%`, `0D ZG` / `0D CW` / `0D PW`,
  `VOL C` / `VOL P`, `OI C` / `OI P`, `MP 10-21`, `EM day +` / `EM day -`, `EM wk +` / `EM wk -`.
  "Full" spells them out.
* **Shared prices:** levels at the same price share one line, e.g. `CW · +GEX  29,883.25`.
* **Source names** appear in labels only when two sources are drawn. `STALE` is added once the update
  is older than the stale time.
* **Safety:** a level more than "Ignore levels farther than" from price is skipped, not drawn.
* **GEX profile**: boxes right of the last bar, one per price bin. Positive exposure extends right of
  the centre line, negative extends left.
* **Info panel** (top right by default): one column per source, headed with the source and its options
  (e.g. `CBOE NDX`). Settings under **6 - Info panel**:
  - **Show panel**: off hides it completely; the levels stay on the chart.
  - **Detail**:
    - **Minimal:** regime, zero gamma, data.
    - **Compact** (the default): adds the call and put walls.
    - **Full:** adds net GEX, hedging per 1% (in contracts of your chart), charm flow per day, absolute
      gamma, ±GEX strikes, 0DTE levels, volume walls, max pain, expected move and mapping.

    The zero-gamma row also shows its distance in daily expected moves, e.g. `(0.2σ)`.
  - **Position** and **Text size**.

  Level rows show the price and its distance from the last close in points (`29883.25  +186`).
  The **Data** row reads like `DL 12m`: delayed quotes, snapshot 12 minutes old. It adds **STALE**
  when old, and **CUT OFF** when a payload lacks its `END` marker (TradingView shortened the paste;
  use the website's per-market copy button).
* Nothing is drawn, and the panel says **BLOCKED**, if:
  - the payload belongs to another market (an ES payload on an NQ chart), or
  - any mapped level is more than 8% from price, which almost always means the mapping is wrong.

## Repainting and execution model

* GEX levels are drawn on the last bar only, as horizontal lines. They are not plotted
  historically, because the snapshot says nothing about past bars. There is no history to repaint.
* The live mapping factor uses `request.security(..., lookahead_off, gaps_on)` on the chart
  timeframe. On the real-time bar the factor updates intrabar.
* The indicator draws options levels only. It has no price-action or ICT tools.

## Alerts

* Create an alert on the indicator and choose **"Any alert() function call"**. That gives the
  approach, wall-cross, zero-gamma-cross and stale-snapshot alerts, each with a per-type cooldown,
  on real-time bars only.
* Two `alertcondition`s are also available: zero-gamma cross and wall cross.
* Webhooks: TradingView can POST alert messages to a URL on plans that support it. **Alerts can be
  delayed, missed, duplicated, or triggered by changing conditions. They are informational and
  place no orders.**
* Level-shift and regime-change alerts between snapshots come from the **service**: a log line,
  plus a POST to `GEX_ALERT_WEBHOOK_URL` if you set one.

## Manual validation checklist

Record pass/fail for each item:

1. The script compiles in the Pine Editor with no errors. Note any warnings.
2. With an empty payload, the panel shows "no payload" and no lines are drawn. Turning off "Show info
   panel" hides the panel completely.
3. Paste the output of `python -m gexsys demo --market NQ` onto an NQ1! chart:
   - the Data row starts with "SYN";
   - lines are drawn (or BLOCKED appears if the synthetic prices sit more than 8% from the real NQ
     price; raise "Reject mapped levels farther than" to test the drawing itself);
   - the label prices equal payload price × mapping factor, rounded to 0.25.
4. Paste an NQ payload on an ES chart. Expect BLOCKED and no lines.
5. Switch Mapping to "Snapshot factor" with a payload that has `fac=0`. Expect the Mapping row (Detail: Full) to
   read UNAVAILABLE and no lines.
6. Watch the mapping row cross 09:30 and 16:00 ET. It should read `live …` in RTH and `held …`
   outside RTH.
7. Lines and labels stay ≤ 20 when all modules are on. Check the object count in the Pine logs or
   by eye.
8. Change the timeframe (1m, 5m, 1h). The levels stay the same and the factor stays consistent.
9. Run Bar Replay. The GEX lines show only on the latest replayed bar.
10. Set alerts and let a real-time approach or cross happen. Exactly one alert fires per cooldown
    window.
11. Set "Snapshot stale after" to 1 minute. Labels gain `[STALE]` and the stale alert fires.
12. Check MNQ and MES charts. Tick distances use a 0.25 tick.
