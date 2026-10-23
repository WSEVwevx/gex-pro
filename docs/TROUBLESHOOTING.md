# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `python` opens the Microsoft Store | Python isn't installed. Run `winget install Python.Python.3.12 --scope user`, then use the full path or reopen the terminal. |
| `ZoneInfoNotFoundError: America/New_York` | Run `pip install -r requirements.txt`. Windows has no tz database, so `tzdata` is required. |
| `AuthError: DATABENTO_API_KEY is not set` | Run DATABENTO_SETUP.bat (see docs/DATABENTO_SETUP.md). |
| `HTTP 401/403` | The token is wrong, it doesn't match the base URL (sandbox vs production), or the account lacks index-option entitlement. |
| Repeated `HTTP 429` | Lower `provider.requests_per_minute` or `engine.max_dte` (fewer chain calls), or raise `refresh.rth_seconds`. |
| `zero_gamma_status: NO CROSSING` | The modeled profile keeps one sign within ±`grid_pct`. Widen `grid_pct` (for example 0.08), or accept that no flip is modeled nearby. |
| `UNAVAILABLE: only x% of gross GEX has IV` | Vendor IV is missing. Supply IV or bid/ask, or lower `min_profile_coverage` (this reduces reliability). |
| `mapping refused: reference prices …s apart` | The futures and options reference prices are too far apart in time. Pass a fresher `--futures-price`, or let Pine map live. |
| Pine shows `BLOCKED payload is ES / chart is NQ` | You pasted the other market's payload. |
| Pine shows `BLOCKED levels > 8% away` | Wrong mapping mode, for example "None" with an index source, or a synthetic payload on a real chart. |
| Pine mapping shows `UNAVAILABLE (no NASDAQ:NDX data…)` | No TradingView data for the reference symbol. Use "Reference symbol override" (for example `NASDAQ:NDX` → `TVC:NDX`), or "Snapshot factor". |
| Pine mapping shows `held …` | Normal outside cash-index hours. The last RTH factor is in use. |
| Dashboard says `NO DATA` | The service hasn't finished its first calculation yet, or the provider failed. Check `/health` and the logs. |
| Health `stale` | No successful refresh for `alerts.stale_after_s`. Check provider status and credentials. |
| Tests fail on time or DST | Make sure `tzdata` is installed and up to date (pinned version in `requirements.txt`). |
