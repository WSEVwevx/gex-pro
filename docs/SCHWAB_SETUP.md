# Schwab setup (real-time options data, free with a Schwab account)

Once set up, START.bat uses Schwab automatically.
- **Options chains** for SPX/NDX come from Schwab instead of Cboe's 15-minute-delayed feed.
- **Live /ES and /NQ quotes** let the website show true futures prices.
- **If the Schwab login lapses** (every 7 days) or Schwab is down, the levels keep coming from Cboe,
  labeled "CBOE (fallback)", and you get a Windows notification.

> **Not yet verified with a live account.** The adapter was built from Schwab's documented API
> (endpoints and login flow taken from the schwab-py library) and tested against sample responses.
> Do the first-run check below and send any error text back so it can be fixed.

## 1. Create a Schwab developer app (one time, a few days for approval)

1. You need a Schwab **brokerage** account.
2. Go to **developer.schwab.com** and sign up with the same login.
3. **Dashboard → Create App**:
   - API product: **Accounts and Trading Production** and **Market Data Production**. Market Data
     is the one this tool uses.
   - **Callback URL:** `https://127.0.0.1:8182`. It must match exactly; changing it later means
     another approval.
4. Wait for the status to change to **Ready For Use**. Schwab says this can take a few days.
5. Open the app and note its **App Key** and **Secret**.

Real-time quotes depend on your account's market-data agreements. If Schwab reports delayed data,
the website and indicator say "delayed".

## 2. Log in (first time, then every 7 days)

1. Double-click **SCHWAB_LOGIN.bat** in the Options Indicator folder.
2. The first time, it asks for your App Key and Secret (the secret is typed hidden). They are saved
   in `%LOCALAPPDATA%\gexsys\.env` on this PC only, **not** in the OneDrive folder.
3. Your browser opens Schwab's login. Log in and approve.
4. Schwab sends the browser to `https://127.0.0.1:8182/?code=...`. **That page won't load; this is
   expected.** Copy the whole address from the address bar, paste it into the black window, and
   press Enter.
5. You'll see "Logged in". Restart **START.bat**.

The login token is saved in `%LOCALAPPDATA%\gexsys\schwab_token.json` and refreshes itself every
30 minutes. Schwab allows a login to last **7 days**. After that, run SCHWAB_LOGIN.bat again; the
website shows how many days are left.

## 3. First-run check

1. Start **START.bat**. The black window should say `Data: Schwab ... login valid N more days`.
2. On the website (http://127.0.0.1:8765), the top chips should read **Data SCHWAB** and, during
   market hours, **Options real time**.
3. During market hours, the footer's futures-price note should say `Schwab quotes /ES... (live, time-matched)`.
4. If you see **Data CBOE (fallback)** instead, the banner explains why. Copy that text and send it.

## How it works

| What | Schwab endpoint |
|---|---|
| Option chain | `GET https://api.schwabapi.com/marketdata/v1/chains?symbol=$SPX&contractType=ALL&strikeCount=200&includeUnderlyingQuote=true&strategy=SINGLE&fromDate=…&toDate=…` (NDX: `$NDX`) |
| Futures + index quotes | `GET https://api.schwabapi.com/marketdata/v1/quotes?symbols=/ES,$SPX` (NQ: `/NQ,$NDX`) |
| Login | `https://api.schwabapi.com/v1/oauth/authorize` → `https://api.schwabapi.com/v1/oauth/token` |

* `strikeCount=200` asks for 200 strikes around the money per expiration, which covers the ±5%
  zone the levels use.
* The futures basis uses /ES (or /NQ) and the cash index from one quote request. It's used only when
  their trade times are within 60 seconds of each other; otherwise (cash index closed) the carry
  model is used.
* Refresh: every 60 seconds during market hours. The ~2-hour TradingView paste schedule is unchanged.
* Level math is identical to the Cboe path: gamma is recomputed from Schwab's implied volatility,
  so both sources are computed the same way.

## Troubleshooting

| Message | Fix |
|---|---|
| `SCHWAB_APP_KEY / SCHWAB_APP_SECRET are not set` | Run SCHWAB_LOGIN.bat; it asks for them. |
| `Schwab token request rejected (HTTP 400/401)` | Wrong key/secret, callback URL not exactly `https://127.0.0.1:8182`, app not yet "Ready For Use", or the pasted address was old. Run SCHWAB_LOGIN.bat again. To re-enter the key/secret, delete `%LOCALAPPDATA%\gexsys\.env` first. |
| `7-day login expired` | Run SCHWAB_LOGIN.bat, then restart START.bat. |
| `no ?code= in that URL` | Copy the **whole** address after logging in, starting with `https://127.0.0.1:8182/?code=`. |
| Website shows "Options 15-min delayed" with Schwab | Your account lacks real-time entitlements, or Schwab didn't say. Check Schwab's market-data agreements. |
