# Mathematical methodology

All formulas are implemented in `gexsys/engine.py`, `gexsys/pricing.py` and `gexsys/levels.py`,
and tested in `tests/`.

## 1. Notation

| Symbol | Meaning | Unit |
|---|---|---|
| S | options-underlying reference price (index, ETF or futures) | points |
| K | strike | points |
| OIᵢ | open interest of contract i | contracts |
| Γᵢ | gamma: ∂Δ/∂S per one option unit, per 1.0 point | 1/point |
| Mᵢ | multiplier: notional units per point (100 shares for SPX/NDX/SPY/QQQ, $50 for ES options, $20 for NQ options) | units/contract |
| sᵢ | assumed dealer sign (+1 dealer long gamma, −1 dealer short gamma) | – |
| T | time to expiry in years, ACT/365, computed from timezone-aware datetimes | years |

## 2. Exposure per contract

```
baseᵢ = sᵢ · OIᵢ · Γᵢ · Mᵢ                     change in delta (underlying units) per 1.0-point move
GEX_delta_per_point = baseᵢ
GEX_usd_per_point   = baseᵢ · S                change in dollar delta per 1.0-point move
GEX_usd_per_1pct    = baseᵢ · S · S · 0.01     change in dollar delta per 1% move   (default)
```

Defining M as "notional units per point" lets one formula serve both equity-style and futures
options. For futures options, dollar delta = Δ · M · F, so Γ · OI · M · F is the change in dollar
delta per point, which is the same expression.

Units are never mixed. `convert_units()` converts aggregates at a single reference price.

**Hand check** (in `tests/test_engine.py`): one call with OI = 1,000, Γ = 0.002, M = 100, S = 5,000.
- delta/point = 1000 · 0.002 · 100 = 200
- $/point = 200 · 5000 = $1,000,000
- $/1% = 1,000,000 · 50 points = **$50,000,000**

## 3. Positioning assumption (the dominant source of model risk)

Public OI does not show who is long or who is short. Every sign convention is an assumption.

| Model | calls | puts | Interpretation |
|---|---|---|---|
| `conventional` (default) | +1 | −1 | Dealers long call gamma and short put gamma. This is the common public "GEX" convention. |
| `dealer_short_all` | −1 | −1 | Customers net long all options. |
| `dealer_long_all` | +1 | +1 | Customers net short all options. |
| `custom` | ±1 | ±1 | Set explicitly. |

`python -m gexsys sensitivity --config …` re-runs one chain under every model, so you can see how
much the levels depend on this choice. Labels always say "modeled".

## 4. Greeks

* Vendor Greeks are used as supplied and tagged `PROV`, with the vendor timestamp.
* When gamma is missing:
  - if IV is present, gamma comes from the model;
  - if IV is also missing and the quote has a valid bid/ask, IV is solved from the mid by bisection,
    then gamma is computed.
  - Either way the result is tagged `CALC`. Otherwise the contract is excluded and counted.
* Models:
  - **Black-Scholes-Merton** with continuous dividend yield q for SPX/NDX (European):
    `Γ = e^{-qT} φ(d1) / (S σ √T)`
  - **Black-76** for options on futures: the same formula with S = F and q = r.
  - SPY/QQQ are American. BSM gamma is used as an approximation. `crr_american` (a binomial tree)
    quantifies the error, and a test asserts it stays under 5% for near-dated ATM ETF puts. Deep ITM
    American puts and calls near ex-dividend dates can diverge more.
* T has a floor of one minute, so 0DTE gamma stays finite. Expiry reference times are set per
  product:
  - SPX/NDX standard monthlies and ES/NQ quarterly options: 09:30 ET (AM, special opening quotation).
  - Everything else: the close, which is 13:00 ET on early-close days.
* Rates and dividends: `GEX_RISK_FREE_RATE` (default 4%) and `GEX_DIV_YIELD_<SRC>` (default 0).
  These matter for IV solving and recomputed gamma, not for vendor gamma.

Validation: `tests/test_pricing.py` compares analytic gamma against central finite differences of
the price (relative error < 1e-3), checks put-call parity, the IV round trip, and the hand value
Γ(100,100,1y,σ=0.2) = φ(0.1)/20.

### 4a. ETF options in index terms

ES uses SPX and SPY options; NQ uses NDX and QQQ. With r = index price / ETF price, each ETF option
becomes an index-equivalent contract: strike K·r (exact; it is only *grouped* with the nearest listed
index strike when levels, walls and max-pain candidates are built), open interest OI/r, same IV. An ETF
option without a Cboe IV gets one solved from its own bid/ask before conversion (IV is scale-invariant). BSM gamma is homogeneous of degree -1 in (S, K), so
Γ(rS, rK) = Γ(S, K)/r and

  (OI/r) · Γ(rS, rK) · 100 · (rS)² = OI · Γ(S, K) · 100 · S²

The converted contract carries exactly the ETF option's dollar gamma. Vanna and charm are degree 0, and
their exposures use OI·multiplier·S, which is also unchanged.

### 4b. Inputs and missing IV

* Rate and dividend yield: `GEX_RISK_FREE_RATE` (default 4%) and `GEX_DIV_YIELD_<SOURCE>` (defaults
  SPX 1.3%, NDX 0.7%, SPY 1.3%, QQQ 0.6%) are used whenever gamma is recomputed.
* IV order: the vendor's IV; else solved from the bid/ask mid; else the nearest strike's IV in the
  same expiration (counted in the warnings). With `recompute_greeks = "always"` the vendor's own gamma
  is never used: Cboe rounds it to 4 decimals, which overstated deep in-the-money 0DTE gamma by ~40x.

### 4c. Independent check (2026-10-23, live Cboe data)

A separate script recomputed everything from the raw Cboe responses with its own OCC parsing, expiry
times, Black-Scholes gamma, IV solver and zero-gamma search, valuing ETF options in their own prices.
Results vs the engine: net GEX within 0.006% (ES) and 0.002% (NQ); call wall, put wall and absolute-gamma
strike identical; zero gamma within 0.001 points (ES) and 1.2 points (NQ, from QQQ's 0.6% vs NDX's
0.7% dividend yield); futures mapping exact; vanna, charm and max pain identical.

## 5. Aggregation

Exposure is kept per contract and aggregated by strike (call/put/net/abs plus OI), by expiration,
and by DTE bucket (0DTE, 1DTE, 2–7D, 8–30D, 31D+). Totals: net, call, put, gross, and the sums of
positive-net and negative-net strikes.

Gamma density is net exposure per point of local strike spacing, so that strikes on different grid
widths (5-pt vs 25-pt) are comparable.

Different underlyings are never summed. One configuration means one options source.

## 6. Expiration basket

Expirations with T ≤ 0 are always excluded. By default the basket is every expiration with
DTE ≤ `max_dte` (45), including 0DTE. `include_0dte=false` removes the same-day expiry. An explicit
`expirations: ["YYYY-MM-DD", …]` list overrides both.

## 7. Zero gamma (estimate)

The method is sticky-strike re-pricing over a price grid:

1. Grid: P ∈ [S(1−g), S(1+g)], with g = `grid_pct` (default 5%) and `grid_steps` points (default 201).
2. At each P, every contract keeps its IV, T, OI and sign. **Gamma is recomputed** with BSM/Black-76
   at P, and the unit scale uses P. Time does not decay across the grid.
3. Net(P) = Σ sᵢ · OIᵢ · Γᵢ(P) · Mᵢ · scale(P).
4. Crossings are sign changes between adjacent grid points, located by linear interpolation.
5. **Selection rule:** the crossing nearest the reference price. All crossings are exported as
   alternatives.
6. Zero gamma is **not** returned in these cases:
   - there is no crossing in range (status `NO CROSSING`);
   - contracts with IV make up less than `min_profile_coverage` (80%) of gross exposure (status
     `UNAVAILABLE`), because contracts without IV can't be re-priced.

The current sign of net GEX is never used as a zero-gamma level.

## 8. Levels

| Level | Definition | Metric shown |
|---|---|---|
| Call wall | strike with max \|Σ call exposure\| in the basket | `|call exposure|` and call OI |
| Put wall | strike with max \|Σ put exposure\| | `|put exposure|` and put OI |
| Max +GEX / Max −GEX | strike with the largest positive / most negative net | net exposure |
| Concentrations | strikes with \|net\| ≥ `min_share` of Σ\|net\|, top `top_n` | share |
| Near-price clusters | runs of adjacent significant strikes within ±`cluster_window_pct` | exposure-weighted centre |
| Expected move | S · IV_ATM · √T to the nearest expiry, plus the ATM straddle mid when quoted | points |
| Gamma-weighted distance | Σ\|net_k\|·\|K−S\| / Σ\|net_k\| | points |
| Near-spot concentration | gross within ±1% of S / total gross | share |

Walls use the magnitude of *gamma exposure*, not raw OI, and they do not depend on the sign model.
By default (`wall_side_filter=true`) the call wall is searched at or above S and the put wall at or
below S. Without the filter, deep in-the-money calls with large OI can put the "call wall" below price.
Set `"levels": {"wall_side_filter": false}` to search all strikes.

### Additional levels (`gexsys/extras.py`)

| Level | Definition |
|---|---|
| 0DTE / next-expiration ZG, call wall, put wall | The core definitions above, recomputed on the nearest expiration only. Labeled `0DTE` when it expires today (ET), else `next MM-DD`. |
| Volume walls | Strike within ±5% of S with the most call (put) **volume** summed over the basket. Volume is today's, 15-min delayed, so it moves intraday; outside RTH it is the last session's. |
| OI walls | Strike within ±5% of S with the most raw call (put) open interest. |
| Max pain (per expiration) | argmin over that expiration's strikes K* of Σ calls OI·max(0, K*−K) + Σ puts OI·max(0, K−K*). A popular statistic, not a price target. |
| Daily expected move | anchor ± S·√V, V = implied variance of one full session from w(e) = IV_atm(e)²·T(e) (T in calendar years, as the IVs are annualized). Market closed: w of the expiration at the next session's close. Market open: forward variance w(next session) − w(today). No daily expirations: w(first) ÷ sessions until it. |
| Weekly expected move | anchor ± S·√V, V = w(this week's last expiration); during RTH today's full-session variance + w(week) − w(today). |
| Expected-move anchor | Previous session close during RTH; the last close outside RTH. The bands stay fixed for the session. |
| GEX profile | Net exposure summed into equal-width bins (≈40 bins over ±2.5% of S, width from 0.5/1/2/2.5/5/10/25/50/100/250), scaled to −99..99 of the largest bin. |
| Absolute gamma strike | argmax over strikes of Σ\|exposure\| (calls and puts together). Independent of the sign assumption. |

### Second-order exposures (`extras.greek_exposures`)

These use the same positioning signs sᵢ as GEX, and only contracts with an IV. Their coverage of
gross GEX is reported.

| Quantity | Formula | Meaning |
|---|---|---|
| Vanna exposure | Σ sᵢ·OIᵢ·Mᵢ·vannaᵢ·S·0.01, with vanna = ∂Δ/∂σ = −e^(−qT)·φ(d1)·d2/σ | change in dealer dollar delta if implied vol rises 1 point |
| Charm exposure | Σ sᵢ·OIᵢ·Mᵢ·charmᵢ·S/365, with charm = ∂Δ/∂t (BSM with dividend q) | change in dealer dollar delta per calendar day of time decay |
| Hedge flow | −(vanna exposure), −(charm exposure) | dealers trade opposite their delta change to stay hedged |

Both Greeks are validated against central finite differences of delta (`tests/test_pricing.py`).
Charm is largest close to expiration, which is why its effect concentrates late in the session.

### Futures-contract translation (website and indicator panel)

Dollar figures become contracts by dividing by one contract's notional, futures price × point value:
- point value is $20 for NQ, $2 for MNQ, $50 for ES and $5 for MES;
- the indicator uses `syminfo.pointvalue` of the chart, so it adapts automatically;
- example: −$1.2B per 1% ÷ (29,900 × $20) ≈ 2,000 NQ contracts per 1% move.

Zero-gamma distance in σ is (price − zero gamma) ÷ daily expected move. Under about 0.3σ, price sits
at the flip.

### Daily bias (`gexsys/bias.py`, website Bias tab)

A transparent, rule-based reading of positioning. It is **not a forecast**: every factor, score and
reason is shown.

| Factor | Score |
|---|---|
| Gamma side | σ = (price − zero gamma) ÷ daily expected move. Above +0.3 is a range day, below −0.3 a trend day, otherwise a pivot day. Sets the day **type**, not direction. |
| Magnet | Range days: +1/−1 × min(1, distance to the absolute-gamma strike ÷ 0.5σ). Other days: half weight. |
| Charm | ±1 by the sign of the dealer hedge flow from time decay |
| Walls | −0.5 within 0.25σ under the call wall; +0.5 within 0.25σ over the put wall |
| Vanna | ±0.5: hedge flow if IV eases (range day) or rises (trend day) |
| 0DTE max pain | up to ±0.5 toward today's max pain if it is within 1σ |

**Reading the score:**
- Score ≥ +0.75 is bullish, ≤ −0.75 bearish, otherwise neutral.
- Confidence is from |score|: below 1.25 low, below 2 medium, otherwise high. Pivot days are always
  low.

**Base case and range by day type:**
- **Range day:** the magnet, within ±0.7σ capped by the walls.
- **Trend day:** ±0.8σ in the bias direction, range up to 1.2σ on that side.
- **Pivot day:** zero gamma, range ±0.9σ.
- **Override:** the base case always moves in the bias direction; otherwise it is price + lean ×
  min(|score|/3, 1) × 0.4σ.

**The chart:**
- An eased path from now (or the 09:30 open) to the base case.
- A ±1σ·√(elapsed/session) cone. Early closes shorten the session.

Tested in `tests/test_bias.py`.

### Considered and not added

A "volume-adjusted" 0DTE exposure (adding today's volume to stale open interest) was considered.
Practitioner sources agree that 0DTE positions are missing from OI, but no standard formula exists,
and volume cannot tell opening trades from closing ones. An invented adjustment would look precise
without being reliable, so the 0DTE levels stay OI-based and are labeled as such.

## 9. Regime

The regime is `INDETERMINATE` when either:
- \|net\| / gross < `regime_band` (5%), or
- S is within `zero_gamma_band_pct` (0.15%) of the zero-gamma estimate.

Otherwise the regime is `POSITIVE` or `NEGATIVE` by the sign of net. A modeled regime does not
guarantee any price behaviour.

## 10. Snapshot changes

`engine.diff` reports:
- the shift of zero gamma, the walls and max ± (in points);
- the change in net;
- whether the regime changed;
- the concentration shift: the total-variation distance between normalized |net|-by-strike
  distributions (0 = identical, 1 = disjoint).

## 11. Mapping to futures

See `gexsys/mapping.py`. Methods:
- `ratio`: L·F/U. This is the only method allowed for ETFs.
- `offset`: L + (F − U). Allowed only for the same index.
- `identity`: futures options on the charted contract.
- `calendar_offset`: futures options on another contract month.

Basis mapping is refused when F and U were observed more than `max_skew_s` apart. Mapped levels
round to the futures tick (0.25 for NQ/MNQ/ES/MES). Index and ETF sources are labeled **PROXY**.

## 12. Calibration and evaluation

`gexsys/replay.py` measures the calculations, not trading outcomes:
- level stability (mean and max absolute shift, share of snapshots in which a level moved);
- regime changes;
- unavailable and degraded frequency;
- latency.

Any strategy study has to be pre-registered before it runs:
- **Hypothesis:** for example, "after a zero-gamma cross in RTH, 30-minute realized range exceeds
  the median."
- **Sample split:** in-sample / out-of-sample by date.
- **Costs:** 1 tick of slippage per side plus commissions.
- **Look-ahead control:** use only snapshots whose `asof` precedes the signal bar.

The system ships no such result and makes no predictive claim.
