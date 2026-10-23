# Databento setup: true NQ/ES futures-options levels

With a Databento key, START.bat builds the levels from **CME options on the NQ and ES futures**
instead of NDX/SPX index options. The levels are then in futures prices directly, with no index
translation.

## 1. Account and plan (about 10 minutes)

1. Sign up at **databento.com**. New accounts get free credit, which covers trying the historical
   data.
2. Subscribe to the **CME** dataset (`GLBX.MDP3`) **Standard** plan. In October 2026 it cost about
   $199/month, with live data and recent history included. Check the current price on Databento's
   pricing page.
3. Databento asks whether you are a professional or non-professional user. Answer honestly; for
   personal trading you are normally non-professional.
4. In the Databento portal, open **API keys** and copy your key. It starts with `db-`.

## 2. Save the key on your PC

1. Double-click **DATABENTO_SETUP.bat** in the Options Indicator folder.
2. Paste the key and press Enter. The typing is hidden.
3. It saves the key in `%LOCALAPPDATA%\gexsys\.env`, outside the OneDrive and GitHub folder, and
   makes one test request. You should see **"Key works."**

## 3. Use it

Close START.bat if it's open and run it again. The terminal says
**"Data: Databento - CME NQ/ES options on futures"**, and the website's top bar shows
**Data DATABENTO** and **Options real time**.

TradingView: paste as usual. The payload now says `src=NQ_FOP` / `src=ES_FOP` and `map=identity`, so
the indicator draws the levels at their own prices on the futures chart.

## What to expect

* **First refresh** of the day downloads that day's option list (a few MB), then refreshes are small.
* **Open interest** is CME's end-of-day figure. CME publishes it once a day, in the morning.
* **Warnings line** on the website shows how many options got IV from live quotes vs settlement
  prices, and any option series that wasn't found.
* **To stop using Databento:** delete the `DATABENTO_API_KEY=` line from `%LOCALAPPDATA%\gexsys\.env`.
  START.bat goes back to the free Cboe data.

## If something goes wrong

| Message | Meaning |
|---|---|
| `DATABENTO_API_KEY is not set` | Run DATABENTO_SETUP.bat. |
| `Databento HTTP 401/403` | Key wrong, revoked, or the CME plan isn't active. |
| `newest available data is from ...` | Your plan doesn't include today's data, so the levels use older prices. |
| `option series not found and skipped` | CME doesn't list one of the product codes right now. Harmless unless it's every weekly. |
| `no price for ESZ6` | No quote or settlement for the front future yet, e.g. a holiday. |

The website keeps the last good levels while any error lasts.
