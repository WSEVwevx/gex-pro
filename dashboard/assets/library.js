// GEX PRO Library: a beginner's course on options, dealer hedging and gamma exposure.
// Content only (the page that shows it is in app.js). Lessons: {id, chapter, title, minutes, oneLiner,
// body (HTML; {{d:name}} inserts a diagram), example, gex: [page, label], quiz: {q, choices, answer, why}}.
window.GEX_LIBRARY = (() => {
  const chapters = [
    ["basics", "1. Options basics"],
    ["dealers", "2. Dealers and the Greeks"],
    ["gex", "3. Gamma exposure (GEX)"],
    ["vol", "4. Volatility"],
    ["use", "5. Using GEX PRO"],
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
    // ---------------------------------------------------------------- 1. basics
    L({id: "what-is-an-option", chapter: "basics", title: "What is an option?", minutes: 3,
      oneLiner: "A contract that gives you the right, not the obligation, to buy or sell something at a fixed price before a set date.",
      body: `<p>An option is like a <b>reservation</b>. You pay a small fee now (the <b>premium</b>) to lock in a price (the <b>strike</b>) until a date (the <b>expiration</b>). If the deal becomes good for you, you use it. If not, you walk away and only lose the fee.</p>
        <p>There are two kinds:</p><ul><li>A <b>call</b> is the right to <b>buy</b> at the strike. You want price to go <b>up</b>.</li><li>A <b>put</b> is the right to <b>sell</b> at the strike. You want price to go <b>down</b>, or you use it as insurance.</li></ul>
        <p>One standard stock or ETF option covers <b>100 shares</b>. That number is the <b>multiplier</b>.</p>{{d:payoff_call}}`,
      example: `SPY trades at $600. You buy a 610 call for $2 ($200 total, because ×100). If SPY finishes at $620, the call is worth $10 ($1,000): you made $800. If SPY finishes below $610, it expires worthless and you lose the $200.`,
      gex: ["levels", "See today's strikes on the Levels page"],
      quiz: {q: "You think the market might drop and want insurance. Which option fits?", choices: ["A call", "A put", "Neither"], answer: 1, why: "A put gains value as price falls, which is why investors buy puts as protection."}}),
    L({id: "calls-and-puts", chapter: "basics", title: "Calls and puts, side by side", minutes: 3,
      oneLiner: "Calls profit when price rises above the strike; puts profit when price falls below it.",
      body: `<p>The chart in the last lesson showed a call. Here is a put: it is the mirror image.</p>{{d:payoff_put}}
        <p>Words you'll see everywhere:</p><ul><li><b>In the money (ITM)</b>: the option already has value. A call with price above its strike, a put with price below.</li><li><b>At the money (ATM)</b>: the strike is right at the current price.</li><li><b>Out of the money (OTM)</b>: no value yet. It needs a move to pay off.</li></ul>
        <p>Every option has a <b>buyer</b> and a <b>seller</b>. The buyer's loss is limited to the premium. The seller collects the premium but takes the risk. That seller is very often a professional <b>dealer</b>, which is what the rest of this course is about.</p>`,
      example: `With SPX at 6,000: the 6,100 call and the 5,900 put are both out of the money. The 6,000 call and put are at the money. The 5,900 call is in the money by 100 points.`,
      quiz: {q: "SPX is 6,000. Is the 5,800 put in, at, or out of the money?", choices: ["In the money", "At the money", "Out of the money"], answer: 2, why: "A put pays when price is below the strike. 6,000 is above 5,800, so it has no value yet: out of the money."}}),
    L({id: "open-interest-volume", chapter: "basics", title: "Open interest vs volume", minutes: 2,
      oneLiner: "Volume is how many contracts traded today; open interest is how many are still open.",
      body: `<p><b>Volume</b> counts every contract that changed hands today, and it resets each morning. <b>Open interest (OI)</b> counts contracts that are still alive: opened and not yet closed or expired.</p>
        <p>OI is reported <b>once a day</b> (by the clearing house, after the close), so it's yesterday's picture. Volume moves all day.</p>
        <p>GEX uses open interest because hedging depends on positions that <b>still exist</b>. GEX PRO also shows <b>volume walls</b>, where today's trading is concentrated, as a live complement.</p>`,
      example: `A strike with 50,000 OI and 2,000 volume is a big, settled position. A strike with 1,000 OI but 30,000 volume today is where new money is fighting right now.`,
      gex: ["levels", "Volume and OI walls are on the Levels page (filter: Volume & OI)"],
      quiz: {q: "Which number updates during the trading day?", choices: ["Open interest", "Volume", "Both"], answer: 1, why: "Volume counts trades as they happen; open interest is published once a day."}}),
    L({id: "index-etf-futures", chapter: "basics", title: "SPX, SPY, ES and NDX, QQQ, NQ", minutes: 3,
      oneLiner: "They track the same markets in different sizes, so their options levels line up.",
      body: `<p>The S&P 500 index can be traded three main ways: <b>SPX</b> (the index itself, options only), <b>SPY</b> (an ETF, about one tenth of SPX) and <b>ES</b> (futures contracts). The Nasdaq-100 has <b>NDX</b>, <b>QQQ</b> (about one forty-first of NDX) and <b>NQ</b> futures.</p>
        <p>Futures trade slightly above the index because of <b>carry</b>: interest minus dividends until the futures expire. GEX PRO measures that gap and converts every level into <b>futures prices</b>, so they line up with your NQ or ES chart.</p>
        <p>GEX PRO combines <b>SPX + SPY</b> options for ES and <b>NDX + QQQ</b> for NQ, so it captures most of the positioning. ETF options are scaled into index terms: about 10 SPY contracts count as one SPX contract.</p>`,
      example: `SPX 6,000 → SPY ≈ 600 → ES ≈ 6,025 (with about 25 points of carry a couple of months before expiry). A put wall at SPX 5,950 shows on your ES chart near 5,975.`,
      gex: ["levels", "The reference price card shows the index price and its futures equivalent"],
      quiz: {q: "Why does an ES level sit a little above the SPX level?", choices: ["A rounding error", "Futures carry (interest minus dividends)", "ES is a different market"], answer: 1, why: "Futures price in the cost of carry until they expire, so they trade at a small premium to the index."}}),
    // ---------------------------------------------------------------- 2. dealers and Greeks
    L({id: "dealers", chapter: "dealers", title: "Who dealers are and why they hedge", minutes: 3,
      oneLiner: "Market makers sell you options, then trade the underlying all day to stay neutral.",
      body: `<p>When you buy an option, someone sells it to you. Most often that is a <b>dealer</b> (market maker): a firm whose job is to quote prices all day and earn the spread, <b>not</b> to bet on direction.</p>
        <p>To stay neutral, dealers <b>hedge</b>: they buy or sell stocks or futures to cancel out the direction risk of the options they hold. As price moves, the risk changes, so they keep re-hedging.</p>
        <p>Because dealers are huge, their re-hedging moves markets. GEX is simply a model of <b>which way and how hard</b> they'll have to trade.</p>`,
      example: `A dealer sells you a call. If the market rises, that call gains value and the dealer loses on it. To offset that, the dealer buys some futures now, and buys more if the market keeps rising.`,
      quiz: {q: "What does a dealer mainly want?", choices: ["To bet the market goes up", "To stay neutral and earn the spread", "To bet the market goes down"], answer: 1, why: "Dealers make money from the bid-ask spread and hedge away the directional risk."}}),
    L({id: "delta", chapter: "dealers", title: "Delta: how much an option moves", minutes: 3,
      oneLiner: "Delta is how many dollars the option gains when the stock rises $1, and how much stock hedges it.",
      body: `<p>Delta runs from <b>0 to 1</b> for calls and <b>0 to −1</b> for puts. A call with delta 0.50 gains about $0.50 when the stock rises $1.</p>{{d:delta_curve}}
        <p>Delta is also the <b>hedge ratio</b>: a dealer short one call with delta 0.50 buys 50 shares (half of 100) to be neutral.</p>
        <p>As a rough guide, delta also reads like the <b>chance the option finishes in the money</b>: a 0.25-delta option is roughly a 1-in-4 shot. The Volatility page uses these 25-delta options to measure skew.</p>`,
      example: `NQ options: a call with delta 0.40 on one NQ futures contract moves about 0.40 points for each 1-point move in NQ.`,
      quiz: {q: "A call has delta 0.80. The stock rises $1. About how much does the call gain?", choices: ["$0.08", "$0.80", "$8.00"], answer: 1, why: "Delta 0.80 means about $0.80 of option value per $1 move in the stock (per share)."}}),
    L({id: "gamma", chapter: "dealers", title: "Gamma: how fast delta changes", minutes: 4,
      oneLiner: "Gamma measures how quickly delta changes, and so how much dealers must re-hedge as price moves.",
      body: `<p>Delta doesn't stay put. As price moves toward a strike, delta changes quickly; far away, it barely moves. <b>Gamma</b> is the speed of that change.</p>{{d:gamma_bell}}
        <p>Three things to remember:</p><ul><li>Gamma is <b>highest at the money</b>, near the strike.</li><li>Gamma gets <b>taller and narrower as expiration approaches</b>. Same-day (0DTE) options have enormous gamma near the strike, which is why the last hours of a session can be wild.</li><li>Calls and puts at the same strike have the <b>same gamma</b>.</li></ul>
        <p>For dealers, high gamma means <b>lots of re-hedging</b> every time price moves. That re-hedging is the force GEX PRO maps.</p>`,
      example: `An at-the-money option with gamma 0.05: delta rises from 0.50 to about 0.55 if the stock rises $1, so a dealer hedging 100 options must trade 500 more shares for that $1 move.`,
      gex: ["gamma", "See the shape of gamma on the Gamma lab"],
      quiz: {q: "Where is gamma highest?", choices: ["Deep in the money", "At the money, near expiration", "Far out of the money, far out in time"], answer: 1, why: "Gamma peaks at the strike, and the peak gets sharper as expiration nears."}}),
    L({id: "positive-negative-gamma", chapter: "dealers", title: "Positive vs negative gamma", minutes: 4,
      oneLiner: "Long gamma makes dealers trade against moves (calm); short gamma makes them trade with moves (fast).",
      body: `<p>Whether dealers <b>own</b> options (long gamma) or <b>sold</b> them (short gamma) flips the direction of their hedging:</p>{{d:hedging}}
        <p>When dealers are <b>long gamma</b>, price rising makes their position longer, so they sell; price falling makes it shorter, so they buy. They sell rips and buy dips: <b>moves get absorbed</b>.</p>
        <p>When dealers are <b>short gamma</b>, it's reversed: they buy as price rises and sell as it falls. <b>Moves feed on themselves</b>. Many of the market's sharpest days happen in negative gamma.</p>`,
      example: `Positive gamma day: ES drifts up 20 points, dealers sell into it, it fades back. Negative gamma day: ES breaks 30 points lower, dealers sell more futures to re-hedge, it drops another 40.`,
      gex: ["levels", "The regime card on Levels tells you which side we're on"],
      quiz: {q: "In negative gamma, price falls. What do dealers do?", choices: ["Buy, which slows the drop", "Sell, which adds to the drop", "Nothing"], answer: 1, why: "Short gamma dealers become longer as price falls, so they sell to re-hedge, pushing price further down."}}),
    L({id: "vanna-charm", chapter: "dealers", title: "Vanna and charm: the hidden flows", minutes: 4,
      oneLiner: "Vanna is re-hedging caused by volatility changes; charm is re-hedging caused by time passing.",
      body: `<p>Delta changes for two more reasons besides price:</p><ul><li><b>Vanna</b>: when <b>implied volatility</b> changes, option deltas change, so dealers re-hedge. A classic case is a <b>volatility crush</b> after an event (CPI, Fed): IV drops, deltas shift, and dealers often end up <b>buying</b>, which can fuel a rally.</li><li><b>Charm</b>: as <b>time passes</b>, out-of-the-money options lose delta. Dealers unwind hedges they no longer need. This "decay flow" is strongest in the <b>last hours</b> of the session and on expiration days.</li></ul>
        <p>GEX PRO turns both into futures contracts on the Levels page: <b>Charm flow per day</b> and <b>Vanna: if IV rises 1 pt</b>.</p>`,
      example: `"Charm flow: Buy 11,000 NQ" means time decay alone points toward dealers buying about 11,000 NQ contracts' worth of exposure over the day, mostly into the close.`,
      gex: ["levels", "See charm and vanna on the Levels stats strip"],
      quiz: {q: "Implied volatility collapses after a Fed decision. Which flow is that?", choices: ["Charm", "Vanna", "Neither"], answer: 1, why: "Vanna is the change in delta (and so in hedging) caused by a change in implied volatility."}}),
    // ---------------------------------------------------------------- 3. GEX
    L({id: "what-is-gex", chapter: "gex", title: "What gamma exposure (GEX) is", minutes: 4,
      oneLiner: "GEX adds up every option's gamma to estimate how many dollars dealers must trade for a 1% move.",
      body: `<p>For each option: <b>gamma × open interest × multiplier × price² × 1%</b>. Add them all up, with calls counted one way and puts the other, and you get dealers' total gamma in dollars: how much they'd buy or sell if the market moved 1%.</p>
        <p>The sign comes from an <b>assumption</b>: customers mostly <b>sell calls</b> (covered calls) and <b>buy puts</b> (protection), so dealers are assumed <b>long calls and short puts</b>. That's the common industry convention, but it's a model: real positioning can differ, especially around big events.</p>
        <p>Read GEX as a <b>map of hedging pressure</b>, not a crystal ball.</p>`,
      example: `"Net GEX −$10B per 1%" means dealers would sell roughly $10 billion of futures if the market fell 1% (and buy that much if it rose 1%): a strongly amplifying market.`,
      gex: ["levels", "Net GEX is the third card on Levels"],
      quiz: {q: "Net GEX is strongly positive. What kind of day is more likely?", choices: ["A wide trend day", "A tighter, mean-reverting day", "It says nothing about the day"], answer: 1, why: "Positive GEX means dealers trade against moves, which tends to compress the range."}}),
    L({id: "zero-gamma", chapter: "gex", title: "Zero gamma: the flip level", minutes: 3,
      oneLiner: "The price where total dealer gamma switches from positive to negative.",
      body: `<p>GEX changes as price moves. GEX PRO re-prices every option at hypothetical prices to find where the total crosses <b>zero</b>. That crossing is <b>zero gamma</b>, often called the gamma flip.</p>{{d:flip}}
        <p><b>Above</b> zero gamma, dealers tend to calm moves. <b>Below</b> it, they tend to amplify them. Price near zero gamma is in the <b>flip zone</b>: little hedging support either way, often choppy until it picks a side.</p>
        <p>The "σ" number beside it tells you how many expected moves away price is. Under 0.3σ: the regime can flip with a small move.</p>`,
      example: `NQ 29,000 with zero gamma at 29,800: price is below the flip, so negative gamma, and a rally back above 29,800 would likely calm the market.`,
      gex: ["gamma", "See the flip and the flip zone on the Gamma curve"],
      quiz: {q: "Price breaks below zero gamma. What usually changes?", choices: ["Moves tend to get faster", "Moves tend to get slower", "Nothing"], answer: 0, why: "Below zero gamma, dealers are net short gamma and their hedging adds to moves."}}),
    L({id: "walls", chapter: "gex", title: "Call wall, put wall and absolute gamma", minutes: 4,
      oneLiner: "The strikes holding the most call gamma, put gamma and total gamma.",
      body: `{{d:walls}}<ul><li><b>Call wall</b>: the strike above price with the most call gamma. Dealer hedging there tends to <b>slow rallies</b>, so it often acts as resistance.</li><li><b>Put wall</b>: the strike below price with the most put gamma. It often acts as <b>support</b>, but a clean break below it can speed up selling.</li><li><b>Absolute gamma strike</b>: the strike with the most gamma overall. Price often gets <b>pulled toward it</b> ("pinning"), especially near expiration. It doesn't depend on the long-calls-short-puts assumption.</li></ul>
        <p>Treat walls as <b>zones</b>, not exact lines. They also move as positions change during the day.</p>`,
      example: `ES 7,650 with a call wall at 8,000 and a put wall at 7,600: the range is lopsided, with support close below and resistance far above.`,
      gex: ["levels", "All walls are on the Levels ladder and chart"],
      quiz: {q: "Which level is most likely to act as a magnet near expiration?", choices: ["The call wall", "The absolute gamma strike", "The put wall"], answer: 1, why: "The biggest total gamma strike tends to pin price as hedging flows concentrate there."}}),
    L({id: "zero-dte", chapter: "gex", title: "0DTE: same-day options", minutes: 3,
      oneLiner: "Options that expire today, with huge but short-lived gamma.",
      body: `<p>SPX, SPY, NDX and QQQ now list options expiring <b>every trading day</b>. Those expiring today are <b>0DTE</b> (zero days to expiration).</p>
        <p>Their gamma near the money is enormous, so they can dominate intraday hedging. It all <b>disappears at 4 pm</b>, which is why GEX PRO shows separate <b>0DTE zero gamma and walls</b>, and why the levels can shift a lot between the morning and the afternoon.</p>`,
      example: `At 2 pm, a 0DTE call at the money can swing from worth $5 to worth $0 on a 0.5% move, and dealers hedging thousands of them must trade fast.`,
      gex: ["levels", "Filter the ladder by 0DTE on Levels"],
      quiz: {q: "What happens to 0DTE gamma at the close?", choices: ["It doubles", "It disappears", "It carries over to tomorrow"], answer: 1, why: "0DTE options expire at the close, so their gamma, and the hedging it causes, is gone."}}),
    L({id: "max-pain", chapter: "gex", title: "Max pain", minutes: 2,
      oneLiner: "The settlement price at which option holders, as a group, lose the most.",
      body: `<p>For each expiration, max pain is the price where the most open options would expire worthless. Some traders believe price drifts toward it into expiration, because of hedging flows.</p>
        <p>It's a <b>statistic, not a target</b>. Strong trends and news override it easily. It's most useful on expiration days and for 0DTE.</p>`,
      example: `Max pain 7,700 for today's ES expiration with price at 7,720: a mild pull down into the close is possible, unless something stronger is going on.`,
      quiz: {q: "Is max pain a price target?", choices: ["Yes, price always reaches it", "No, it's a statistic that news can override", "Only on Mondays"], answer: 1, why: "Max pain describes where options would lose the most; it doesn't force price there."}}),
    // ---------------------------------------------------------------- 4. volatility
    L({id: "implied-volatility", chapter: "vol", title: "Implied volatility and the expected move", minutes: 4,
      oneLiner: "Implied volatility is the market's forecast of how much price will move, priced into options.",
      body: `<p>Option prices contain an estimate of future movement: <b>implied volatility (IV)</b>, quoted as a yearly percentage. Higher IV means bigger expected swings and more expensive options.</p>
        <p>From IV you get the <b>expected move</b>: the range price stays inside about <b>two days in three</b> (one standard deviation). A quick rule of thumb: divide IV by 16 to get a typical daily move in percent (16 ≈ √252 trading days).</p>
        <p>GEX PRO computes it more precisely from the option expiring at the end of the session, using its exact time left.</p>`,
      example: `ES at 7,600 with IV 16%: 16 ÷ 16 = 1% a day, about ±76 points. About two days in three, ES closes within that range.`,
      gex: ["levels", "The expected move is on the reference card and in the ladder"],
      quiz: {q: "IV is 32%. Roughly what daily move does that imply?", choices: ["0.5%", "2%", "32%"], answer: 1, why: "32 ÷ 16 = 2%: the rule of thumb for a one-day expected move."}}),
    L({id: "term-structure", chapter: "vol", title: "Term structure", minutes: 3,
      oneLiner: "IV across expirations: normally rising with time; inverted when traders fear the near term.",
      body: `{{d:term}}<p>Usually, longer-dated options have <b>higher IV</b> (more can happen over more time): an <b>upward-sloping</b> curve, a sign of a calm market.</p>
        <p>When near-term IV rises <b>above</b> longer-term IV, the curve is <b>inverted</b>: traders are paying up for protection right now. Inversion plus negative gamma is a classic setup for big moves.</p>
        <p>Single-date bumps usually mark scheduled events: CPI, the Fed, big tech earnings.</p>`,
      example: `ATM IV 14% for next week and 17% for next month: normal. If next week jumps to 22% while next month stays 17%: inverted, stress building.`,
      gex: ["vol", "See the live curve on the Volatility page"],
      quiz: {q: "Near-term IV is above long-term IV. The curve is...", choices: ["Normal", "Inverted", "Flat"], answer: 1, why: "An inverted curve has the front higher than the back, usually because of near-term fear."}}),
    L({id: "skew", chapter: "vol", title: "Skew", minutes: 3,
      oneLiner: "Downside puts usually cost more volatility than upside calls; how much more is the skew.",
      body: `{{d:skew}}<p>Investors pay for crash protection, so out-of-the-money <b>puts</b> trade at higher IV than equally distant <b>calls</b>. GEX PRO measures skew as <b>25-delta put IV minus 25-delta call IV</b>, in volatility points.</p>
        <p><b>Rising skew</b>: demand for protection is growing. <b>Falling skew</b>: complacency, or a market squeezing higher as protection is sold.</p>`,
      example: `25-delta put IV 20%, 25-delta call IV 15%: skew = 5 points. If it climbs to 8 while the market is flat, someone is quietly buying protection.`,
      gex: ["vol", "Skew by expiration is on the Volatility page"],
      quiz: {q: "Skew jumps while price is flat. What might it mean?", choices: ["Traders are buying downside protection", "Calls are getting expensive", "Nothing at all"], answer: 0, why: "Higher skew means puts are getting relatively more expensive: rising demand for protection."}}),
    // ---------------------------------------------------------------- 5. using GEX PRO
    L({id: "daily-routine", chapter: "use", title: "A GEX PRO trading day", minutes: 4,
      oneLiner: "Read the briefing, know the regime and the levels, then trade your plan around them.",
      body: `<ol><li><b>Before the open (9:00 ET)</b>: read the <b>NY AM briefing</b>. Note the regime, zero gamma, the walls and the expected range. Check the <b>calendar</b> for data releases.</li>
        <li><b>Paste the levels</b> into TradingView: Copy for TradingView → indicator settings → Levels payload. A new paste comes every hour.</li>
        <li><b>Set your expectations by regime.</b> Positive gamma: expect fades toward the walls. Negative gamma: respect breakouts; a lost put wall can accelerate.</li>
        <li><b>Intraday</b>: watch the <b>0DTE levels</b> and the <b>volume walls</b>. Check the Gamma lab if price nears zero gamma.</li>
        <li><b>Into the close</b>: charm flow and max pain matter most in the last two hours.</li>
        <li><b>Evening (7:00 ET)</b>: the <b>Asia briefing</b> sets up the overnight session.</li></ol>`,
      example: `Briefing: "ES negative gamma, put wall 7,600, zero gamma 7,750." Plan: don't fade a break of 7,600; a reclaim of 7,750 would flip the day to calmer conditions.`,
      gex: ["briefings", "Open today's briefing"],
      quiz: {q: "It's a positive-gamma day and price runs into the call wall. What's the usual expectation?", choices: ["Acceleration through it", "Stalling or fading", "A crash"], answer: 1, why: "In positive gamma, hedging works against moves, and the call wall is where call gamma is heaviest."}}),
    L({id: "limits", chapter: "use", title: "What GEX can't tell you", minutes: 3,
      oneLiner: "GEX is a model of hedging pressure: useful context, never a guarantee.",
      body: `<ul><li><b>The sign is assumed.</b> GEX assumes dealers are long calls and short puts. Real positioning can differ.</li><li><b>Open interest is a day old.</b> New positions opened today aren't in it until tomorrow.</li><li><b>Data is 15 minutes delayed.</b> The free Cboe feed is delayed; TradingView keeps the lines aligned with live prices.</li><li><b>News beats levels.</b> A surprise CPI number or headline can blow through any wall.</li><li><b>Levels are zones.</b> Expect probes and overshoots around them.</li></ul>
        <p>Use GEX PRO to understand <b>the backdrop</b>: where hedging helps or hurts. Combine it with your own risk management. Nothing here is investment advice.</p>`,
      example: `A put wall at 7,600 held three days in a row, then a hot inflation print sent ES straight through it. The level was real, but the news was bigger.`,
      quiz: {q: "Which part of GEX is an assumption rather than data?", choices: ["Open interest", "Which side dealers are on (the sign)", "The strike prices"], answer: 1, why: "Open interest and strikes are reported; the dealer long-calls, short-puts convention is a model assumption."}}),
  ];

  const glossary = [
    ["0DTE", "Options that expire today (zero days to expiration).", "zero-dte"],
    ["Absolute gamma strike", "The strike with the most total gamma, calls and puts together. Often a magnet.", "walls"],
    ["ATM / ITM / OTM", "At, in or out of the money: whether an option already has value at today's price.", "calls-and-puts"],
    ["Call", "The right to buy at the strike price before expiration.", "what-is-an-option"],
    ["Call wall", "The strike above price with the most call gamma. Often resistance.", "walls"],
    ["Carry", "Interest minus dividends: why futures trade a little above the index.", "index-etf-futures"],
    ["Charm", "Change in delta as time passes; drives hedging flows into the close.", "vanna-charm"],
    ["Dealer / market maker", "A firm that quotes option prices and hedges to stay neutral.", "dealers"],
    ["Delta", "How much an option's price moves per $1 move in the underlying; also the hedge ratio.", "delta"],
    ["Expected move", "The ±1 standard deviation range implied by option prices (about 2 days in 3).", "implied-volatility"],
    ["Expiration", "The date (and time) an option stops existing.", "what-is-an-option"],
    ["Flip zone", "The band around zero gamma where dealer gamma is close to zero.", "zero-gamma"],
    ["Gamma", "How fast delta changes as price moves. Highest at the money near expiration.", "gamma"],
    ["GEX (gamma exposure)", "Total dealer gamma in dollars per 1% move.", "what-is-gex"],
    ["Hedging", "Trading the underlying to cancel an option position's direction risk.", "dealers"],
    ["Implied volatility (IV)", "The market's forecast of future movement, priced into options.", "implied-volatility"],
    ["Max pain", "The settlement price where option holders as a group lose the most.", "max-pain"],
    ["Multiplier", "How many units one contract covers: 100 for stock and index options, $50/$20 per point for ES/NQ futures.", "what-is-an-option"],
    ["Negative gamma", "Dealers short gamma: their hedging adds to moves.", "positive-negative-gamma"],
    ["Open interest (OI)", "Contracts still open, reported once a day.", "open-interest-volume"],
    ["Positive gamma", "Dealers long gamma: their hedging dampens moves.", "positive-negative-gamma"],
    ["Premium", "The price paid for an option.", "what-is-an-option"],
    ["Put", "The right to sell at the strike price before expiration.", "what-is-an-option"],
    ["Put wall", "The strike below price with the most put gamma. Often support.", "walls"],
    ["Skew", "How much more downside puts cost than upside calls, in volatility points.", "skew"],
    ["Strike", "The fixed price an option lets you buy or sell at.", "what-is-an-option"],
    ["Term structure", "Implied volatility across expirations.", "term-structure"],
    ["Vanna", "Change in delta when implied volatility changes.", "vanna-charm"],
    ["Volume", "Contracts traded today.", "open-interest-volume"],
    ["Zero gamma", "The price where total dealer gamma flips sign.", "zero-gamma"],
  ];

  // which lesson to suggest from each Explain panel
  const forHelp = {regime: "positive-negative-gamma", reference: "index-etf-futures", net_gex: "what-is-gex", stats: "vanna-charm",
    ladder: "walls", by_strike: "walls", max_pain: "max-pain", by_expiry: "zero-dte", gamma_curve: "zero-gamma",
    dte_buckets: "zero-dte", positioning: "what-is-gex", term: "term-structure", skew: "skew", term_table: "term-structure",
    timeline: "zero-gamma", timeline_net: "what-is-gex", bias: "daily-routine", base_case: "daily-routine", bias_range: "implied-volatility",
    bias_chart: "implied-volatility", factors: "vanna-charm", briefings: "daily-routine", calendar: "limits", posts: "limits",
    indicator: "daily-routine", paste: "daily-routine"};

  return {chapters, lessons, glossary, diagrams, forHelp};
})();
