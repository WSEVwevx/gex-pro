// GEX PRO v2 Levels page: draws GEX2.levelsModel (core.js) in the racing-form look. Text only from the model: a
// number shows with its time, or its "missing" text; nothing is computed here but formatting.
(function(){
"use strict";
const G = window.GEX2, $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const num = (x, d = 2) => Number(x).toLocaleString("en-US", {minimumFractionDigits: d, maximumFractionDigits: d});
const ET = {timeZone: "America/New_York"};
const etTime = iso => iso ? new Date(iso).toLocaleTimeString("en-US", {...ET, hour: "2-digit", minute: "2-digit", hour12: false}) + " ET" : "";
const etDay = iso => iso ? new Date(iso).toLocaleDateString("en-US", {...ET, weekday: "short", day: "numeric", month: "short"}) : "";
const TONE = {pos: "--call", neg: "--put", zg: "--flip", ag: "--abs", em: "--em"};
const REGIME = {POSITIVE: ["Positive gamma", "moves tend to fade"], NEGATIVE: ["Negative gamma", "moves can extend"],
  INDETERMINATE: ["Indeterminate", "the model cannot call the side"]};
const store = {get(k, d){ try { return localStorage.getItem(k) || d; } catch(e){ return d; } }, set(k, v){ try { localStorage.setItem(k, v); } catch(e){} }};
let market = store.get("gex.market", "NQ") === "ES" ? "ES" : "NQ", all = null, err = "", paste = null, stamp = null;

function row(k, body, cls = ""){ return `<section class="row ${cls}"><div class="sc k">${k}</div><div>${body}</div></section>`; }
const miss = why => `<span class="nc">${esc(why)}</span>`;

function render(){
  const M = all ? G.levelsModel(all, market, Date.now()) : null;
  const sw = ["NQ", "ES"].map(m => `<a href="#" data-m="${m}"${m === market ? ' aria-current="true"' : ""}>${m}</a>`).join("");
  const th = document.documentElement.dataset.theme;
  const tw = ["dark", "light"].map(t => `<a href="#" data-t="${t}"${t === th ? ' aria-current="true"' : ""}>${t[0].toUpperCase() + t.slice(1)}</a>`).join("");
  const h = [`<header class="mast"><span class="t">GEX · Levels</span><span class="sw">${sw}</span><span class="sw">${tw}</span>
    <span class="sc snap">${M && M.built ? `Updated ${esc(etDay(M.built))}, ${esc(etTime(M.built))}` : err ? "" : "loading…"}</span></header>`];
  if(!M || M.missing){
    h.push(`<section class="state"><div class="sc k">Source</div><div>${miss(err || (M && M.missing) || "loading the latest reading…")}</div></section>`);
    $("app").innerHTML = h.join(""); bind(); return;
  }
  const S = M.source;
  h.push(`<section class="state"><div class="sc k">Source</div><div>${S.backup
    ? `<b class="hl">Backup estimate, not Cboe data.</b> ${esc(S.note || "")}`
    : `<b>${esc(S.provider || "")} data</b> (${esc(S.kind || "")})`}
    ${S.warnings.length ? `<div class="w">${S.warnings.map(esc).join(" · ")}</div>` : ""}</div></section>`);
  h.push('<div class="form"><div>');
  // 1. price vs zero gamma
  const Z = M.levels.ZG, D = M.zgDistance, P = M.price;
  h.push(row(`${esc(market)} vs zero gamma`, D.missing ? `<div class="v2">${miss(D.missing)}</div>`
    : `<div class="big">${num(D.v)}<span class="u">pts ${D.side}</span></div>
       <div class="cap"><span class="tick" style="background:var(--flip)"></span>Zero gamma <span class="n">${num(Z.v)}</span>${Z.modelled ? ' <span class="dim">(modelled)</span>' : ""}
       · price <span class="n">${num(P.v)}</span> at ${esc(etTime(P.at))}</div>`, "hero"));
  // 2. nearer wall
  const W = M.nearerWall;
  h.push(row("Nearer wall", W.missing ? `<div class="v2">${miss(W.missing)}</div>`
    : `<div class="v2"><span class="tick" style="background:var(${W.name === "Call wall" ? "--call" : "--put"})"></span><span class="lv">${W.name} ${num(W.v)}</span>, ${num(W.d)} ${W.side}</div>${W.only ? '<div class="s">the only wall in this reading</div>' : ""}`));
  // 3. regime
  const R = REGIME[M.regime.v] || [M.regime.v, ""];
  h.push(row("Regime", M.regime.missing ? miss(M.regime.missing) : `<div class="v2">${esc(R[0])}</div><div class="s">${esc(R[1])}</div>`));
  // 4. freshness
  h.push(row("Levels as of", `<div class="v2">${esc(etDay(M.asof))}, ${esc(etTime(M.asof))}</div><div class="s">${M.ageMin != null ? esc(G.age(M.ageMin)) + " ago" : ""}${S.backup ? ' · <span class="hl">estimate</span>' : ""}</div>`));
  // 5. the paste
  const T = M.paste;
  h.push(row("TradingView paste", T.missing ? miss(T.missing)
    : `<div class="pline"><button class="copy" id="copy" type="button">Copy paste</button><span><b>${esc(etDay(T.at))}, ${esc(etTime(T.at))}</b> <span class="dim">(${esc(T.slot)} slot)</span></span></div>
       ${T.onHold ? `<div class="pnote"><span class="hl">On hold, ${esc(G.age(T.ageMin))} old.</span> Backup estimates are not pasted, so it still carries the levels of that slot${T.zg != null ? ` (zero gamma ${num(T.zg)})` : ""}.${T.next ? ` Next attempt ${esc(T.next)} ET.` : ""}</div>` : ""}`));
  h.push("</div>");
  // the ladder
  const t = [`<table class="lad"><caption><span class="sc">Ladder, ${esc(market)} futures prices</span> <span class="dim">· as of ${esc(etTime(M.asof))}</span></caption>
    <thead><tr><th></th><th>Level</th><th class="r">Price</th><th class="r">From price</th></tr></thead><tbody>`];
  let placed = false;
  const now = () => `<tr class="now"><td class="m"></td><td>Price</td><td class="r">${P.missing ? "–" : num(P.v)}</td><td class="r d">${P.missing ? "" : esc(etTime(P.at))}</td></tr>`;
  for(const r of M.ladder){
    if(!placed && !P.missing && r.v < P.v){ t.push(now()); placed = true; }
    const near = !W.missing && r.name === W.name;
    t.push(`<tr${near ? ' class="near"' : ""}><td class="m"><i style="background:var(${TONE[r.tone]})"></i></td><td>${esc(r.name)}${near ? '<span class="tag">NEARER WALL</span>' : ""}${r.k === "SH" || r.k === "SL" ? `<span class="tag">exp ${esc(M.sigma.exp || "")}</span>` : ""}</td>
      <td class="r p">${num(r.v)}</td><td class="r d">${P.missing ? "" : num(Math.abs(r.v - P.v)) + (r.v >= P.v ? " above" : " below")}</td></tr>`);
  }
  if(!placed) t.push(now());
  for(const n of M.notCovered) t.push(`<tr class="nc"><td class="m"></td><td>${esc(n.name)}</td><td class="r nc" colspan="2">${esc(n.why)}</td></tr>`);
  t.push("</tbody></table>");
  h.push(`<div>${t.join("")}</div></div>`);
  h.push('<footer class="foot"><span>v2 preview, beside the main site</span><a href="../">Main site</a><span>Information only, not advice.</span></footer>');
  $("app").innerHTML = h.join("");
  bind();
}

function bind(){
  document.querySelectorAll("[data-m]").forEach(a => a.onclick = e => { e.preventDefault(); market = a.dataset.m; store.set("gex.market", market); render(); });
  document.querySelectorAll("[data-t]").forEach(a => a.onclick = e => { e.preventDefault(); document.documentElement.dataset.theme = a.dataset.t; store.set("gex.theme", a.dataset.t); render(); });
  const c = $("copy");
  // the text is fetched with the reading, so the click writes it at once (a write after an await can be refused)
  if(c) c.onclick = () => {
    const done = ok => { c.textContent = ok ? "Copied" : "Copy failed: use the main site's Indicator page"; setTimeout(() => { c.textContent = "Copy paste"; }, 2000); };
    if(!paste || !navigator.clipboard){ done(false); return; }
    navigator.clipboard.writeText(paste).then(() => done(true), () => done(false));
  };
}

const fresh = url => fetch(url + (G.URLS.stamp ? (url.includes("?") ? "&" : "?") + "t=" + Date.now() : ""), {cache: "no-store"});
async function load(){
  try {
    if(G.URLS.stamp && all){                     // hosted: a few bytes say whether a new reading exists
      const s = (await (await fresh(G.URLS.stamp)).text()).trim();
      if(s === stamp) return;
      stamp = s;
    }
    all = await (await fresh(G.URLS.all)).json(); err = "";
    try { paste = (await (await fresh(G.URLS.paste)).text()).trim() || null; } catch(e){ paste = null; }
  } catch(e){ err = all ? "" : "The latest reading could not load. Check your connection; it tries again every minute."; }
  render();
}
load();
setInterval(load, 60 * 1000);
})();
