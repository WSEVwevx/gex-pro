// GEX PRO Library: a course on options, dealer hedging, gamma exposure and the GEX PRO levels.
// Content only (the page that shows it is in app.js). Lessons: {id, chapter, title, minutes, oneLiner,
// body (HTML; {{d:name}} inserts a diagram), points (key points), example, gex: [page, label], quiz: {q, choices, answer, why}}.
window.GEX_LIBRARY = (() => {
  const chapters = [
    ["basics", "1. Options basics"],
    ["dealers", "2. Dealers and the Greeks"],
    ["gex", "3. Gamma exposure (GEX)"],
    ["vol", "4. Volatility"],
    ["levels", "5. The GEX PRO levels"],
    ["use", "6. Using GEX PRO"],
  ];

  // ---------- small diagrams (SVG strings, theme colours via CSS variables)
  const W = 420, H = 170;
  const axes = (xl, yl) => `<line x1="40" y1="${H - 30}" x2="${W - 10}" y2="${H - 30}" stroke="var(--line3)"/><line x1="40" y1="10" x2="40" y2="${H - 30}" stroke="var(--line3)"/>
    <text x="${W - 10}" y="${H - 12}" text-anchor="end">${xl}</text><text x="44" y="20">${yl}</text>`;
  const diagrams = {
    payoff_call: () => `<svg viewBox="0 0 ${W} ${H}">${axes("price at expiration →", "profit")}
      <line x1="40" y1="80" x2="${W - 10}" y2="80" stroke="var(--line2)" stroke-dasharray="3 3"/>
      <polyline fill="none" stroke="var(--pos)" stroke-width="2.5" points="40,100 220,100 400,20"/>
      <line x1="220" y1="20" x2="220" y2="${H - 30}" stroke="var(--zg)" stroke-dasharray="4 3"/><text x="224" y="${H - 36}">strike 100</text>
      <text x="80" y="116" style="fill:var(--neg)">lose only the premium</text><text x="290" y="44" style="fill:var(--pos)">gain as price rises</text></svg>`,
    payoff_put: () => `<svg viewBox="0 0 ${W} ${H}">${axes("price at expiration →", "profit")}
      <line x1="40" y1="80" x2="${W - 10}" y2="80" stroke="var(--line2)" stroke-dasharray="3 3"/>
      <polyline fill="none" stroke="var(--neg)" stroke-width="2.5" points="40,20 220,100 400,100"/>
      <line x1="220" y1="20" x2="220" y2="${H - 30}" stroke="var(--zg)" stroke-dasharray="4 3"/><text x="224" y="${H - 36}">strike 100</text>
      <text x="52" y="44" style="fill:var(--pos)">gain as price falls</text><text x="250" y="116" style="fill:var(--neg)">lose only the premium</text></svg>`,
    delta_curve: () => `<svg viewBox="0 0 ${W} ${H}">${axes("stock price →", "delta (0 to 1)")}
      <path d="M40,130 C150,130 170,125 220,75 S300,22 400,20" fill="none" stroke="var(--pos)" stroke-width="2.5"/>
      <line x1="220" y1="20" x2="220" y2="${H - 30}" stroke="var(--zg)" stroke-dasharray="4 3"/><text x="224" y="${H - 36}">strike</text>
      <text x="48" y="122">far below: ~0</text><text x="300" y="40">far above: ~1</text><text x="226" y="70">at the strike: ~0.5</text></svg>`,
    gamma_bell: () => `<svg viewBox="0 0 ${W} ${H}">${axes("stock price →", "gamma")}
      <path d="M40,138 C150,138 180,30 220,30 S290,138 400,138" fill="none" stroke="var(--pos)" stroke-width="1.5" stroke-dasharray="4 3"/>
      <path d="M40,139 C190,139 205,12 220,12 S250,139 400,139" fill="none" stroke="var(--prompt)" stroke-width="2.5"/>
      <line x1="220" y1="10" x2="220" y2="${H - 30}" stroke="var(--zg)" stroke-dasharray="4 3"/><text x="224" y="${H - 36}">strike</text>
      <text x="262" y="40" style="fill:var(--prompt)">expiring today: tall and narrow</text><text x="262" y="72" style="fill:var(--pos)">a month out: low and wide</text></svg>`,
    hedging: () => `<svg viewBox="0 0 ${W} 190">
      <text x="105" y="18" text-anchor="middle" style="fill:var(--pos);font-weight:700">POSITIVE GAMMA</text>
      <text x="315" y="18" text-anchor="middle" style="fill:var(--neg);font-weight:700">NEGATIVE GAMMA</text>
      <line x1="210" y1="8" x2="210" y2="182" stroke="var(--line2)"/>
      <text x="105" y="50" text-anchor="middle">price rises ↑</text><text x="105" y="72" text-anchor="middle" style="fill:var(--pos)">dealers SELL to re-hedge</text>
      <text x="105" y="112" text-anchor="middle">price falls ↓</text><text x="105" y="134" text-anchor="middle" style="fill:var(--pos)">dealers BUY to re-hedge</text>
      <text x="105" y="170" text-anchor="middle" style="fill:var(--ink)">= pushes AGAINST the move (calm)</text>
      <text x="315" y="50" text-anchor="middle">price rises ↑</text><text x="315" y="72" text-anchor="middle" style="fill:var(--neg)">dealers BUY to re-hedge</text>
      <text x="315" y="112" text-anchor="middle">price falls ↓</text><text x="315" y="134" text-anchor="middle" style="fill:var(--neg)">dealers SELL to re-hedge</text>
      <text x="315" y="170" text-anchor="middle" style="fill:var(--ink)">= pushes WITH the move (fast)</text></svg>`,
    flip: () => `<svg viewBox="0 0 ${W} ${H}">${axes("price →", "dealer gamma")}
      <line x1="40" y1="80" x2="${W - 10}" y2="80" stroke="var(--line3)"/>
      <path d="M40,130 C140,128 190,100 230,80 S330,30 400,26" fill="none" stroke="var(--ink)" stroke-width="2.5"/>
      <path d="M40,80 L40,130 C140,128 190,100 230,80 Z" fill="rgba(217,89,38,.25)"/><path d="M230,80 C270,60 330,30 400,26 L400,80 Z" fill="rgba(57,135,229,.25)"/>
      <line x1="230" y1="10" x2="230" y2="${H - 30}" stroke="var(--zg)" stroke-dasharray="4 3"/><text x="234" y="${H - 36}">zero gamma</text>
      <text x="60" y="112" style="fill:var(--neg)">below: moves get faster</text><text x="282" y="64" style="fill:var(--pos)">above: moves get calmer</text></svg>`,
    walls: () => `<svg viewBox="0 0 ${W} 180">
      ${[[30, 10, "n"], [45, 18, "n"], [60, 52, "n"], [75, 24, "n"], [90, 14, "n"], [105, 8, "p"], [120, 16, "p"], [135, 60, "p"], [150, 30, "p"], [165, 12, "p"]].map(([y, w, s]) =>
        `<rect x="${s === "p" ? 210 : 210 - w * 2.6}" y="${180 - y - 6}" width="${w * 2.6}" height="10" rx="2" fill="${s === "p" ? "var(--pos)" : "var(--neg)"}" opacity=".85"/>`).join("")}
      <line x1="210" y1="0" x2="210" y2="180" stroke="var(--line3)"/>
      <text x="374" y="47" style="fill:var(--pos)">← call wall</text><text x="20" y="125" style="fill:var(--neg)">put wall →</text>
      <line x1="40" y1="${180 - 98}" x2="400" y2="${180 - 98}" stroke="var(--ink)" stroke-width="1.5"/><text x="404" y="${180 - 94}" text-anchor="end" style="fill:var(--ink)">price</text></svg>`,
    bands: () => `<svg viewBox="0 0 ${W} 180">
      ${[[20, "+2σ", "4 3"], [55, "+1σ", ""], [125, "-1σ", ""], [160, "-2σ", "4 3"]].map(([y, t, d]) => `<line x1="40" y1="${y}" x2="370" y2="${y}" stroke="var(--ink3)" stroke-dasharray="${d}"/><text x="376" y="${y + 4}">D${t}</text>`).join("")}
      <line x1="40" y1="90" x2="370" y2="90" stroke="var(--line3)" stroke-dasharray="2 4"/><text x="376" y="94" style="fill:var(--ink3)">close</text>
      <polyline fill="none" stroke="var(--prompt)" stroke-width="2" points="40,90 70,84 100,96 130,74 160,80 190,62 220,58 250,70 280,66 310,52 340,60 370,57"/>
      <text x="48" y="40" style="fill:var(--ink3)">about 68% of sessions end inside ±1σ, 95% inside ±2σ</text></svg>`,
    zones: () => `<svg viewBox="0 0 ${W} 200">
      <rect x="40" y="14" width="300" height="38" fill="var(--pos)" opacity=".12"/><rect x="40" y="52" width="300" height="48" fill="var(--pos)" opacity=".26"/>
      <rect x="40" y="100" width="300" height="46" fill="var(--neg)" opacity=".26"/><rect x="40" y="146" width="300" height="40" fill="var(--neg)" opacity=".12"/>
      ${[[14, "C2", "var(--pos)"], [52, "C1", "var(--pos)"], [100, "flip", "var(--zg)"], [146, "P1", "var(--neg)"], [186, "P2", "var(--neg)"]].map(([y, t, c]) => `<line x1="40" y1="${y}" x2="340" y2="${y}" stroke="${c}" stroke-width="1.5"/><text x="346" y="${y + 4}" style="fill:${c}">${t}</text>`).join("")}
      <text x="50" y="37">Positive Gamma Extension Zone</text><text x="50" y="80">Positive Gamma Zone: hedging dampens moves</text>
      <text x="50" y="127">Negative Gamma Zone: hedging adds to moves</text><text x="50" y="170">Negative Gamma Extension Zone</text></svg>`,
    term: () => `<svg viewBox="0 0 ${W} ${H}">${axes("days to expiration →", "implied vol")}
      <polyline fill="none" stroke="var(--pos)" stroke-width="2.5" points="50,110 120,96 200,84 300,74 400,68"/><text x="300" y="62" style="fill:var(--pos)">normal: upward</text>
      <polyline fill="none" stroke="var(--neg)" stroke-width="2.5" points="50,30 120,52 200,66 300,74 400,78"/><text x="60" y="24" style="fill:var(--neg)">stress: inverted</text></svg>`,
    skew: () => `<svg viewBox="0 0 ${W} ${H}">${axes("strike →", "implied vol")}
      <path d="M50,30 C150,70 230,100 300,108 S380,110 400,106" fill="none" stroke="var(--prompt)" stroke-width="2.5"/>
      <line x1="230" y1="10" x2="230" y2="${H - 30}" stroke="var(--zg)" stroke-dasharray="4 3"/><text x="234" y="${H - 36}">price now</text>
      <text x="56" y="22" style="fill:var(--neg)">downside puts cost more</text><text x="300" y="98">upside calls cheaper</text></svg>`,
  };

  const L = (o) => o;
  const lessons = [
    // ---------------------------------------------------------------- 1. options basics
    L({id: "what-is-an-option", chapter: "basics", title: "What an option is", minutes: 3,
      oneLiner: "A contract that gives the right, but not the obligation, to buy or sell at a fixed price until a set date.",
      body: `<p>An option works like a paid reservation. The buyer pays a fee up front, the <b>premium</b>, to lock in a price, the <b>strike</b>, until a date, the <b>expiration</b>. If the locked-in price turns out to be favourable, the buyer uses it. If not, the buyer lets it expire and loses only the premium.</p>
        <p>There are two types:</p><ul><li>A <b>call</b> is the right to <b>buy</b> at the strike. It gains value when price rises.</li><li>A <b>put</b> is the right to <b>sell</b> at the strike. It gains value when price falls, which is why investors buy puts as insurance.</li></ul>
        <p>One stock, ETF or index option covers <b>100 units</b> of the underlying. That number is the <b>multiplier</b>: an option quoted at $2.00 costs $200.</p>{{d:payoff_call}}`,
      points: ["Buyers pay the premium and can lose at most that amount.", "Calls benefit from rising prices, puts from falling prices.", "Prices are quoted per unit; multiply by 100 for the cost of one contract."],
      example: `SPY trades at $600. You buy the 610 call for $2.00, which costs $200. If SPY ends at $620, the call is worth $10.00 ($1,000), a profit of $800. If SPY ends below $610, the call expires worthless and you lose the $200.`,
      gex: ["levels", "See the strikes that matter today on the Levels page"],
      quiz: {q: "You want protection against a market decline. Which option fits?", choices: ["A call", "A put", "Neither"], answer: 1, why: "A put gains value as price falls, which is why it is used as insurance."}}),
    L({id: "calls-and-puts", chapter: "basics", title: "Calls, puts and moneyness", minutes: 3,
      oneLiner: "Whether an option is in, at or out of the money depends on where price sits relative to its strike.",
      body: `<p>A put is the mirror image of a call: it pays off as price falls below its strike.</p>{{d:payoff_put}}
        <p>Three terms describe where an option stands today:</p><ul><li><b>In the money (ITM)</b>: it would be worth something if exercised now. A call with price above its strike, or a put with price below it.</li><li><b>At the money (ATM)</b>: the strike is at, or very close to, the current price.</li><li><b>Out of the money (OTM)</b>: it would be worth nothing if exercised now; it needs a move in its favour.</li></ul>
        <p>Every option has a buyer and a seller. The buyer's risk is limited to the premium; the seller collects the premium and takes on the risk. The seller is very often a professional <b>dealer</b>, and how dealers manage that risk is the subject of the rest of this course.</p>`,
      points: ["Calls are in the money above their strike, puts below it.", "At-the-money options are the most sensitive to small moves.", "Dealers sit on the other side of most customer trades."],
      example: `With SPX at 6,000: the 6,100 call and the 5,900 put are out of the money; the 6,000 call and put are at the money; the 5,900 call is in the money by 100 points.`,
      quiz: {q: "SPX is at 6,000. Is the 5,800 put in, at or out of the money?", choices: ["In the money", "At the money", "Out of the money"], answer: 2, why: "A put has value only below its strike. 6,000 is above 5,800, so the put is out of the money."}}),
    L({id: "open-interest-volume", chapter: "basics", title: "Open interest and volume", minutes: 2,
      oneLiner: "Volume counts contracts traded today; open interest counts contracts still open.",
      body: `<p><b>Volume</b> is the number of contracts that changed hands today. It starts at zero each morning and rises during the session.</p>
        <p><b>Open interest (OI)</b> is the number of contracts that are still open: created and not yet closed or expired. The clearing house publishes it once a day, before the next session, so during the day it reflects <b>yesterday's close</b>.</p>
        <p>Gamma exposure is built on open interest, because dealers hedge the positions that still exist. Today's volume is shown alongside it (volume walls, net volume) as a live indication of where new activity is concentrated.</p>`,
      points: ["Open interest is the stock of positions; volume is today's flow.", "Open interest updates once a day; volume updates continuously.", "GEX uses open interest."],
      example: `A strike with 50,000 contracts of open interest and 2,000 traded today is a large, established position. A strike with 1,000 open and 30,000 traded today is where new positioning is building.`,
      gex: ["levels", "Volume and OI walls are on the Levels page (filter: Volume & OI)"],
      quiz: {q: "Which figure changes during the trading day?", choices: ["Open interest", "Volume", "Both"], answer: 1, why: "Volume is counted trade by trade; open interest is published once a day."}}),
    L({id: "index-etf-futures", chapter: "basics", title: "Index, ETF and futures: SPX, SPY, ES and NDX, QQQ, NQ", minutes: 3,
      oneLiner: "Three ways to trade the same market, at different sizes, whose option levels can be translated into one another.",
      body: `<p>The S&P 500 trades as <b>SPX</b> (the cash index, through its options), <b>SPY</b> (an ETF priced at about one tenth of SPX) and <b>ES</b> (futures). The Nasdaq-100 trades as <b>NDX</b>, <b>QQQ</b> (about 1/41 of NDX) and <b>NQ</b> futures.</p>
        <p>Futures usually trade slightly above the index because of <b>carry</b>: the interest earned on cash minus the dividends the index pays, until the futures expire. GEX PRO measures the gap and converts every level into a futures price, so the levels line up with your NQ or ES chart. On TradingView the indicator does this with the live ratio between your chart and the index.</p>
        <p>GEX PRO combines <b>SPX + SPY</b> options for ES and <b>NDX + QQQ</b> options for NQ. ETF options are scaled to index size: about 10 SPY contracts carry the exposure of one SPX contract.</p>`,
      points: ["SPY ≈ SPX ÷ 10; QQQ ≈ NDX ÷ 41.", "Futures trade at a small premium to the index (carry).", "Every level on GEX PRO is shown in futures prices."],
      example: `SPX 6,000 → SPY about 600 → ES about 6,025 when carry is about 25 points. A put wall at SPX 5,950 appears on the ES chart near 5,975.`,
      gex: ["levels", "The reference price card shows the index price and its futures equivalent"],
      quiz: {q: "Why does an ES level sit slightly above the matching SPX level?", choices: ["Rounding", "Futures carry: interest minus dividends", "ES is a different market"], answer: 1, why: "Futures price in the cost of carry until expiration, so they trade at a small premium to the index."}}),
    // ---------------------------------------------------------------- 2. dealers and the Greeks
    L({id: "dealers", chapter: "dealers", title: "Dealers and hedging", minutes: 3,
      oneLiner: "Market makers take the other side of option trades and hedge continuously to stay neutral on direction.",
      body: `<p>When a customer buys or sells an option, the counterparty is usually a <b>dealer</b> (market maker). A dealer aims to earn the bid-ask spread, not to bet on direction.</p>
        <p>To remove direction risk, the dealer <b>hedges</b> by trading the underlying: shares, the ETF or futures. As price moves and time passes, the option's risk changes, so the dealer keeps adjusting that hedge.</p>
        <p>Dealer hedging is large enough to influence prices. Gamma exposure is a model of how much, and in which direction, dealers will need to trade as the market moves.</p>`,
      points: ["Dealers are paid to provide liquidity, not to take direction.", "They hedge with the underlying and re-hedge as conditions change.", "GEX estimates the size and direction of that re-hedging."],
      example: `A dealer sells a customer an ES call. If ES rises, the call gains value and the dealer loses on it, so the dealer buys ES futures to offset that, and buys more if ES keeps rising.`,
      quiz: {q: "What is a dealer's main objective?", choices: ["Profit from the market rising", "Earn the spread while staying neutral", "Profit from the market falling"], answer: 1, why: "Dealers earn the spread and hedge away directional risk."}}),
    L({id: "delta", chapter: "dealers", title: "Delta", minutes: 3,
      oneLiner: "How much an option's price moves for a 1-point move in the underlying, and therefore how much underlying hedges it.",
      body: `<p>Delta runs from <b>0 to 1</b> for calls and from <b>0 to −1</b> for puts. A call with a delta of 0.50 gains about $0.50 when the underlying rises $1.</p>{{d:delta_curve}}
        <p>Delta is also the <b>hedge ratio</b>. A dealer who is short one call with delta 0.50 (100 multiplier) buys 50 shares to be neutral.</p>
        <p>As a rough guide, delta is close to the probability that the option finishes in the money: a 0.25-delta option is roughly a one-in-four chance.</p>`,
      points: ["Calls: 0 to 1. Puts: 0 to −1. At the money: about ±0.5.", "Delta × multiplier = the shares or contracts that hedge the option.", "Delta changes as price and time move; that change is gamma and charm."],
      example: `A dealer short 100 SPY calls with delta 0.40 holds 100 × 100 × 0.40 = 4,000 SPY shares as a hedge.`,
      quiz: {q: "A call has delta 0.80. The underlying rises $1. Roughly how much does the call gain per unit?", choices: ["$0.08", "$0.80", "$8.00"], answer: 1, why: "Delta 0.80 means about $0.80 per $1 move, per unit of the underlying."}}),
    L({id: "gamma", chapter: "dealers", title: "Gamma", minutes: 4,
      oneLiner: "How fast delta changes as price moves, which sets how much dealers must re-hedge.",
      body: `<p>Delta is not fixed. Near the strike it changes quickly as price moves; far from the strike it barely changes. <b>Gamma</b> measures that rate of change.</p>{{d:gamma_bell}}
        <ul><li>Gamma is <b>highest at the money</b>.</li><li>It becomes <b>taller and narrower as expiration approaches</b>. Options expiring today (0DTE) carry very large gamma close to price, and almost none further away.</li><li>A call and a put with the same strike and expiration have the <b>same gamma</b>.</li></ul>
        <p>For a dealer, more gamma means more re-hedging for every move in price. That re-hedging is what gamma exposure maps.</p>`,
      points: ["Gamma = change in delta per 1-point move.", "Largest at the money and close to expiration.", "Gamma determines how much dealers trade as price moves."],
      example: `An at-the-money SPY option with gamma 0.05: a $1 rise lifts its delta from 0.50 to about 0.55. A dealer hedging 100 of them must trade 100 × 100 × 0.05 = 500 more shares.`,
      gex: ["ladder", "See gamma strike by strike on the Live table"],
      quiz: {q: "Where is gamma highest?", choices: ["Deep in the money", "At the money, close to expiration", "Far out of the money, far from expiration"], answer: 1, why: "Gamma peaks at the strike, and the peak sharpens as expiration approaches."}}),
    L({id: "positive-negative-gamma", chapter: "dealers", title: "Positive and negative gamma", minutes: 4,
      oneLiner: "Long gamma makes dealers trade against price moves; short gamma makes them trade with them.",
      body: `<p>Whether dealers <b>own</b> gamma (long options) or <b>owe</b> it (short options) reverses the direction of their hedging:</p>{{d:hedging}}
        <p><b>Long gamma (positive):</b> as price rises, the dealer's position becomes longer, so the dealer sells; as price falls, it becomes shorter, so the dealer buys. Hedging leans <b>against</b> the move, which tends to dampen volatility and keep price in a range.</p>
        <p><b>Short gamma (negative):</b> the reverse. The dealer buys as price rises and sells as it falls. Hedging moves <b>with</b> the price, which tends to extend moves. Many of the largest daily moves occur in negative gamma.</p>`,
      points: ["Positive gamma: dealers buy dips and sell rallies (dampening).", "Negative gamma: dealers sell weakness and buy strength (amplifying).", "The regime describes tendencies, not certainties."],
      example: `Positive gamma: ES rallies 20 points, dealer selling meets the rally and it fades. Negative gamma: ES breaks 30 points lower, dealers sell futures to re-hedge, and the decline extends.`,
      gex: ["levels", "The regime card on the Levels page shows which side the market is on"],
      quiz: {q: "Dealers are short gamma and price falls. What do they do?", choices: ["Buy, slowing the decline", "Sell, adding to the decline", "Nothing"], answer: 1, why: "Short gamma leaves dealers longer as price falls, so they sell to re-hedge, adding to the move."}}),
    L({id: "vanna-charm", chapter: "dealers", title: "Vanna and charm", minutes: 4,
      oneLiner: "Delta also changes when implied volatility moves (vanna) and as time passes (charm), creating hedging flows without any price move.",
      body: `<ul><li><b>Vanna</b> is the change in delta when <b>implied volatility</b> changes. With the usual positioning (customers long puts, dealers short them), a drop in implied volatility, such as after a Fed decision or CPI, shrinks put deltas and leaves dealers over-hedged; unwinding that hedge means <b>buying</b>. A rise in implied volatility works the other way.</li>
        <li><b>Charm</b> is the change in delta as <b>time passes</b>. Out-of-the-money options lose delta as expiration approaches, so the hedges against them are gradually unwound. The effect is strongest in the last hours of the session and around expirations.</li></ul>
        <p>The Levels page converts both into futures contracts: <b>Charm flow per day</b> and <b>Vanna: if IV rises 1 pt</b>.</p>`,
      points: ["Vanna: hedging caused by implied-volatility changes.", "Charm: hedging caused by the passage of time.", "Both can move the market on days when price itself is quiet."],
      example: `"Charm flow per day: Buy 11,000 NQ" means time decay alone implies dealers buying exposure equivalent to about 11,000 NQ contracts over the session, concentrated into the close.`,
      gex: ["levels", "Charm and vanna are on the Levels stats strip"],
      quiz: {q: "Implied volatility collapses after a Fed decision. Which effect drives the resulting hedging?", choices: ["Charm", "Vanna", "Neither"], answer: 1, why: "Vanna is the change in delta, and therefore in hedging, caused by a change in implied volatility."}}),
    // ---------------------------------------------------------------- 3. gamma exposure
    L({id: "what-is-gex", chapter: "gex", title: "Gamma exposure (GEX)", minutes: 4,
      oneLiner: "The sum of every option's gamma, in dollars: how much dealers would trade for a 1% move.",
      body: `<p>For each option, GEX = <b>gamma × open interest × multiplier × price² × 1%</b>. Adding every option together, with calls and puts given opposite signs, gives the dollars of underlying dealers would buy or sell if the market moved 1%.</p>
        <p>The sign rests on an <b>assumption</b>: customers mostly sell calls (for example covered calls) and buy puts (protection), so dealers are taken to be <b>long calls and short puts</b>. This is the standard industry convention, not reported data; actual positioning can differ, especially around large events.</p>
        <p>Read GEX as a map of <b>hedging pressure</b>: where dealer flows are likely to dampen moves and where they are likely to add to them.</p>`,
      points: ["GEX is measured in dollars per 1% move.", "Positive net GEX dampens moves; negative net GEX amplifies them.", "The dealer-positioning sign is a convention, not observed data."],
      example: `"Net GEX −$10B per 1%" means that if the market fell 1%, dealers would need to sell about $10 billion of underlying to stay hedged (and buy that much on a 1% rise): an amplifying market.`,
      gex: ["levels", "Net GEX is on the Levels page"],
      quiz: {q: "Net GEX is strongly positive. Which session is more likely?", choices: ["A wide trend day", "A narrower, mean-reverting day", "GEX says nothing about it"], answer: 1, why: "With positive GEX, dealer hedging leans against moves, which tends to narrow the range."}}),
    L({id: "zero-gamma", chapter: "gex", title: "Zero gamma (the gamma flip)", minutes: 3,
      oneLiner: "The price at which total dealer gamma changes sign.",
      body: `<p>Gamma exposure changes as price moves. GEX PRO re-prices every option across a range of hypothetical prices and finds where the total crosses <b>zero</b>. That price is <b>zero gamma</b>, also called the gamma flip.</p>{{d:flip}}
        <p><b>Above</b> zero gamma, dealer hedging tends to dampen moves. <b>Below</b> it, hedging tends to amplify them. Close to zero gamma there is little hedging support in either direction, and trading is often choppy until price moves away from it.</p>
        <p>The <b>σ figure</b> next to it gives the distance in expected moves. Under 0.3σ, a small move can change the regime.</p>`,
      points: ["Zero gamma is a modeled estimate, not an exchange-published level.", "Above it: dampening. Below it: amplifying.", "Near it: the regime can change quickly."],
      example: `NQ at 29,000 with zero gamma at 29,800: price is below the flip, so negative gamma applies. A sustained move back above 29,800 would point to calmer conditions.`,
      gex: ["levels", "Zero gamma and the regime are on the Levels page"],
      quiz: {q: "Price falls through zero gamma. What usually changes?", choices: ["Moves tend to become larger", "Moves tend to become smaller", "Nothing"], answer: 0, why: "Below zero gamma dealers are net short gamma, and their hedging adds to moves."}}),
    L({id: "walls", chapter: "gex", title: "Call wall, put wall and absolute gamma", minutes: 4,
      oneLiner: "The strikes holding the most call gamma, put gamma and total gamma.",
      body: `{{d:walls}}<ul><li><b>Call wall</b>: the strike above price with the most call gamma. Dealer hedging around it tends to slow rallies, so it often acts as resistance.</li><li><b>Put wall</b>: the strike below price with the most put gamma. It often acts as support; a decisive break below it can accelerate selling.</li><li><b>Absolute gamma strike</b>: the strike with the most total gamma, calls and puts combined. Price often gravitates toward it, especially near expiration ("pinning"). Because it ignores the sign, it does not depend on the positioning assumption.</li></ul>
        <p>Treat walls as <b>zones</b> rather than exact prices, and expect them to move as positions change.</p>`,
      points: ["Call wall: resistance tendency above price.", "Put wall: support tendency below price; breaks can accelerate.", "Absolute gamma: a magnet, strongest near expiration."],
      example: `ES at 7,650 with the call wall at 8,000 and the put wall at 7,600: support is close below while resistance is far above, an asymmetric range.`,
      gex: ["levels", "All walls are on the Levels page"],
      quiz: {q: "Which level most often acts as a magnet near expiration?", choices: ["The call wall", "The absolute gamma strike", "The put wall"], answer: 1, why: "The strike with the most total gamma concentrates hedging flows and tends to pin price."}}),
    L({id: "zero-dte", chapter: "gex", title: "0DTE options", minutes: 3,
      oneLiner: "Options that expire today: very large gamma close to price, gone at the close.",
      body: `<p>SPX, SPY, NDX and QQQ list options that expire <b>every trading day</b>. Those expiring today are <b>0DTE</b> (zero days to expiration).</p>
        <p>Because gamma concentrates near the money as expiration approaches, 0DTE options carry very large gamma <b>within a narrow range around price</b>. They can dominate intraday hedging, and their influence ends at the close, when they expire. This is why intraday levels can shift between the morning and the afternoon, and why GEX PRO ranks today's expiry separately.</p>`,
      points: ["0DTE gamma is large but concentrated close to price.", "It disappears at the close.", "Intraday levels are driven mainly by the first expiry."],
      example: `Early in the afternoon, an at-the-money 0DTE call can go from several dollars to nothing on a 0.5% move. Dealers hedging thousands of contracts have to adjust quickly.`,
      gex: ["levels", "Filter the Levels page by 0DTE"],
      quiz: {q: "What happens to 0DTE gamma at the close?", choices: ["It doubles", "It disappears", "It rolls into tomorrow"], answer: 1, why: "0DTE options expire at the close, so their gamma, and the hedging it creates, ends."}}),
    L({id: "max-pain", chapter: "gex", title: "Max pain", minutes: 2,
      oneLiner: "The settlement price at which option holders, as a group, would receive the least.",
      body: `<p>For a given expiration, max pain is the settlement price that makes the <b>total value paid out to option holders smallest</b>: the price where the open calls and puts together are worth the least at expiration.</p>
        <p>Some traders expect price to drift toward it into expiration. The evidence is mixed, and trends and news easily override it. It is a statistic, not a target; it is most relevant on expiration days.</p>`,
      points: ["Max pain minimises the total payout to option holders.", "It is a statistic, not a price target.", "Its relevance is greatest on expiration day."],
      example: `Max pain at 7,700 for today's ES expiration with ES at 7,720: a mild drift lower into the close is possible, unless stronger forces are at work.`,
      quiz: {q: "Is max pain a price target?", choices: ["Yes, price always reaches it", "No, it is a statistic that news can override", "Only on Mondays"], answer: 1, why: "Max pain describes where option holders would be paid the least; it does not force price there."}}),
    // ---------------------------------------------------------------- 4. volatility
    L({id: "implied-volatility", chapter: "vol", title: "Implied volatility and the expected move", minutes: 4,
      oneLiner: "Implied volatility is the movement priced into options; the expected move translates it into points.",
      body: `<p>Option prices contain the market's estimate of future movement: <b>implied volatility (IV)</b>, quoted as an annual percentage. Higher IV means larger expected moves and more expensive options.</p>
        <p>The <b>expected move</b> is IV converted into price: the range that price stays within about <b>68% of the time</b> (one standard deviation, 1σ). A useful rule of thumb: IV ÷ 16 is roughly the one-day move in percent, because 16 ≈ √252 trading days.</p>
        <p>GEX PRO calculates it precisely from the at-the-money IV of the expiration that closes the session, using the exact time remaining.</p>`,
      points: ["IV is quoted per year; divide by 16 for a rough daily %.", "±1σ contains price about 68% of the time, ±2σ about 95%.", "Higher IV = wider expected ranges."],
      example: `ES at 7,600 with IV of 16%: 16 ÷ 16 = 1% per day, about ±76 points. On roughly two sessions in three, ES closes within that range.`,
      gex: ["levels", "The expected move is on the Levels page"],
      quiz: {q: "IV is 32%. Roughly what daily move does that imply?", choices: ["0.5%", "2%", "32%"], answer: 1, why: "32 ÷ 16 = 2%, the rule-of-thumb one-day move."}}),
    L({id: "iv-bands", chapter: "vol", title: "IV range bands", minutes: 3,
      oneLiner: "Price levels set by implied volatility: ±1σ and ±2σ for the day, the week and the monthly expiry.",
      body: `{{d:bands}}<p>The indicator turns implied volatility into price levels. Each band is centred on the <b>previous close</b> and uses the at-the-money IV of its own expiration:</p>
        <ul><li><b>D</b>: today's session. <b>W</b>: through this week's last expiry. <b>M</b>: through the monthly expiry (third Friday).</li><li><b>±1σ</b>: price ends inside about 68% of the time. <b>±2σ</b>: about 95% of the time.</li></ul>
        <p>Price reaching a 1σ band means the move is already as large as the market priced in; a 2σ band is a stretched, less common move. Bands that coincide with a gamma level form a stronger zone.</p>`,
      points: ["D, W and M bands each use their own expiry's IV.", "1σ ≈ 68% containment, 2σ ≈ 95%.", "Bands overlapping gamma levels show as confluence."],
      example: `NQ closed at 29,950 with today's ATM IV at 25%: about ±393 points at 1σ (29,557 to 30,343) and ±786 at 2σ.`,
      gex: ["indicator", "Turn bands on under IV range bands in the indicator"],
      quiz: {q: "Price reaches the D+2σ band. How unusual is that?", choices: ["Common: about half of all days", "Uncommon: roughly a 1-in-20 move", "Impossible"], answer: 1, why: "±2σ contains price about 95% of the time, so reaching it is roughly a 1-in-20 outcome."}}),
    L({id: "term-structure", chapter: "vol", title: "Term structure", minutes: 3,
      oneLiner: "Implied volatility across expirations: usually rising with time, inverted when near-term risk is in demand.",
      body: `{{d:term}}<p>Longer-dated options usually carry <b>higher IV</b> than near-dated ones, because more can happen over more time: an <b>upward-sloping</b> curve, typical of calm markets.</p>
        <p>When near-term IV rises <b>above</b> longer-term IV, the curve is <b>inverted</b>: traders are paying up for protection now. Inversion together with negative gamma often comes before large moves.</p>
        <p>A bump at a single date usually marks a scheduled event such as CPI, a Fed decision or major earnings. On GEX PRO, the gap between the D, W and M IV bands gives a quick view of the curve.</p>`,
      points: ["Normal: upward-sloping. Stress: inverted.", "Single-date bumps mark scheduled events.", "Compare the D, W and M band IVs for a quick read."],
      example: `ATM IV of 14% for next week and 17% for next month is normal. If next week rises to 22% while next month stays at 17%, the curve is inverted.`,
      quiz: {q: "Near-term IV is above longer-term IV. The curve is...", choices: ["Normal", "Inverted", "Flat"], answer: 1, why: "An inverted curve has the front higher than the back, usually because of near-term risk."}}),
    L({id: "skew", chapter: "vol", title: "Skew", minutes: 3,
      oneLiner: "Downside puts usually trade at higher implied volatility than upside calls; the difference is the skew.",
      body: `{{d:skew}}<p>Investors pay for crash protection, so out-of-the-money <b>puts</b> trade at higher IV than equally distant <b>calls</b>. A common measure is <b>25-delta put IV minus 25-delta call IV</b>, in volatility points.</p>
        <p><b>Rising skew</b> means demand for protection is increasing. <b>Falling skew</b> suggests complacency, or a rally in which protection is being sold.</p>
        <p>GEX PRO does not plot skew directly; it matters here because it explains why put-side gamma and put walls are often larger than their call-side counterparts.</p>`,
      points: ["Equity index skew is normally put-rich.", "Rising skew = more demand for protection.", "Skew explains why put walls are often heavy."],
      example: `25-delta put IV of 20% and 25-delta call IV of 15% gives a skew of 5 points. If it climbs to 8 while the index is flat, protection is being bought.`,
      quiz: {q: "Skew rises while price is flat. What might it mean?", choices: ["Traders are buying downside protection", "Calls are becoming expensive", "Nothing"], answer: 0, why: "Higher skew means puts are becoming relatively more expensive: rising demand for protection."}}),
    // ---------------------------------------------------------------- 5. the GEX PRO levels
    L({id: "ranked-levels", chapter: "levels", title: "Ranked levels: C, P and Ab", minutes: 4,
      oneLiner: "The strongest positive-gamma, negative-gamma and total-gamma strikes near price, numbered by strength.",
      body: `<p>Beyond the single call and put walls, the indicator ranks the strikes that matter most near price:</p>
        <ul><li><b>C1–C7</b>: the strikes with the most <b>positive net GEX</b>, strongest first. C1 is the main call-side concentration; if price moves through it, the next C level often takes over.</li><li><b>P1–P7</b>: the strikes with the most <b>negative net GEX</b>. P1 is the main put-side concentration; below it, hedging can speed up selling.</li><li><b>Ab1–Ab3</b>: the strikes with the most <b>total gamma</b>, sign ignored. They often act as magnets.</li></ul>
        <p>Neighbouring strikes are combined so levels sit at real strikes, at least one band apart (about 40 points on NQ, 10 on ES). The <b>strength bar</b> beside each tag shows its share of gamma relative to the strongest level, and weaker levels are drawn more lightly.</p>`,
      points: ["C = positive net GEX, P = negative net GEX, Ab = total gamma.", "1 is the strongest in each group.", "The strength bar compares each level with the strongest one shown."],
      example: `A tag reading "▬▬▬▬▬▬ C1  Ab2" at 29,800 means it is both the strongest positive-gamma strike and the second-largest total-gamma strike: a significant level.`,
      gex: ["indicator", "Copy the indicator and today's paste"],
      quiz: {q: "What does P1 mark?", choices: ["The strongest call strike", "The strike with the most negative net GEX", "The previous close"], answer: 1, why: "P levels rank negative net GEX; P1 is the largest of them."}}),
    L({id: "first-expiry", chapter: "levels", title: "First expiry and standalone levels", minutes: 3,
      oneLiner: "Intraday levels come from the nearest expiration, and for NQ usually from QQQ's own strikes.",
      body: `<p>By default the indicator ranks C, P and Ab levels from the <b>first expiry</b>: today's 0DTE options during the session, or the next expiry when none expire today. Their gamma sits close to price, so they produce many nearby, intraday-relevant levels. "All expirations" ranks every expiry out to 45 days instead, giving fewer, larger levels further away.</p>
        <p>The default <b>auto</b> choice uses whichever chain holds most of that expiry's gamma:</p>
        <ul><li><b>NQ</b>: usually <b>QQQ standalone</b>. QQQ's 0DTE options outweigh NDX's, and levels sit on QQQ's own $1 strikes, about 41 NQ points apart.</li><li><b>ES</b>: usually <b>SPX + SPY</b>, because SPX's 0DTE gamma is several times SPY's.</li></ul>
        <p>The hover box always names the source, for example "QQQ standalone · first expiry 0DTE".</p>`,
      points: ["First expiry = today's 0DTE (or the next expiry).", "NQ: usually QQQ standalone. ES: usually SPX + SPY.", "Before the open, levels use yesterday's closing data."],
      example: `With an NQ/QQQ ratio of 41.28, QQQ strikes 720, 721 and 722 map to NQ at about 29,722, 29,763 and 29,804.`,
      gex: ["indicator", "Change 'Ranked from' in the indicator settings"],
      quiz: {q: "Why are NQ intraday levels about 41 points apart?", choices: ["It is a fixed setting", "They sit on QQQ's $1 strikes, about 41 NQ points each", "NQ futures only trade every 41 points"], answer: 1, why: "In standalone mode the levels are QQQ strikes converted to NQ, and one QQQ dollar is about 41 NQ points."}}),
    L({id: "gamma-zones", chapter: "levels", title: "Gamma zones and confluence", minutes: 4,
      oneLiner: "The ranked levels and the gamma flip divide the chart into zones with different hedging behaviour.",
      body: `{{d:zones}}<ul><li><b>Positive Gamma Zone</b>: from the gamma flip up to C1. Call-dominated gamma; hedging dampens moves.</li><li><b>Positive Gamma Extension Zone</b>: from C1 up to the next call level. Above C1 hedging pressure eases.</li><li><b>Negative Gamma Zone</b>: from P1 up to the gamma flip. Put-dominated gamma; hedging adds to moves.</li><li><b>Negative Gamma Extension Zone</b>: from P1 down to the next put level. Below P1 hedging adds to selling.</li></ul>
        <p>A level on the edge between two zones is a <b>boundary</b>, and the hover box says so. When several levels sit at or near the same price, that is <b>confluence</b>, shown as ●● dots: two levels is moderate, three strong, four or more very strong. Stacked levels make a more significant reaction zone.</p>`,
      points: ["Zones are measured from the gamma flip, C1 and P1.", "Boundaries between zones are natural decision points.", "More ● dots = more levels stacked = a stronger zone."],
      example: `C1 and Ab2 at 29,800 with the flip at 29,470: 29,800 is a boundary between the Positive Gamma Zone below it and the Positive Gamma Extension Zone above it, with two-level confluence.`,
      gex: ["indicator", "Hover any tag on the chart for its zone"],
      quiz: {q: "A tag shows ●●●. What does it mean?", choices: ["Three levels converge there", "The level is three days old", "Three trades occurred there"], answer: 0, why: "The dots count the levels at or near that price; three is strong confluence."}}),
    // ---------------------------------------------------------------- 6. using GEX PRO
    L({id: "indicator-setup", chapter: "use", title: "Setting up the TradingView indicator", minutes: 3,
      oneLiner: "Install the script once, then paste fresh levels from the website when you want an update.",
      body: `<ol><li>On the <b>Indicator</b> page, click <b>Copy code</b>. In TradingView open the Pine Editor, paste, and click Save, then add it to an NQ or ES chart.</li><li>On the website click <b>Copy for TradingView</b>. In the indicator's settings, open <b>Levels payload</b>, select all, paste, and click OK. One paste serves both NQ and ES charts.</li><li>A new paste is published every hour. TradingView scripts cannot download data, so the levels change only when you paste again.</li></ol>
        <p>If the levels are older than the stale limit (90 minutes by default), the tags and panel show <b>STALE</b>. When the script itself changes, copy the code again; the Indicator page lists recent changes.</p>`,
      points: ["Install the code once; paste levels as often as you like.", "One paste covers NQ and ES.", "STALE means it is time for a fresh paste."],
      example: `Before the open: copy the 9:00 paste, replace the old one in the settings, and the chart redraws with the morning's levels.`,
      gex: ["indicator", "Open the Indicator page"],
      quiz: {q: "Why don't the levels update on their own in TradingView?", choices: ["They are fixed for the week", "TradingView scripts cannot download data, so you paste updates", "It is a paid feature"], answer: 1, why: "Pine scripts cannot make web requests, so new levels arrive by pasting the latest update."}}),
    L({id: "heatmap", chapter: "use", title: "Reading the heatmap", minutes: 3,
      oneLiner: "Futures candles with dealer gamma painted behind them, snapshot by snapshot.",
      body: `<p>Each column behind the candles is a GEX snapshot; each band shows net dealer gamma at that price at that time. <b>Blue</b> is positive gamma (hedging tends to slow price there); <b>orange</b> is negative gamma (hedging tends to add to moves). Brighter means more gamma.</p>
        <p>The call wall (blue line) and put wall (orange line) are drawn where they held for an hour or more; the ZG, CW and PW labels on the price axis show the current values.</p>
        <p>Use it to see how price behaved at the gamma bands earlier in the session, and how those bands shifted as positioning changed.</p>`,
      points: ["Blue = positive gamma, orange = negative, brighter = stronger.", "Each column is one snapshot in time.", "Hover anywhere for the exact value at that price and time."],
      example: `Price stalls three times under a bright blue band during the morning: a positive-gamma level absorbing buying.`,
      gex: ["heatmap", "Open the Heatmap"],
      quiz: {q: "What does a bright orange band mean?", choices: ["Strong positive gamma", "Strong negative gamma", "High volume"], answer: 1, why: "Orange is negative gamma, and brightness shows its size."}}),
    L({id: "index-drivers", chapter: "use", title: "Index drivers: the stocks behind NQ and ES", minutes: 3,
      oneLiner: "A handful of the largest companies account for much of each index's daily move.",
      body: `<p>The Nasdaq-100 and S&P 500 are weighted by company size, so the largest names account for a large share of each index. The Screener ranks them by <b>index weight</b> and estimates each stock's contribution to the future's move:</p>
        <p class="lib-formula">points ≈ index weight × the stock's % move × the futures price</p>
        <p>The page also shows pre-market and after-hours moves, which point to where the future may open; relative volume (today's volume against the 3-month average); and upcoming earnings. Reports from the largest names after the close (AMC) often move NQ and ES overnight.</p>`,
      points: ["A few mega caps account for much of each index's move.", "Points contribution translates a stock's move into futures points.", "Watch pre/after-hours moves and upcoming earnings."],
      example: `NVDA at 12.4% of the Nasdaq-100 falls 0.6% with NQ at 29,100: 0.124 × 0.006 × 29,100 ≈ −21 NQ points.`,
      gex: ["screener", "Open the Screener"],
      quiz: {q: "A stock is 5% of the index and rises 2%, with the future at 30,000. Roughly how many points does it add?", choices: ["3", "30", "300"], answer: 1, why: "0.05 × 0.02 × 30,000 = 30 points."}}),
    L({id: "daily-routine", chapter: "use", title: "A trading day with GEX PRO", minutes: 4,
      oneLiner: "Know the regime, the levels and the range before the open, then manage the session around them.",
      body: `<ol><li><b>Before the open</b>: read the <b>NY AM briefing</b>. Note the regime, the gamma flip, C1 and P1, and the day's IV band. Check the calendar for data releases and the Screener for earnings and pre-market moves in the largest stocks.</li>
        <li><b>Update the chart</b>: paste the latest levels into the indicator.</li>
        <li><b>Set expectations by regime</b>. Positive gamma: moves into C levels and walls tend to stall. Negative gamma: respect breakouts; a break of P1 or the put wall can accelerate.</li>
        <li><b>During the session</b>: watch confluence zones, the D±1σ band, and how price behaves at heatmap bands. Paste again for fresher levels.</li>
        <li><b>Into the close</b>: charm and the absolute gamma strike matter most in the final hours.</li>
        <li><b>Evening</b>: the <b>Asia briefing</b> sets up the overnight session.</li></ol>`,
      points: ["Know the regime and the key levels before the open.", "Positive gamma favours fades; negative gamma favours breakouts.", "Refresh the paste during the day."],
      example: `Briefing: "ES negative gamma, P1 7,600, flip 7,750." Plan: do not fade a break of 7,600; a sustained move above 7,750 would point to calmer conditions.`,
      gex: ["briefings", "Open today's briefing"],
      quiz: {q: "Positive gamma, and price reaches C1. What is the usual expectation?", choices: ["Acceleration through it", "Stalling or fading", "A crash"], answer: 1, why: "In positive gamma, hedging leans against moves, and C1 is the heaviest call-side concentration."}}),
    L({id: "limits", chapter: "use", title: "What GEX cannot tell you", minutes: 3,
      oneLiner: "GEX models hedging pressure: valuable context, never a guarantee.",
      body: `<ul><li><b>The sign is assumed.</b> Dealer positioning is not published; GEX assumes dealers are long calls and short puts.</li><li><b>Open interest is a day old.</b> Positions opened today are not included until tomorrow.</li><li><b>The free data is delayed.</b> Cboe option quotes are about 15 minutes behind; the TradingView indicator keeps the lines aligned with live prices.</li><li><b>News outweighs levels.</b> A surprise data release or headline can move through any level.</li><li><b>Levels are zones.</b> Expect probes and overshoots around them.</li></ul>
        <p>Use GEX PRO to understand the backdrop, where hedging is likely to help or hinder a move, and combine it with your own risk management. Nothing here is investment advice.</p>`,
      points: ["Positioning is an assumption.", "Open interest is from yesterday's close.", "News can override any level."],
      example: `A put wall held for three sessions, then a hotter-than-expected inflation report sent ES straight through it. The level was real; the news was larger.`,
      quiz: {q: "Which part of GEX is an assumption rather than data?", choices: ["Open interest", "Which side dealers are on (the sign)", "The strike prices"], answer: 1, why: "Open interest and strikes are reported; dealer positioning is a modeling convention."}}),
  ];

  // [term, meaning, lesson id ("" = none), topic, where you see it]
  const glossary = [
    // ---- options basics
    ["Option", "A contract giving the right, not the obligation, to buy (call) or sell (put) at a set price until expiration.", "what-is-an-option", "Options basics", "Library"],
    ["Call", "The right to buy at the strike price before expiration.", "what-is-an-option", "Options basics", "Library, Live table"],
    ["Put", "The right to sell at the strike price before expiration.", "what-is-an-option", "Options basics", "Library, Live table"],
    ["Strike", "The fixed price an option lets you buy or sell at. Every GEX level sits at a strike (or the band around one).", "what-is-an-option", "Options basics", "Every level"],
    ["Premium", "The price paid for an option.", "what-is-an-option", "Options basics", "Library"],
    ["Expiration", "The date (and time) an option stops existing. Most index options now expire every trading day.", "what-is-an-option", "Options basics", "Live table expiry strip"],
    ["0DTE", "Options that expire today (zero days to expiration). Their gamma is concentrated tightly around price, so they drive intraday levels.", "zero-dte", "Options basics", "Indicator tags, 0D ZG / CW / PW"],
    ["Monthly expiration (OPEX)", "The standard monthly expiry on the third Friday: usually the largest open interest of the month. Quarterly ones (Mar, Jun, Sep, Dec) are bigger still.", "zero-dte", "Options basics", "M IV bands, expiry strip (M)"],
    ["AM / PM settlement", "SPX and NDX monthlies settle on the opening price (AM); weeklies and dailies settle on the close (PM).", "zero-dte", "Options basics", "Expiry strip (AM tag)"],
    ["ATM / ITM / OTM", "At, in or out of the money: whether an option would be worth anything if exercised at today's price.", "calls-and-puts", "Options basics", "Library"],
    ["Multiplier", "How many units one contract covers: 100 for stock and index options; $20 per point for NQ, $50 for ES ($2 / $5 for MNQ / MES).", "what-is-an-option", "Options basics", "Hedge sizes in contracts"],
    ["Open interest (OI)", "Contracts still open, reported once a day (as of yesterday's close). The weight behind every GEX level.", "open-interest-volume", "Options basics", "Live table Net OI, OI walls"],
    ["Volume", "Contracts traded today. Unlike open interest it updates during the session.", "open-interest-volume", "Options basics", "Live table Net volume, volume walls"],
    // ---- greeks
    ["Delta", "How much an option's price moves per $1 move in the underlying; also how much stock or futures a dealer holds to hedge it.", "delta", "Greeks", "Library"],
    ["Gamma", "How fast delta changes as price moves. Highest at the money and near expiration, which is why 0DTE gamma sits right at price.", "gamma", "Greeks", "Every GEX number"],
    ["Vega", "How much an option's price changes per 1 point of implied volatility.", "implied-volatility", "Greeks", "Library"],
    ["Vanna", "How delta changes when implied volatility changes. Falling IV usually makes dealers buy back hedges (supportive).", "vanna-charm", "Greeks", "Levels page stats (Full panel)"],
    ["Charm", "How delta changes as time passes. Drives hedging flows into the close and into expirations.", "vanna-charm", "Greeks", "Levels page stats, indicator panel"],
    ["DEX (delta exposure)", "Dealers' dollar delta at a strike: how much underlying they hold to hedge it right now.", "delta", "Greeks", "Live table Net DEX"],
    // ---- dealers
    ["Dealer / market maker", "A firm that quotes option prices and hedges to stay neutral. Their hedging is what GEX tries to model.", "dealers", "Dealers & positioning", "Library"],
    ["Hedging", "Trading the underlying (stock, ETF or futures) to cancel an option position's direction risk.", "dealers", "Dealers & positioning", "Library"],
    ["Positioning model", "The assumption that dealers are long the calls and short the puts the public trades. Real positioning is not published, so every GEX tool assumes something.", "dealers", "Dealers & positioning", "Page footnotes"],
    // ---- GEX and levels
    ["GEX (gamma exposure)", "Dealer gamma in dollars per 1% move: how much they would buy or sell to stay hedged if price moved 1%.", "what-is-gex", "GEX & levels", "Levels page, Live table"],
    ["Net GEX", "Call gamma minus put gamma, all strikes. Positive = hedging dampens moves; negative = hedging adds to them.", "what-is-gex", "GEX & levels", "Levels page, indicator panel"],
    ["Positive gamma", "Dealers long gamma: they sell rallies and buy dips to stay hedged, which calms moves and favours ranges.", "positive-negative-gamma", "GEX & levels", "Regime card, indicator panel"],
    ["Negative gamma", "Dealers short gamma: they sell into drops and buy into rallies, which extends moves and favours trend days.", "positive-negative-gamma", "GEX & levels", "Regime card, indicator panel"],
    ["Gamma regime", "Which side of zero gamma price is on: positive, negative or balanced (too close to call).", "positive-negative-gamma", "GEX & levels", "Levels page, ticker, indicator panel"],
    ["Zero gamma (gamma flip)", "The price where modeled dealer gamma flips sign. An estimate: above it hedging calms moves, below it adds to them.", "zero-gamma", "GEX & levels", "ZG tag, Levels page, heatmap axis label"],
    ["Flip zone", "The band around zero gamma where dealer gamma is close to zero and the regime can change with a small move.", "zero-gamma", "GEX & levels", "Regime card (σ distance)"],
    ["Call wall", "The strike above price with the most call gamma (all expiries). Often resistance.", "walls", "GEX & levels", "CW tag, Levels page, heatmap"],
    ["Put wall", "The strike below price with the most put gamma (all expiries). Often support.", "walls", "GEX & levels", "PW tag, Levels page, heatmap"],
    ["Absolute gamma strike", "The strike with the most total gamma, calls and puts together, sign ignored. Often a magnet.", "walls", "GEX & levels", "AG tag, Levels page"],
    ["Max pain", "The settlement price where option holders as a group would lose the most. Price is sometimes pulled toward it into expiration.", "max-pain", "GEX & levels", "MP tag, Levels page"],
    ["Largest ±GEX", "The single strikes with the most positive and the most negative net gamma.", "walls", "GEX & levels", "+GEX / -GEX tags (off by default)"],
    ["Volume / OI walls", "The strikes with the most call or put contracts traded today (volume) or open as of yesterday (OI).", "open-interest-volume", "GEX & levels", "VOL C / VOL P, OI C / OI P tags"],
    // ---- indicator levels
    ["C levels (C1-C7)", "The strongest positive net-GEX strikes near price, strongest first. C1 is the main call-side concentration; beyond it the next C level may take over.", "ranked-levels", "Indicator levels", "Indicator tags, Live table chips"],
    ["P levels (P1-P7)", "The most negative net-GEX strikes near price. P1 is the main put-side concentration; below it hedging can speed up selling.", "ranked-levels", "Indicator levels", "Indicator tags, Live table chips"],
    ["Ab levels (Ab1-Ab3)", "The strikes with the most total gamma (calls + puts combined), strongest first. Often magnets.", "ranked-levels", "Indicator levels", "Indicator tags, Live table chips"],
    ["First expiry", "The nearest expiration: today's (0DTE) during the session, otherwise the next one. The indicator's default source for C / P / Ab levels.", "first-expiry", "Indicator levels", "Indicator 'Ranked from', hover header"],
    ["Standalone (ETF only)", "Levels from the ETF's own options at its own strikes (QQQ for NQ, SPY for ES), not folded into the index. QQQ $1 strikes land about 41 NQ points apart.", "first-expiry", "Indicator levels", "Hover header, 'Ranked from'"],
    ["Confluence", "Several levels at or very near the same price. More levels stacked (shown as ●● dots) = a stronger potential reaction zone.", "gamma-zones", "Indicator levels", "● dots on tags, hover box"],
    ["Positive Gamma Zone", "From the gamma flip up to C1: call-dominated gamma, so dealer hedging dampens moves.", "gamma-zones", "Indicator levels", "Hover box zone context, green zone column"],
    ["Positive Gamma Extension Zone", "From C1 up to the next call level: above C1 hedging pressure eases off.", "gamma-zones", "Indicator levels", "Hover box zone context"],
    ["Negative Gamma Zone", "From P1 up to the gamma flip: put-dominated gamma, so dealer hedging adds to moves.", "gamma-zones", "Indicator levels", "Hover box zone context, red zone column"],
    ["Negative Gamma Extension Zone", "From P1 down to the next put level: below P1 hedging adds to selling.", "gamma-zones", "Indicator levels", "Hover box zone context"],
    ["Strength bar", "The ▬▬▬ bar beside a tag: the level's share of gamma relative to the strongest level shown.", "ranked-levels", "Indicator levels", "Indicator tags"],
    ["0DTE zero gamma / walls", "Zero gamma, call wall and put wall from today's expiring options only.", "zero-dte", "Indicator levels", "0D ZG / 0D CW / 0D PW tags"],
    // ---- volatility
    ["Implied volatility (IV)", "The market's forecast of how much price will move, backed out of option prices, as an annual %.", "implied-volatility", "Volatility", "Levels page stats, IV bands"],
    ["ATM IV", "Implied volatility at the money: the average of the call and the put at the strike nearest price. What the IV bands use.", "implied-volatility", "Volatility", "IV band hover, Levels page"],
    ["σ (standard deviation)", "One unit of expected movement. Price ends inside ±1σ about 68% of the time and inside ±2σ about 95%.", "iv-bands", "Volatility", "IV bands, regime σ distance"],
    ["Expected move", "The ±1σ range options price in for the session, from the previous close.", "implied-volatility", "Volatility", "Levels page, Bias page"],
    ["IV range bands", "Price levels set by implied volatility: ±1σ and ±2σ for the day (D), week (W) and monthly expiry (M), each from its own expiry's ATM IV.", "iv-bands", "Volatility", "D+1σ / W-2σ / M+1σ tags"],
    ["Skew", "How much more downside puts cost than upside calls, in volatility points.", "skew", "Volatility", "Library"],
    ["Term structure", "Implied volatility across expirations: usually higher further out, inverted when fear is high.", "term-structure", "Volatility", "Library"],
    ["VIX / VXN", "30-day implied volatility of the S&P 500 (VIX) and Nasdaq-100 (VXN). A quick read on the IV behind ES and NQ.", "implied-volatility", "Volatility", "Ticker"],
    // ---- futures and data
    ["NQ / ES (MNQ / MES)", "Nasdaq-100 and S&P 500 futures ($20 and $50 per point); the micros are one tenth.", "index-etf-futures", "Futures & data", "Everywhere"],
    ["Index / ETF / futures", "NDX and SPX (cash indexes), QQQ and SPY (ETFs that track them), NQ and ES (futures). Options on all of them feed the levels.", "index-etf-futures", "Futures & data", "Data chip, hover header"],
    ["Basis / carry", "Why futures trade a little above the index: interest minus dividends until the futures expire.", "index-etf-futures", "Futures & data", "Levels page reference price"],
    ["Mapping (factor)", "Converting an index level to a futures price: index level × futures/index ratio. The indicator uses the live ratio on your chart.", "index-etf-futures", "Futures & data", "Indicator panel 'Mapping'"],
    ["Reference price", "The price every level is measured against: the futures equivalent of the index's last price.", "index-etf-futures", "Futures & data", "Levels page"],
    ["RTH / Globex", "Regular trading hours (9:30-16:00 ET cash session) vs the overnight futures session.", "limits", "Futures & data", "Clock, status"],
    ["Delayed data", "Free Cboe option quotes are 15 minutes behind; open interest updates once a day. Futures prices come from Yahoo, also delayed.", "limits", "Futures & data", "Status chips"],
    // ---- site and paste
    ["Paste (levels payload)", "The text you copy from the website into the indicator's settings. Pine can't download data, so the levels change when you paste a new one.", "indicator-setup", "Site & indicator", "Copy for TradingView, Indicator page"],
    ["Scheduled paste", "A fresh paste is published every hour on the hour, and at once when its format changes.", "indicator-setup", "Site & indicator", "'Next paste' chip"],
    ["Stale", "A paste older than the stale limit (90 minutes by default). Paste a fresh one for current levels.", "indicator-setup", "Site & indicator", "Indicator tags and panel"],
    ["Heatmap", "Futures candles with dealer gamma painted behind them, snapshot by snapshot: blue positive, orange negative.", "heatmap", "Site & indicator", "Heatmap page"],
    ["Live table", "A strike ladder with net DEX, net GEX, net OI and net volume at every band near price, for the expirations you pick.", "walls", "Site & indicator", "Live table page"],
    ["Index weight", "A stock's share of the index (Nasdaq-100 or S&P 500). The biggest few move the futures.", "index-drivers", "Site & indicator", "Screener"],
    ["Points contribution", "Index weight × the stock's % move × the futures price: roughly how many NQ / ES points that stock's move is worth.", "index-drivers", "Site & indicator", "Screener"],
    ["Relative volume", "Today's volume divided by the 3-month average. 1.5× or more is unusual interest.", "open-interest-volume", "Site & indicator", "Screener"],
    ["BMO / AMC", "Earnings reported before the market opens / after the market closes. AMC reports from big names often gap NQ and ES overnight.", "index-drivers", "Site & indicator", "Screener earnings"],
    ["Track record", "Each session's plan, frozen before the 9:30 open, graded after the close. Kept forever in a public history.", "daily-routine", "Site & indicator", "Track record page"],
  ];

  // which lesson to suggest from each Explain panel
  const forHelp = {regime: "positive-negative-gamma", reference: "index-etf-futures", net_gex: "what-is-gex", stats: "vanna-charm",
    ladder: "walls", livetable: "walls", by_strike: "walls", max_pain: "max-pain", by_expiry: "zero-dte",
    bias: "daily-routine", base_case: "daily-routine", bias_range: "implied-volatility",
    bias_chart: "implied-volatility", factors: "vanna-charm", briefings: "daily-routine", calendar: "limits", posts: "limits",
    indicator: "indicator-setup", paste: "indicator-setup", heatmap: "heatmap", screener: "index-drivers", glossary: "what-is-gex"};

  return {chapters, lessons, glossary, diagrams, forHelp};
})();
