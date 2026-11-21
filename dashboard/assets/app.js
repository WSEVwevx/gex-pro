const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
// links from outside feeds: web addresses only (a "javascript:" address would run as code when clicked)
const link = u => /^https?:[/][/]/i.test(String(u ?? "").trim()) ? esc(String(u).trim()) : "#";
const num = (x, d=2) => x == null || !isFinite(x) ? "-" : Number(x).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
const money = x => x == null || !isFinite(x) ? "-" : (x<0?"-":"+") + "$" + (Math.abs(x)>=1e9 ? num(Math.abs(x)/1e9,2)+"B" : num(Math.abs(x)/1e6,0)+"M");
const signed = (x, d=2) => x == null || !isFinite(x) ? "" : (Math.abs(x) < 0.5 * 10 ** -d ? "" : x > 0 ? "+" : "-") + num(Math.abs(x), d);   // no "-0.00"
const store = { get(k, d){ try { return localStorage.getItem(k) ?? d; } catch(e){ return d; } }, set(k, v){ try { localStorage.setItem(k, v); } catch(e){} } };

// Static mode: the hosted copy (python -m gexsys build-site) reads files that a scheduled job rewrites,
// instead of the local service's /api endpoints.
const STATIC = !!window.GEX_STATIC;
const API = STATIC ? {all: "data/all.json", news: "data/news.json", posts: "data/posts.json", indicator: "data/indicator.json", briefings: "data/briefings.json", track: "data/trackrecord.json", quotes: "data/quotes.json", positioning: "data/positioning.json", sources: "data/sources.json", pastes: "data/pastes.json", archive: "data/archive.json", studies: "data/studies.json"}
                   : {all: "/api/all", news: "/api/news", posts: "/api/posts", indicator: "/api/indicator", briefings: "/api/briefings", track: "/api/trackrecord", quotes: "/api/quotes", positioning: "/api/positioning", sources: "/api/sources", pastes: "/api/pastes", archive: "/api/archive", studies: "/api/studies"};
const pineUrl = m => STATIC ? `data/pine-published${m ? "-" + m : ""}.txt`
                            : `/api/pine/all?which=published${m ? "&market=" + encodeURIComponent(m) : ""}`;
// every data request skips the browser cache; on the hosted copy a unique query also skips GitHub's
// 10-minute CDN cache, so opening the page always gets the newest build
const fetchFresh = url => fetch(STATIC ? url + (url.includes("?") ? "&" : "?") + "t=" + Date.now() : url, {cache: "no-store"});
// a failure says what failed, what is still on screen, and that the page is retrying
const lastGood = () => data && data.now ? new Date(data.now).toLocaleTimeString("en-US", {timeZone: "America/New_York", hour: "numeric", minute: "2-digit"}) : null;
const offline = () => (STATIC ? "Can't reach the data file. " : "Can't reach the GEX service on this PC (is START.bat still running?). ")
  + (lastGood() ? `Showing the ${lastGood()} ET numbers. ` : "Nothing to show yet. ") + "Retrying by itself.";
const stateHtml = (kind, title, text) => `<div class="state ${kind}"><i></i><div><b>${esc(title)}</b>${esc(text)}</div></div>`;

if (location.protocol === "file:" && !STATIC) {
  document.body.innerHTML = `<div class="wrap"><div class="banner bad fatal">
  This page only works while the GEX PRO service is running.<br>1. Double-click <b>START.bat</b> in your Options Indicator folder.<br>
  2. Your browser opens <b>http://127.0.0.1:8765</b> automatically.</div></div>`;
  throw new Error("opened as file");
}

let data = null, market = store.get("gex.market", "NQ");

// ---------- loading without jumps: each card keeps the height it had last time on this screen width, so the data
// arriving moves nothing below it. Heights are remembered per card (and per market on the market pages).
const HKEY = "gex.h." + Math.round(innerWidth / 40);
let cardH = {};
try { cardH = JSON.parse(store.get(HKEY, "{}")) || {}; } catch(e) {}
const PER_MARKET = ["levelsView", "ladderView", "heatmapView", "screenerView", "biasView"];
const cardKey = c => { const v = c.closest("[id$=View]"); return v ? v.id + ":" + [...v.querySelectorAll(".card")].indexOf(c) + (PER_MARKET.includes(v.id) ? ":" + market : "") : null; };
// a first visit has no heights of its own yet: it reserves the usual ones (measured on the live site at 1366 and
// 375 px wide, every page re-measured 2026-11-20 after the redesign, NQ, folds closed), by page and card order. They are replaced by this device's real heights after one draw.
const DEFAULT_H = {wide: {levelsView:[207,434,102,577,571,373,373,124,124,124,1228],ladderView:[184,797,220,328,312],heatmapView:[648],screenerView:[291,370,97,679],biasView:[200,633,220,238],trackView:[259,578,635,297,272,1661,370,365,365,320],backtestView:[221,260,528,536,291,165,301,803],briefingsView:[448,292,0,0],newsView:[651,988],indicatorView:[217,217,217,67,369],libraryView:[155,628,1371],glossaryView:[5493],healthView:[1515]},
  narrow: {levelsView:[186,514,94,894,618,365,365,81,116,109,1757],ladderView:[184,892,193,320,272],heatmapView:[879],screenerView:[304,389,146,754],biasView:[332,731,393,368],trackView:[446,891,823,334,291,2528,637,384,407,359],backtestView:[464,252,566,718,385,275,312,834],briefingsView:[1029,303,0,0],newsView:[787,718],indicatorView:[252,251,254,95,980],libraryView:[317,1066,1726],glossaryView:[13616],healthView:[2870]}};
function reserve(){
  const usual = DEFAULT_H[innerWidth < 700 ? "narrow" : "wide"];
  document.querySelectorAll("[id$=View] .card").forEach(c => {
    const v = c.closest("[id$=View]"), h = cardH[cardKey(c)] || (usual[v.id] || [])[[...v.querySelectorAll(".card")].indexOf(c)];
    c.style.minHeight = h ? h + "px" : "";
  });
}
reserve();
document.body.classList.add("first");                       // cards fade in once, on the first paint only
setTimeout(() => document.body.classList.remove("first"), 600);
let settleT = 0;
function settle(){                                           // after a page has drawn: remember its cards' real heights
  clearTimeout(settleT);
  settleT = setTimeout(() => {
    const v = document.querySelector("[id$=View]:not([hidden])");
    if(!v) return;
    v.querySelectorAll(".card").forEach(c => {
      if([...c.querySelectorAll(".skeleton")].some(k => k.offsetParent)) return;     // still loading: keep the reservation
      c.style.minHeight = "";
      cardH[cardKey(c)] = Math.round(c.getBoundingClientRect().height);
    });
    store.set(HKEY, JSON.stringify(cardH));
  }, 900);
}

// ---------- motion (durations and curves: the tokens at the top of terminal.css). A number that changed counts to its
// new value; a level that really moved is marked for a few seconds. Nothing runs on the first paint, in a background
// tab, or for people who ask for reduced motion.
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const seenNum = new Map();
const numIn = t => { const m = /-?[\d,]+(?:\.\d+)?/.exec(t); return m ? {m, v: parseFloat(m[0].replace(/,/g, ""))} : null; };
function countTo(node, from, to, text){
  const hit = numIn(text), dec = (hit.m[0].split(".")[1] || "").length, t0 = performance.now(), ms = 280;
  const step = now => {
    const u = Math.min(1, (now - t0) / ms), e = 1 - (1 - u) * (1 - u);
    const v = (from + (to - from) * e).toLocaleString("en-US", {minimumFractionDigits: dec, maximumFractionDigits: dec});
    if(!node.isConnected) return;
    node.nodeValue = u < 1 ? text.slice(0, hit.m.index) + v + text.slice(hit.m.index + hit.m[0].length) : text;
    if(u < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
function showChanges(){
  const v = document.querySelector("[id$=View]:not([hidden])");
  if(!v) return;
  const calm = REDUCED || document.hidden;
  v.querySelectorAll(".big, #ladder .row .p").forEach((el, i) => {
    const node = [...el.childNodes].find(n => n.nodeType === 3 && numIn(n.nodeValue));
    if(!node) return;
    const row = el.closest(".row"), name = row ? (row.querySelector(".name") || {}).firstChild : null;
    const key = v.id + "|" + market + "|" + (row && name ? "lv:" + name.nodeValue.trim() : (el.closest("[id]") || {}).id + ":" + i);
    const text = node.nodeValue, now = numIn(text).v, was = seenNum.get(key);
    seenNum.set(key, now);
    if(was == null || was === now || calm) return;
    countTo(node, was, now, text);
    // a level row: a strike level moved if its price changed at all; zero gamma once it has moved 0.1% (the replay's rule)
    if(row && (!/zero gamma/i.test(name.nodeValue) || Math.abs(now - was) >= 0.001 * Math.abs(was))){
      row.classList.add("moved");
      const d = document.createElement("span");
      d.className = "delta"; d.textContent = (now > was ? "▲ +" : "▼ ") + (now - was).toLocaleString("en-US", {maximumFractionDigits: 2});
      el.parentNode.appendChild(d);
      setTimeout(() => { d.remove(); row.classList.remove("moved"); }, 6000);
    }
  });
}
// One view at a time ("show only"). The old on/off toggles could hide the key levels by accident.
try { localStorage.removeItem("gex.groups"); } catch(e) {}
let view = store.get("gex.view", "all");
let showTable = false;

const GROUPS = [["key","Key levels"],["odte","0DTE"],["flow","Volume & OI"],["mp","Max pain"],["range","Expected move"]];
const VIEWS = [["all","All"], ...GROUPS];
const KIND_COLOR = {ag:"var(--ag)", zg:"var(--zg)", call:"var(--pos)", put:"var(--neg)", vol:"var(--vol)", oi:"var(--oi)", mp:"var(--mp)", em:"var(--em)"};

function toast(msg){ const t=$("toast"); t.textContent=msg; t.classList.add("show"); clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("show"),3800); }
// clipboard, else the old copy command, else a box with the text selected (long code never goes through prompt())
async function copyText(text, done){
  try { await navigator.clipboard.writeText(text); toast(done); return; } catch(e) {}
  const ta = $("copyText"); ta.value = text; $("copyBox").hidden = false; ta.focus(); ta.select(); ta.scrollTop = 0;
  try { if(document.execCommand("copy")){ $("copyBox").hidden = true; toast(done); } } catch(e) {}
}
$("copyClose").onclick = () => { $("copyBox").hidden = true; };
$("copyBox").onclick = e => { if(e.target === $("copyBox")) $("copyBox").hidden = true; };
// ---------- 9:30 pastes (Backtesting page): each past session's paste as it stood at the open, for backtesting
let pastes = null, pasteWeeks = [];
async function loadPastes(){
  try { const j = await (await fetchFresh(API.pastes)).json(); pastes = j.pastes || []; pasteWeeks = j.weeks || []; renderWeeks(); }
  catch(e){ if(!pastes){ $("pastesList").innerHTML = `<div class="expl">${esc(offline())}</div>`; return; } }
  const days = [...new Set(pastes.map(p => p.session))].sort().reverse();
  const get = (d, m) => (pastes.find(p => p.session === d && p.market === m) || {}).paste;
  $("pastesSub").textContent = days.length ? `${days.length} session${days.length === 1 ? "" : "s"}` : "";
  if(!days.length){ $("pastesList").innerHTML = `<div class="expl">The first one is saved at the next 9:30 open.</div>`; return; }
  const btn = (d, which, label) => `<button class="linkbtn" data-d="${esc(d)}" data-w="${which}">${label}</button>`;
  $("pastesList").innerHTML = `<table class="trk-table paste-table"><tr><th>Session</th><th>NQ</th><th>ES</th><th>Both</th></tr>${days.map(d => `<tr>
    <td>${esc(new Date(d + "T12:00:00Z").toLocaleDateString("en-US", {weekday: "short", month: "short", day: "numeric", ...(d.slice(0, 4) === String(new Date().getFullYear()) ? {} : {year: "numeric"}), timeZone: "UTC"}))}</td>
    <td>${get(d, "NQ") ? btn(d, "NQ", "Copy") : `<span class="dim">-</span>`}</td><td>${get(d, "ES") ? btn(d, "ES", "Copy") : `<span class="dim">-</span>`}</td>
    <td>${get(d, "NQ") && get(d, "ES") ? btn(d, "both", "Copy") : `<span class="dim">-</span>`}</td></tr>`).join("")}</table>`;
  $("pastesList").querySelectorAll("button[data-d]").forEach(b => b.onclick = () => {
    const d = b.dataset.d, w = b.dataset.w, when = new Date(d + "T12:00:00Z").toLocaleDateString("en-US", {month: "short", day: "numeric", timeZone: "UTC"});
    const text = w === "both" ? [get(d, "NQ"), get(d, "ES")].join("|") : get(d, w);     // one paste for both charts, like the scheduled one
    copyText(text, `Copied the ${w === "both" ? "NQ + ES" : w} levels from the ${when} 9:30 open. Paste them into Levels payload.`);
  });
}
function renderWeeks(){
  const wks = [...new Set(pasteWeeks.map(w => w.week))];          // newest first
  const get = (wk, m) => pasteWeeks.find(w => w.week === wk && w.market === m);
  const thisMon = (() => { const t = new Date(new Date().toLocaleString("en-US", ET)); t.setDate(t.getDate() - ((t.getDay() + 6) % 7));
    return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`; })();
  const label = wk => wk === thisMon ? "This week" : "Week of " + new Date(wk + "T12:00:00Z").toLocaleDateString("en-US", {month: "short", day: "numeric", timeZone: "UTC"});
  $("weeksSub").textContent = wks.length ? `${wks.length} week${wks.length === 1 ? "" : "s"}` : "";
  if(!wks.length){ $("weeksList").innerHTML = `<div class="expl">The first week appears after the next 9:30 open.</div>`; return; }
  const btn = (wk, which, txt) => `<button class="linkbtn" data-wk="${esc(wk)}" data-w="${which}">${txt}</button>`;
  $("weeksList").innerHTML = `<table class="trk-table paste-table"><tr><th>Week</th><th>Days</th><th>NQ</th><th>ES</th><th>Both</th></tr>${wks.map(wk => { const n = get(wk, "NQ"), e = get(wk, "ES");
    return `<tr><td>${esc(label(wk))}</td><td class="m">${Math.max((n || {}).days || 0, (e || {}).days || 0)}</td><td>${n ? btn(wk, "NQ", "Copy") : `<span class="dim">-</span>`}</td>
      <td>${e ? btn(wk, "ES", "Copy") : `<span class="dim">-</span>`}</td><td>${n && e ? btn(wk, "both", "Copy") : `<span class="dim">-</span>`}</td></tr>`; }).join("")}</table>`;
  $("weeksList").querySelectorAll("button[data-wk]").forEach(b => b.onclick = () => {
    const wk = b.dataset.wk, w = b.dataset.w, text = w === "both" ? [get(wk, "NQ").paste, get(wk, "ES").paste].join("|") : get(wk, w).paste;
    copyText(text, `Copied ${label(wk).toLowerCase()}'s ${w === "both" ? "NQ + ES" : w} levels. Paste them into Levels payload, then scroll through the week.`);
  });
}
function showPastes(){ setPage("backtest"); }
$("indPastesJump").onclick = showPastes;
async function copyFrom(url, what){
  let text;
  try { text = (await (await fetchFresh(url)).text()).trim(); } catch(e){ toast(offline()); return; }
  if(!text){ toast("Nothing to copy yet - the first scheduled update hasn't happened."); return; }
  await copyText(text, `Copied ${what}. In TradingView: indicator settings > Levels payload > Ctrl+A, Ctrl+V > OK.`);
}
$("copyAll").onclick = () => copyFrom(pineUrl(""), "the scheduled update for NQ and ES");
// the phone's bottom bar: pages, search (the command bar over the top bar) and the paste
document.querySelectorAll("#botbar [data-p]").forEach(b => b.onclick = () => setPage(b.dataset.p));
$("bbCopy").onclick = () => $("copyAll").click();
$("bbSearch").onclick = () => { document.body.classList.add("cmd-open"); $("cmd").focus(); };
$("cmd").addEventListener("blur", () => setTimeout(() => document.body.classList.remove("cmd-open"), 150));
// a sideways swipe on the price (only there: never a table or the page row) switches NQ and ES; the buttons stay
(() => { let x0 = null, y0 = 0;
  $("lvHead").addEventListener("touchstart", e => { const t = e.touches[0]; x0 = t.clientX; y0 = t.clientY; }, {passive: true});
  $("lvHead").addEventListener("touchend", e => { if(x0 == null) return; const t = e.changedTouches[0], dx = t.clientX - x0, dy = t.clientY - y0; x0 = null;
    if(Math.abs(dx) >= 60 && Math.abs(dx) > 2 * Math.abs(dy)) setMarket(market === "NQ" ? "ES" : "NQ"); }, {passive: true});
})();
$("tableToggle").onclick = () => { showTable = !showTable; render(); };

// ---------- pages: Levels | News
let page = "levels";                                   // always open on Levels
try { localStorage.removeItem("gex.page"); } catch(e) {}
let impactF = store.get("gex.impact", "med");       // high | med | all
let curF = store.get("gex.cur", "USD");             // USD | all
let news = null;
const VIEW_IDS = ["levels", "ladder", "heatmap", "screener", "bias", "track", "backtest", "briefings", "news", "indicator", "library", "glossary", "health"];
function setPage(p){
  if(!VIEW_IDS.includes(p)) p = "levels";
  if(p !== page){ const ar = document.querySelector(".area"); if(ar) ar.scrollTop = 0; window.scrollTo(0, 0); }   // a new page opens at its top
  document.querySelectorAll("#pages button[data-p]").forEach(b => b.setAttribute("aria-selected", String(b.dataset.p === p)));
  const tab = document.querySelector(`#pages button[data-p="${p}"]`), row = $("pages");   // on a phone the page row scrolls: keep the open page in view
  if(tab && row.scrollWidth > row.clientWidth) row.scrollLeft = Math.max(0, tab.offsetLeft - (row.clientWidth - tab.offsetWidth) / 2);
  const arriving = p !== page || $(p + "View").hidden;
  VIEW_IDS.forEach(v => { $(v + "View").hidden = v !== p; });
  if(arriving){ const vw = $(p + "View"); vw.classList.remove("view-enter"); void vw.offsetWidth; vw.classList.add("view-enter"); }
  page = p;
  settle();
  $("pageTitle").textContent = (PAGES.find(x => x[0] === p) || ["", "Levels"])[1];
  $("tabs").hidden = $("status").hidden = NO_MARKET_PAGES.includes(p);
  $("density").hidden = $("phaseLab").hidden = p !== "levels";
  document.querySelectorAll("#botbar [data-p]").forEach(b => b.dataset.p === p ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"));
  $("explain").classList.contains("open") && openExplain(PAGE_HELP[p] || "regime");
  if(p === "briefings") loadBriefings();
  if(p === "news") renderNews();
  if(p === "indicator") loadIndicator();
  if(p === "backtest"){ loadPastes(); loadArchive(); loadStudies(); }
  if(p === "library") renderLibrary();
  if(p === "glossary") renderGlossary();
  if(p === "track") loadTrack();
  if(p === "health") loadSources();
  if(p === "screener") loadScreener();
  if(p === "heatmap" && window.__hmOpen) window.__hmOpen();
  if(!NO_MARKET_PAGES.includes(p) && data) render();
  $("explainTab").title = "Explain this page (X)";
}
document.querySelectorAll("#pages button[data-p]").forEach(b => b.onclick = () => setPage(b.dataset.p));
async function loadNews(){
  try { news = await (await fetchFresh(API.news)).json(); }
  catch(e) { news = news || {events: [], error: offline()}; }
  renderNews(); if(data) render();
}
const ET = {timeZone: "America/New_York"};
const dur = ms => { const m = Math.max(0, Math.round(ms/60000)); return m < 60 ? `${m}m` : m < 1440 ? `${Math.floor(m/60)}h ${m%60}m` : `${Math.floor(m/1440)}d ${Math.floor(m%1440/60)}h`; };
const etTime = iso => new Date(iso).toLocaleTimeString("en-US", {...ET, hour:"numeric", minute:"2-digit"});
function newsFilter(e){
  const imp = {high:["High"], med:["High","Medium"], all:["High","Medium","Low","Holiday"]}[impactF] || ["High"];
  return imp.includes(e.impact) && (curF === "all" || e.country === curF);
}
// next high-impact USD event, else the next medium one (some weeks have no high-impact USD events)
// ---------- Trump posts (Truth Social)
let posts = null, postF = store.get("gex.postf", "all");      // all | market
async function loadPosts(){
  try { posts = await (await fetchFresh(API.posts)).json(); }
  catch(e) { posts = posts || {posts: [], error: offline()}; }
  renderPosts();
}
function renderPosts(){
  $("postF").innerHTML = [["all","All"],["market","Market-related"]].map(([k, t]) => `<button role="tab" aria-selected="${postF === k}" data-k="${k}">${t}</button>`).join("");
  [...$("postF").children].forEach(b => b.onclick = () => { postF = b.dataset.k; store.set("gex.postf", postF); renderPosts(); });
  if(!posts) return;
  const list = (posts.posts || []).filter(p => postF === "all" || (p.market_words || []).length);
  const when = iso => { const t = new Date(iso); return `${ago(iso)} · ${t.toLocaleString("en-US", {...ET, weekday:"short", hour:"numeric", minute:"2-digit"})} ET`; };
  $("posts").innerHTML = list.map(p => {
    const hot = (p.market_words || []).length > 0;
    const kind = p.kind === "retruth" ? `<span class="chip">ReTruth${p.author ? " of @" + esc(p.author) : ""}</span>` : p.kind === "quote" ? `<span class="chip">Quote</span>` : "";
    const media = (p.media || [])[0];
    const counts = p.counts ? `<span>${num(p.counts.likes, 0)} likes · ${num(p.counts.retruths, 0)} ReTruths</span>` : "";
    return `<div class="post${hot ? " hot" : ""}">
      <div class="meta"><b>${when(p.time)}</b>${kind}${counts}${p.url ? `<a href="${link(p.url)}" target="_blank" rel="noopener">open</a>` : ""}</div>
      ${p.text ? `<div class="txt" role="button" tabindex="0" onclick="this.classList.toggle('open')" title="Click to expand">${esc(p.text)}</div>` : `<div class="txt c-ink3">${media ? (media.type === "video" ? "Video post" : "Image post") : "Post without text"}</div>`}
      ${media && media.preview ? `<img loading="lazy" src="${esc(media.preview)}" alt="${media.type === "video" ? "video preview" : "image"} from the post" referrerpolicy="no-referrer">` : ""}
      ${p.link && p.link.url ? `<a class="fs-base" href="${link(p.link.url)}" target="_blank" rel="noopener">${esc(p.link.title || p.link.url)}</a>` : ""}
      ${hot ? `<div class="tags">${p.tone ? `<span class="tone ${p.tone}" title="Keyword guess at what this post means for stocks, not a forecast">${p.tone}</span>` : ""}${p.market_words.map(w => `<span class="mw">${esc(w)}</span>`).join("")}</div>` : ""}
    </div>`; }).join("") || `<div class="expl">${postF === "market" ? "No recent posts mention market topics." : "No posts available."}</div>`;
  $("postsFoot").innerHTML = `Source: ${esc(posts.source || "-")}${posts.fetched_at ? `, updated ${ago(posts.fetched_at)}` : ""}; checked every 5 min. Yellow tags flag market topics (tariffs, the Fed, China, oil...); Bullish / Bearish is a keyword guess at the post's lean for stocks, shown only when it is clear. Posts can move futures quickly, and nothing here predicts how.${posts.error ? ` <span class="c-warn">${esc(posts.error)}</span>` : ""}`;
}

// ---------- Briefings page: NY AM and Asia session write-ups
let brief = null, briefPick = "";                          // "" = the newest briefing
async function loadBriefings(){
  try { brief = await (await fetchFresh(API.briefings)).json(); }
  catch(e){ $("briefTitle").textContent = "Briefings unavailable"; $("briefLead").textContent = offline(); return; }
  renderBriefings();
}
const BKIND = {nyam: "NY AM", asia: "Asia", weekly: "Weekly"};
// ---------- the five-block NY AM brief (briefings/morning.py): figures only, each block linked to the page it lives on
const B2_COL = n => /call/i.test(n) ? "var(--pos)" : /put/i.test(n) ? "var(--neg)" : /zero/i.test(n) ? "var(--zg)" : "var(--ag)";
const B2_TAG = {band: "Range", regime_range: "Regime", key_level: "Level", wall_holds: "Wall"};
const isBrief2 = b => !!b && (b.kind === "nyam" || b.kind === "asia") && b.version >= 2;
function briefMarket2(m, grades, kind){
  const col = m.regime === "POSITIVE" ? "var(--pos)" : m.regime === "NEGATIVE" ? "var(--neg)" : "var(--zg)";
  const go = (p, t) => `<button class="blink" data-go="${p}" data-m="${esc(m.market)}">${t} →</button>`;
  const r = m.range;
  let bar = "";
  if(r){                                                    // price and the three levels inside the expected range
    const lo = r.low - r.em * 0.3, hi = r.high + r.em * 0.3, at = p => Math.max(0, Math.min(100, 100 * (p - lo) / (hi - lo)));
    bar = `<div class="b2-bar" role="img" aria-label="Price and the key levels inside the expected range">
      <i class="b2-band" style="left:${at(r.low)}%;width:${at(r.high) - at(r.low)}%"></i>
      ${(m.levels || []).filter(l => l.price >= lo && l.price <= hi).map(l => `<i class="b2-tick" style="left:${at(l.price)}%;background:${B2_COL(l.name)}" title="${esc(l.name)} ${num(l.price)}"></i>`).join("")}
      <i class="b2-dot" style="left:${at(m.price)}%" title="Price ${num(m.price)}"></i></div>
      <div class="b2-ends"><span>${num(r.low)}</span><span>±${num(r.em, 0)} pts (1σ)</span><span>${num(r.high)}</span></div>`;
  }
  const g = (grades || []).filter(x => x.market === m.market);
  return `<section class="card bm b2 accent" style="--accent:${col}">
    <div class="head mb-0"><h2>${esc(m.market)}</h2><span class="chip" style="color:${col}">${esc({POSITIVE: "positive gamma", NEGATIVE: "negative gamma"}[m.regime] || "balanced gamma")}</span><span class="spacer"></span>${go("levels", "Levels")}</div>
    <div class="b2-px"><b>${num(m.price)}</b>${m.sigma == null ? "" : `<span><b style="color:${col}">${num(Math.abs(m.sigma), 1)}σ ${m.sigma >= 0 ? "above" : "below"}</b> zero gamma ${num(m.zero_gamma)}</span>`}</div>
    <p class="b2-p">${esc(m.history)} ${go("track", "Track record")}</p>
    <div class="eyebrow b2-eb">The three levels that matter</div>
    <div class="b2-lv">${(m.levels || []).map(l => `<div><i style="background:${B2_COL(l.name)}"></i><span>${esc(l.name)}<small>${esc(l.why)}</small></span><b>${num(l.price)}<em>${signed(l.dist, 1)}${l.dist_em == null ? "" : ` · ${num(l.dist_em)}σ`}</em></b></div>`).join("")}</div>
    ${bar}
    <div class="eyebrow b2-eb">${m.changes.since ? `Since ${esc(m.changes.since)}'s close` : "Since the previous close"}</div>
    <ul class="b2-ul">${m.changes.items.map(x => `<li>${esc(x)}</li>`).join("")}</ul>
    <div class="eyebrow b2-eb">${kind === "asia" ? "Last session, graded" : "Yesterday, graded"}</div>
    <p class="b2-p">${m.yesterday ? esc(m.yesterday.text) : "No earlier session in the track record yet."}</p>
    ${g.length ? `<div class="eyebrow b2-eb">This brief, graded after the close</div><div class="b2-gr">${g.map(x => `<span class="trk-tag ${x.hit ? "good" : "bad"}">${x.hit ? "✓" : "✗"} ${B2_TAG[x.type] || esc(x.type)}</span>`).join("")}</div>` : ""}
    ${m.stale ? `<div class="expl c-warn">${esc(m.stale)}</div>` : ""}</section>`;
}
// one line for where every number comes from: "NDX+QQQ (9:01 AM) and SPX+SPY (9:01 AM) options, 15-min delayed; ..."
function briefData(ms){
  const p = ms.map(m => /^(.+) options, (.+), calculated (.+) ET; (.+)$/.exec(m.data || ""));
  return p.length > 1 && p.every(x => x && x[2] === p[0][2] && x[4] === p[0][4])
    ? `${p.map(x => `${x[1]} (${x[3]} ET)`).join(" and ")} options, ${p[0][2]}; ${p[0][4]}` : ms.map(m => m.data).filter(Boolean).join(" ");
}
function briefScore(sc){
  const rows = (sc && sc.rows) || [], pct = v => v == null ? "-" : num(100 * v, 0) + "%";
  const tag = r => !r.n ? `<span class="trk-tag">not graded yet</span>` : !r.enough ? `<span class="trk-tag">${r.n} of ${sc.min} needed</span>`
    : r.flagged ? `<span class="trk-tag bad">below baseline: flagged</span>` : r.ci[0] > r.baseline ? `<span class="trk-tag good">beats baseline</span>` : `<span class="trk-tag">in line with baseline</span>`;
  return `<div class="b2-sc">${rows.map(r => `<div><span>${esc(r.label)}<small>${r.baseline == null ? "baseline depends on each level's distance" : `guessing scores ${pct(r.baseline)}`}</small></span><b>${pct(r.rate)}<small>${r.n ? `${r.k} of ${r.n}` : "no grades"}</small></b>${tag(r)}</div>`).join("")}</div>
    <div class="expl">${sc && sc.briefs ? `${sc.briefs} brief${sc.briefs > 1 ? "s" : ""} graded.` : "Grading starts after the first session closes."} A brief is frozen when written, then scored against the index's session after the close. The baseline is what guessing would score. A statement type is flagged for removal once, from ${sc ? sc.min : 20} grades on, even the top of its 95% range is below its baseline.</div>`;
}
function renderBriefings(){
  if(!brief) return;
  const latest = Object.values(brief.latest || {}).filter(Boolean).sort((a, b) => b.slot.localeCompare(a.slot));
  const b = briefPick ? (brief.by_id[briefPick] || brief.latest[briefPick]) : latest[0];
  const kindNow = b ? b.kind : null;
  $("briefKind").innerHTML = ["nyam", "asia", "weekly"].map(k => `<button role="tab" aria-selected="${kindNow === k && !String(briefPick).includes("-")}" data-k="${k}"${brief.latest[k] ? "" : " disabled"}>${BKIND[k]}</button>`).join("");
  [...$("briefKind").children].forEach(x => x.onclick = () => { briefPick = x.dataset.k; renderBriefings(); });
  $("briefPick").innerHTML = `<option value="">Earlier briefings</option>` + (brief.history || []).filter(h => brief.by_id[h.id]).map(h =>
    `<option value="${esc(h.id)}"${briefPick === h.id ? " selected" : ""}>${esc(BKIND[h.kind])} · ${new Date(h.session + "T12:00:00Z").toLocaleDateString("en-US", {weekday:"short", month:"short", day:"numeric", timeZone:"UTC"})}</option>`).join("");
  $("briefPick").onchange = e => { briefPick = e.target.value; renderBriefings(); };
  const nxt = Object.entries(brief.next || {}).filter(([, v]) => v).map(([k, v]) => `<span class="chip">Next ${BKIND[k]} <b>${new Date(v).toLocaleString("en-US", {...ET, weekday:"short", hour:"numeric", minute:"2-digit"})} ET</b></span>`).join("");
  if(!b){
    $("briefTitle").textContent = "No briefing yet";
    $("briefMeta").innerHTML = nxt; $("briefLead").textContent = "The first one is written at the next briefing time (or as soon as the app starts during a briefing window).";
    $("briefMarkets").innerHTML = ""; $("briefCal").innerHTML = ""; $("briefPosts").innerHTML = ""; return;
  }
  const weekly = b.kind === "weekly", when = o => new Date(b.session + "T12:00:00Z").toLocaleDateString("en-US", {...o, timeZone: "UTC"});
  $("briefHead").style.setProperty("--accent", b.kind === "asia" ? "var(--oi)" : "var(--pos)");
  $("briefKicker").textContent = weekly ? "The week in prices" : b.kind === "asia" ? "Night session · Asia open" : "Before the US open";
  $("briefTitle").textContent = weekly ? `${b.title} · week ending ${when({month: "short", day: "numeric"})}` : isBrief2(b) ? `${b.kind === "asia" ? "Asia brief · for" : "NY AM brief ·"} ${when({weekday: "short", month: "short", day: "numeric"})}` : `${b.title} · ${when({weekday: "long", month: "short", day: "numeric"})} session`;
  $("briefSides").hidden = weekly;      // no calendar or posts in a recap
  $("briefHead").classList.toggle("b2h", isBrief2(b));
  $("briefMeta").innerHTML = `<span class="chip">Written <b>${new Date(b.generated_at).toLocaleString("en-US", {...ET, weekday:"short", hour:"numeric", minute:"2-digit"})} ET</b></span>`
    + (b.late ? `<span class="chip" title="The app wasn't running at the scheduled time, so this was written when it started"><i class="dot warn"></i>Written late</span>` : "") + nxt
    + (b.indexes || []).map(x => `<span class="chip">${esc(x.name)} <b style="color:${x.pct > 0 ? "var(--good)" : x.pct < 0 ? "var(--bad)" : "inherit"}">${signed(x.pct, 1)}%</b></span>`).join("");
  if(b.sections) $("briefLead").innerHTML = b.sections.map(x => `<div class="bsec"><div class="eyebrow">${esc(x.title)}</div><p>${esc(x.text)}</p></div>`).join("");
  else if(isBrief2(b)) $("briefLead").textContent = "";      // the cards and the calendar say it once
  else $("briefLead").textContent = b.headline;
  $("briefNews").hidden = !(b.headlines || []).length;
  $("briefNewsList").innerHTML = (b.headlines || []).map(x => `<div class="bpost"><div class="meta"><b class="c-ink2">${esc(new Date(x.day + "T12:00:00Z").toLocaleDateString("en-US", {weekday: "short", timeZone: "UTC"}))}</b>${x.source ? `<span>${esc(x.source)}</span>` : ""}${/^https:/.test(x.url || "") ? `<a href="${link(x.url)}" target="_blank" rel="noopener">open</a>` : ""}</div>${esc(x.title)}</div>`).join("");
  const col = r => r === "POSITIVE" ? "var(--pos)" : r === "NEGATIVE" ? "var(--neg)" : "var(--zg)";
  const v2 = isBrief2(b), oneDay = v2 && b.kind === "nyam", bid = (brief.history.find(h => h.slot === b.slot && h.kind === b.kind) || {}).id;
  $("briefMarkets").innerHTML = v2 ? b.markets.map(m => briefMarket2(m, ((brief.score || {}).grades || {})[bid], b.kind)).join("")
    : (b.markets || []).map(m => `<section class="card bm accent" style="--accent:${col(m.regime)}">
    <div class="head mb-0"><h2>${esc(m.market)}</h2><span class="chip" style="color:${col(m.regime)}">${esc((m.regime || "").toLowerCase())} gamma</span></div>
    <div class="hl">${esc(m.headline)}</div>
    <div class="blv">${(m.levels || []).map(l => `<div><span>${esc(l.name)}</span><b>${num(l.price)} <span class="c-ink3 fw-500">${signed(l.price - m.price, 1)}</span></b></div>`).join("")}</div>
    ${m.range ? `<div class="bsec"><div class="eyebrow">Expected range</div><p>${esc(m.range.text)}</p></div>` : ""}
    ${m.odte ? `<div class="bsec"><div class="eyebrow">0DTE levels</div><p>${esc(m.odte)}</p></div>` : ""}
    ${m.bias ? `<div class="bsec"><div class="eyebrow">Bias</div><p>${esc(m.bias)}</p></div>` : ""}
    <div class="bsec"><div class="eyebrow">Game plan</div><p>${esc(m.plan)}</p></div>
    ${(m.changes || []).length ? `<div class="bsec"><div class="eyebrow">What changed</div>${m.changes.map(c => `<p>${esc(c)}</p>`).join("")}</div>` : ""}
    ${m.data ? `<div class="expl">${esc(m.data)}</div>` : ""}</section>`).join("");
  $("briefCal").innerHTML = (b.calendar || []).map(c => v2 && !(c.items || []).length          // an empty calendar is one line, not a section
    ? `<div class="expl" style="margin-top:${c === b.calendar[0] ? 0 : 10}px"><b class="c-ink2">${esc(c.title.replace(" (ET)", ""))}:</b> no high- or medium-impact events.</div>`
    : `<div class="head" style="margin:${c === b.calendar[0] ? 0 : 18}px 0 6px"><h2>${esc(c.title)}</h2></div>`
    + ((c.items || []).map(e => `<div class="bev${oneDay ? " today" : ""}"><span class="tm">${oneDay ? "" : esc(e.day) + " "}${esc(e.clock)}</span><span class="imp ${esc(e.impact)}">${esc(e.impact === "Medium" ? "Med" : e.impact)}</span><span>${esc(e.title)} <span class="c-ink3 mono-sm">${esc(e.country)}</span></span><span class="fp">${esc(e.detail || "")}</span></div>`).join("")
       || `<div class="expl mt-0">No high- or medium-impact events.</div>`)
    + (c.history ? `<div class="expl">${esc(c.history)}</div>` : "")).join("")
    + (v2 ? `<div class="expl">${esc(briefData(b.markets))}</div>` : "");       // where the numbers come from, once
  $("briefPostsTitle").textContent = v2 ? "How the NY AM brief has scored" : (b.posts || {}).title || "Market-moving posts";
  $("briefPosts").innerHTML = v2 ? briefScore(brief.score) : ((b.posts || {}).items || []).map(x => `<div class="bpost"><div class="meta"><b class="c-ink2">${esc(x.clock)} ET</b>${x.tone ? `<span class="tone ${esc(x.tone)}">${esc(x.tone)}</span>` : ""}${(x.words || []).map(w => `<span class="mw">${esc(w)}</span>`).join("")}${x.url ? `<a href="${link(x.url)}" target="_blank" rel="noopener">open</a>` : ""}</div>${esc(x.text)}</div>`).join("")
    || `<div class="expl mt-0">No market-related posts in this window.</div>`;
}

$("briefMarkets").addEventListener("click", e => {
  const t = e.target.closest("[data-go]");
  if(t){ if(t.dataset.m){ market = t.dataset.m; store.set("gex.market", market); } setPage(t.dataset.go); }
});

// ---------- Indicator page: the TradingView script, always the current file
const PINE_KW = new Set("if else for to by in while switch var varip true false na and or not import export method type return continue break series simple const".split(" "));
function pineHtml(line){
  const re = /(\/\/.*$)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(#[0-9a-fA-F]{6,8}\b|\b\d+(?:\.\d+)?\b)|\b([A-Za-z_]\w*)(\s*\.\s*[A-Za-z_]\w*)?(?=\s*\()|\b([A-Za-z_]\w*)\b/g;
  let out = "", last = 0, m;
  while((m = re.exec(line))){
    out += esc(line.slice(last, m.index)); last = re.lastIndex;
    if(m[1]) out += `<span class="tk-c">${esc(m[1])}</span>`;
    else if(m[2]) out += `<span class="tk-s">${esc(m[2])}</span>`;
    else if(m[3]) out += `<span class="tk-n">${esc(m[3])}</span>`;
    else if(m[4]) out += m[5] ? `<span class="tk-ns">${esc(m[4])}</span><span class="tk-f">${esc(m[5])}</span>` : (PINE_KW.has(m[4]) ? `<span class="tk-k">${esc(m[4])}</span>` : `<span class="tk-f">${esc(m[4])}</span>`);
    else out += PINE_KW.has(m[6]) ? `<span class="tk-k">${esc(m[6])}</span>` : esc(m[6]);
  }
  return out + esc(line.slice(last));
}
let ind = null, indShown = null;
async function loadIndicator(){
  let d;
  try { d = await (await fetchFresh(API.indicator)).json(); }
  catch(e){ $("indMeta").innerHTML = `<span class="chip"><i class="dot warn"></i>${offline()}</span>`; return; }
  const changed = ind && ind.version !== d.version;
  ind = d;
  if(changed) toast("The indicator code was just updated. Copy the new version into TradingView.");
  renderIndicator();
}
function renderIndicator(){
  if(!ind) return;
  const when = new Date(ind.updated);
  $("indName").textContent = ind.name;
  $("indFile").textContent = ind.filename;
  $("indMeta").innerHTML = `<span class="chip">Pine <b>v${esc(ind.pine_version)}</b></span><span class="chip">Version <b>${esc(ind.version)}</b></span>
    <span class="chip" title="${esc(when.toLocaleString("en-US", {...ET}))} ET">Updated <b>${ago(ind.updated)}</b></span>
    <span class="chip"><b>${num(ind.lines, 0)}</b> lines</span><span class="chip"><b>${num(ind.inputs, 0)}</b> settings</span>`;
  if(indShown !== ind.version){                  // re-render the (long) code only when it changed
    $("indCode").innerHTML = ind.code.split("\n").map((l, i) => `<div class="cl"><span class="ln">${i + 1}</span><span class="lc">${pineHtml(l) || " "}</span></div>`).join("");
    indShown = ind.version;
  }
  $("indChanges").innerHTML = (ind.changes || []).map(c => `<div class="change"><code>${esc(c.commit)}</code><span>${esc(c.message)}</span><span class="when">${new Date(c.date).toLocaleDateString("en-US", {...ET, month:"short", day:"numeric"})} · ${ago(c.date)}</span></div>`).join("")
    || `<div>${stateHtml("empty", "No change history here", "The list of recent script changes comes from the project's git history, which this copy was built without. The script itself is current.")}</div>`;
  const pub = data && data.workers.find(w => w.published);
  $("indPasteTime").textContent = pub ? `${slotTxt(pub.published.slot_et)} paste` : "Waiting for the first paste";
}
async function copyCode(){
  if(!ind) return;
  await copyText(ind.code, `Copied ${num(ind.lines, 0)} lines of ${ind.name} (version ${ind.version}). Paste it into TradingView's Pine Editor and click Save.`);
}
$("indCopy").onclick = copyCode;
$("indCopy2").onclick = copyCode;
$("indShow").onclick = () => { const c = $("indCode"), show = c.hidden; c.hidden = !show;
  $("indShow").textContent = show ? "Hide source" : "Show source"; $("indShow").setAttribute("aria-expanded", String(show)); };
document.querySelector(".bt-more").ontoggle = e => { if(e.target.open) renderBacktest(); };     // its charts measure their width
$("indDownload").onclick = () => {
  if(!ind) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([ind.code], {type: "text/plain"}));
  a.download = ind.filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};
$("indPaste").onclick = () => copyFrom(pineUrl(""), "the latest levels for NQ and ES");

function nextHighUSD(){
  const now = Date.now(), up = news ? (news.events || []).filter(e => e.country === "USD" && Date.parse(e.time) > now) : [];
  return up.find(e => e.impact === "High") || up.find(e => e.impact === "Medium");
}
function renderNews(){
  const opt = (id, cur, items, key) => {
    $(id).innerHTML = items.map(([k, t]) => `<button role="tab" aria-selected="${cur === k}" data-k="${k}">${t}</button>`).join("");
    [...$(id).children].forEach(b => b.onclick = () => { if(key === "imp"){ impactF = b.dataset.k; store.set("gex.impact", impactF); } else { curF = b.dataset.k; store.set("gex.cur", curF); } renderNews(); });
  };
  opt("impactF", impactF, [["high","High"],["med","High + Medium"],["all","All"]], "imp");
  opt("curF", curF, [["USD","USD"],["all","All currencies"]], "cur");
  if(!news){ return; }
  const now = Date.now(), evs = (news.events || []).filter(newsFilter);
  const next = evs.find(e => Date.parse(e.time) > now);
  let html = "", day = "";
  for(const e of evs){
    const d = new Date(e.time).toLocaleDateString("en-US", {...ET, weekday:"long", month:"short", day:"numeric"});
    if(d !== day){ day = d; html += `<div class="news-day">${esc(d)}</div>`; }
    const t = Date.parse(e.time), allDay = etTime(e.time) === "12:00 AM";
    html += `<div class="ev${t < now ? " past" : ""}${e === next ? " next" : ""}">
      <span class="tm">${allDay ? "All day" : etTime(e.time)}</span><span class="imp ${esc(e.impact)}">${esc(e.impact === "Medium" ? "Med" : e.impact)}</span>
      <span class="cur">${esc(e.country)}</span><span>${esc(e.title)}${e === next ? ` <span class="chip">in ${dur(t - now)}</span>` : ""}</span>
      <span class="fp">${e.forecast ? `F <b>${esc(e.forecast)}</b>` : ""}${e.forecast && e.previous ? " · " : ""}${e.previous ? `P <b>${esc(e.previous)}</b>` : ""}</span></div>`;
  }
  $("news").innerHTML = html || `<div class="expl">No ${impactF === "high" ? "high-impact " : impactF === "med" ? "high- or medium-impact " : ""}${curF === "all" ? "" : curF + " "}events this week. Try a wider filter above.</div>`;
  const nh = nextHighUSD();
  $("newsNext").textContent = nh ? `Next ${nh.impact === "High" ? "high" : "medium"}-impact USD: ${nh.title}, ${new Date(nh.time).toLocaleDateString("en-US", {...ET, weekday:"short"})} ${etTime(nh.time)} ET (in ${dur(Date.parse(nh.time) - now)})` : "";
  $("newsFoot").innerHTML = `Source: <a class="c-ink2" href="https://www.forexfactory.com/calendar" target="_blank" rel="noopener">ForexFactory calendar</a> (weekly export feed), checked every 30 min${news.fetched_at ? `, last updated ${ago(news.fetched_at)}` : ""}. Times in ET. F = forecast, P = previous; the feed has no actual results - see ForexFactory for those.${news.error ? ` <span class="c-warn">${esc(news.error)}</span>` : ""}`;
}

let stamp = null;
async function load(){
  try{
    // hosted: the site rebuilds every few minutes, so check its build stamp (a few bytes) before the full data file
    const st = STATIC ? await fetchFresh("data/stamp.txt").then(r => r.ok ? r.text() : null).catch(() => null) : null;
    if(!st || st !== stamp || !data){
      data = await (await (st ? fetch(`${API.all}?b=${encodeURIComponent(st)}`) : fetchFresh(API.all))).json();
      stamp = st;
    }
    if(data.calendar && data.calendar.sessions) store.set("gex.cal", JSON.stringify({sessions: data.calendar.sessions}));   // the next visit orders Levels by it
    render(); if(page === "indicator") renderIndicator();
  }
  catch(e){ $("banner").innerHTML = `<div class="banner bad">${offline()}</div>`; }
}

// ---------- data health: every outside source, when it last worked, whether its last try failed
let sources = null;
const HL = {ok: ["ok", "Working"], partial: ["warn", "Working, partly"], late: ["warn", "Late"], waiting: ["", "Not checked yet"],
            failing: ["bad", "Last try failed"], down: ["bad", "Not working"]};
// the hosted copy is only as fresh as its last build: about every 3-6 min while futures trade, hourly otherwise
const buildLag = iso => STATIC && (Date.now() - Date.parse(iso)) / 60000 > (sessionLabel(new Date())[0] === "Futures closed" ? 90 : 20);
async function loadSources(){
  try { sources = await (await fetchFresh(API.sources)).json(); }
  catch(e) { sources = sources || {sources: [], error: offline()}; }
  const bad = (sources.sources || []).some(r => r.status === "failing" || r.status === "down");     // red = failed; late stays amber
  document.querySelector('#pages button[data-p="health"]').classList.toggle("alert", !!bad);
  if(page === "health") renderSources();
}
function renderSources(){
  if(!sources){ $("hlList").innerHTML = '<div class="expl">Checking every source...</div>'; return; }
  const rows = (sources.sources || []).slice();
  if(STATIC && sources.now) rows.unshift({name: "Hosted site", provider: "GitHub Actions", pages: ["Every page"], last_ok: sources.now,
    status: buildLag(sources.now) ? "late" : "ok", detail: "Rebuilt about every 3 minutes in cash hours, every 6 minutes overnight while futures trade, and hourly when they are closed."});
  const n = rows.filter(r => !["ok", "waiting"].includes(r.status)).length, wait = rows.filter(r => r.status === "waiting").length;
  $("hlSub").textContent = sources.error || (n ? `${n} of ${rows.length} need attention` + (wait ? `, ${wait} not checked yet` : "") : wait ? `${rows.length - wait} working, ${wait} not checked yet`
    : `All ${rows.length} working`) + (sources.now ? ` · checked ${ago(sources.now)}` : "");
  const rank = {down: 0, failing: 1, late: 2, partial: 3, waiting: 4, ok: 5};          // problems first, otherwise the order stays
  rows.sort((a, b) => (rank[a.status] ?? 5) - (rank[b.status] ?? 5));
  $("hlList").innerHTML = rows.map(r => {
    const [cls, word] = HL[r.status] || ["", r.status], msg = r.error || r.note || r.detail || "";
    const when = r.last_ok ? `worked ${Date.now() - Date.parse(r.last_ok) < 60000 ? "just now" : dur(Date.now() - Date.parse(r.last_ok)) + " ago"}` : "no good copy yet";
    return `<div class="hl-row"><i class="dot ${cls}"></i><div><b>${esc(r.name)}</b><span>${esc(r.provider || "")}</span></div>
      <div><b>${esc(word)}</b><span>${esc(when)}</span></div>
      <div class="hl-msg">${esc(msg)}${(r.pages || []).length ? `<span>Used by: ${esc(r.pages.join(", "))}</span>` : ""}</div></div>`;
  }).join("");
}

function ago(iso){ const m = (Date.now() - Date.parse(iso))/60000, r = Math.round(m); return m < 1 ? "just now" : r < 60 ? `${r} min ago` : `${Math.floor(r/60)} h ${r%60} min ago`; }

function render(){
  const ws = data.workers, markets = [...new Set(ws.map(w => w.market))];
  if(!markets.includes(market)) market = markets[0];
  $("tabs").innerHTML = markets.map(m => `<button role="tab" aria-selected="${m===market}" data-m="${m}">${m}</button>`).join("");
  [...$("tabs").children].forEach(b => b.onclick = () => setMarket(b.dataset.m));
  const anyPub = ws.some(w => w.published);
  $("copyAll").disabled = !anyPub;
  $("copyAll").textContent = anyPub ? `Copy for TradingView · ${slotTxt(ws.find(w=>w.published).published.slot_et)}` : "Copy for TradingView";
  $("bbCopy").disabled = !anyPub; $("bbCopyT").textContent = anyPub ? slotTxt(ws.find(w=>w.published).published.slot_et).replace(/^[A-Z][a-z]{2}, /, "") : "not available yet";

  const w = ws.find(x => x.market === market && x.result) || ws.find(x => x.market === market);
  const h = w.health;
  const s = w.result && w.result.summary;
  // hosted copy: health was taken when the site was built, so also judge how old the build is
  const built = STATIC ? (Date.now() - Date.parse(data.now)) / 60000 : 0;
  const open = sessionLabel(new Date())[0] !== "Futures closed";          // builds every 3-6 min while open, hourly otherwise
  const lag = STATIC && built > (open ? 20 : 90);
  const svc = h.status === "ok" && !lag ? "ok" : h.status === "starting" ? "" : "warn";
  const used = (s && s.provider) || w.provider, rt = s && s.ref_quality === "RT", bk = s && s.backup;
  const opts = s ? esc(s.options_source || w.source) + (s.etf ? "+" + esc(s.etf) : "") : esc(w.source);
  $("status").innerHTML = `<span class="chip"><i class="dot ${svc}"></i>Data <b>${esc(used)}</b> · ${opts}</span>
    <span class="chip">Options <b>${bk ? "backup estimate" : rt ? "real time" : "15-min delayed"}</b></span>
    ${s ? `<span class="chip">Updated <b>${ago(s.asof)}</b></span>` : ""}
    <span class="chip"${bk ? ' title="No new TradingView paste while the levels are a backup estimate"' : ""}>Next paste <b>${bk ? "on hold" : h.next_publish_et ? esc(h.next_publish_et.slice(11)) + " ET" : "-"}</b></span>
    ${(() => { const e = nextHighUSD(); return e ? `<span class="chip" title="Next ${e.impact.toLowerCase()}-impact USD event (ForexFactory)"><i class="dot ${e.impact === "High" ? "bad" : "warn"}"></i>${esc(e.title)} <b>in ${dur(Date.parse(e.time) - Date.now())}</b></span>` : ""; })()}`;
  $("banner").innerHTML = !w.result ? `<div class="banner">${h.last_error ? "The options data source failed on its last try. Nothing to show yet; retrying by itself. Details are on the Data health page." : "First calculation in progress: levels appear within a minute."}</div>`
    : s && s.backup ? `<div class="banner backup"><b>Backup estimate.</b> Cboe is refusing requests, so these levels are an estimate from OCC open interest and VIX-family volatility (no skew). The TradingView paste keeps the last Cboe levels.<span class="bn-more"> It gives the walls, C1, P1 and zero gamma when price is near a crossing; it has no 0DTE flip and no first-expiry Ab1 or lower ranks. Details are on the Data health page.</span></div>`
    // closed market and the close's numbers already shown: a failed retry changes nothing (Data health still says so)
    : h.last_error && !h.holds_latest ? `<div class="banner" title="${esc(h.last_error)}">The options data source failed on its last try. Showing the last good numbers; retrying by itself. Details are on the Data health page.</div>`
    : lag ? `<div class="banner">The hosted data was built ${ago(data.now)}. GitHub runs the refresh on a schedule that sometimes runs late; this page picks up the next build by itself.</div>` : "";
  // old data says so on each market card, not only in the banner
  document.body.classList.toggle("stale-data", !!lag);
  document.body.classList.toggle("backup-data", !!(s && s.backup));
  document.body.style.setProperty("--stale-text", lag ? `"data from ${lastGood()} ET"` : '""');
  if(!w.result) return;
  const L = w.result.mapped || s, X = L.extras || {};
  const ref = L.futures_equiv_of_ref ?? s.ref_price;
  $("phaseLab").textContent = [phaseBase, ...calNotes(new Date(), data.calendar)].filter(Boolean).join(" · ");
  renderHero(w, s, L, X, ref);
  renderPlan(w);
  renderLevelMap(w, L, X, ref);
  loadLevelHistory();
  renderLadder(L, X, ref, !!w.result.mapped);
  renderChart(w, s, L, ref);
  renderMaxPain(X);
  renderStats(w, s, L, X);
  renderExpiry(s);
  if(page === "bias") renderBias(w);
  renderTicker();
  if(page === "ladder") renderLiveTable();
  if(page === "screener") renderScreener();
  if(page === "heatmap" && hmMarket !== market + hmTf){ hmReset = true; loadHeatmap(); }
  $("foot").innerHTML = `Model estimates from ${esc(s.provider || w.provider)} ${opts} options (${s.ref_quality === "RT" ? "real-time quotes" : "15-minute-delayed quotes"}) and end-of-day open interest, assuming dealers are long calls and short puts.
    ${w.result.mapped ? "Futures prices use " + esc(w.result.mapped.mapping.futures_ref_mode) + "; TradingView re-maps with your live chart." : esc(s.mapping_note || "")}
    These are proxy levels from index and ETF options, not NQ/ES futures options, and not trading advice.`;
}

// a paste slot ("2026-11-19 16:30" ET): the time alone if it is today's, else with its day, so an old paste never reads as today's
const slotTxt = slot => slot.slice(0, 10) === new Date().toLocaleDateString("en-CA", ET) ? `${slot.slice(11)} ET`
  : `${new Date(slot.slice(0, 10) + "T12:00:00Z").toLocaleDateString("en-US", {timeZone: "UTC", weekday: "short", month: "short", day: "numeric"})}, ${slot.slice(11)} ET`;
// the time of the price every level is measured from (after the close it is the 16:00 print, not a live quote)
const refAt = t => t ? ` · ${new Date(t).toLocaleString("en-US", {...ET, month: "short", day: "numeric", hour: "numeric", minute: "2-digit"})} ET` : "";
// The sentence under the price (redesign Phase 4): fixed templates only, never AI. Every number in it is on the page
// in the same units (the key levels' "pts above · σ"), measured from the price above it, with that price's time.
// It describes the market; it never says buy, sell, should, target or will (tests/test_sentence.py).
const SAY_GAMMA = {POSITIVE: ["modeled dealer gamma is positive", ", where hedging tends to lean against moves"],
                   NEGATIVE: ["modeled dealer gamma is negative", ", where hedging tends to add to moves"],
                   INDETERMINATE: ["modeled dealer gamma is close to balanced", ", with no clear tilt"]};
const lvPrice = v => v && typeof v === "object" ? v.price : v;
function stateSentence(o){
  // "330 pts (0.3σ) below": the same distance and σ the key-level tiles show; a level on the price reads "at"
  // from = "level": where the level is from the price; from = "price": where the price is from the level
  const gap = (v, from = "level") => { const d = Math.abs(v - o.ref), pts = num(d, 0);
    return pts === "0" ? null : `${pts} pts${o.emd ? ` (${num(d / o.emd, 1)}σ)` : ""} ${(v > o.ref) === (from === "level") ? "above" : "below"}`; };
  const [g, why] = SAY_GAMMA[o.regime] || ["modeled dealer gamma is unavailable", ""];
  const range = /\+\/-([\d.]+%)/.exec(o.zgStatus || "");
  const first = o.zg != null ? `${o.m} is ${gap(o.zg, "price") || "at"} zero gamma (${num(o.zg)}); ${g}${why}.`
    : /^NO CROSSING/i.test(o.zgStatus || "") ? `${o.m} has no zero-gamma crossing within ${range ? "±" + range[1] : "the modeled range"} of the price; ${g}${why ? " throughout that range" : ""}${why}.`
    : `Zero gamma for ${o.m} is unavailable; ${g}${why}.`;
  const wall = (name, v) => v == null ? `the ${name} is unavailable` : `the ${name}, ${num(v)}, is ${gap(v) || "at the price"}`;
  const second = wall("put wall", o.pw) + "; " + wall("call wall", o.cw) + ".";
  return (o.backup ? "Backup estimate: " : "") + first + " " + second[0].toUpperCase() + second.slice(1);
}
function renderHero(w, s, L, X, ref){
  const R = {POSITIVE:["Positive gamma","+","var(--pos)","Modeled dealers are long gamma, so their hedging leans against moves. That tends to mean tighter ranges and more mean reversion."],
             NEGATIVE:["Negative gamma","-","var(--neg)","Modeled dealers are short gamma, so their hedging follows the move. That tends to mean wider ranges and more trend days."],
             INDETERMINATE:["Balanced","~","var(--zg)","Exposure is close to balanced, or price sits near zero gamma, so there's no clear tilt either way."]}[s.regime]
             || [s.regime, "?", "var(--ink3)", "No usable estimate right now."];
  const changed = w.result.delta && w.result.delta.regime_changed;
  // distance to zero gamma measured in today's expected moves: < 0.3 means price sits right at the flip
  const zgp = L.zero_gamma && L.zero_gamma.price, emx = X.expected_move || {}, emd = emx.daily_points_fut ?? emx.daily_points;
  const sig = zgp != null && emd ? (ref - zgp) / emd : null;
  const sigTxt = sig == null ? "" : `<div class="kv mt-3"><span>Price vs zero gamma</span><b>${num(Math.abs(sig), 1)}σ ${sig >= 0 ? "above" : "below"}</b></div>
    <div class="expl mt-1">${Math.abs(sig) < 0.3 ? "Right at the flip: the regime can change with a small move." : Math.abs(sig) < 1 ? "Within one expected move of the flip." : "More than a full expected move from the flip; the regime is well established."}</div>`;
  const rc = {POSITIVE: "c-pos", NEGATIVE: "c-neg", INDETERMINATE: "c-zg"}[s.regime] || "c-ink3";
  const says = {POSITIVE: "hedging leans against moves", NEGATIVE: "moves can extend", INDETERMINATE: "no clear tilt either way"}[s.regime] || "no usable estimate";
  const mp = w.result.mapped && w.result.mapped.mapping;     // the headline is the index converted with the frozen basis
  $("lvHead").innerHTML = `<div class="lvh-px"><div class="eyebrow">${esc(market)} ${w.result.mapped ? "equiv. of " + esc(w.source) : esc(w.source)}${refAt(s.ref_time)}</div><div class="lvh-big">${num(ref)}</div>${mp ? `<div class="lvh-sub">${esc(w.source)} ${num(mp.source_ref, 2)} × basis ${num(mp.factor, 5)}, not the live futures price</div>` : ""}</div>
    <div class="lvh-rg"><div class="eyebrow"><span class="wide-only">Gamma </span>regime (model)</div><div class="lvh-regime ${rc}">${R[0]}</div>
      <div class="lvh-sub">${sig == null ? "" : `${num(Math.abs(sig), 1)}σ ${sig >= 0 ? "above" : "below"} zero gamma · `}${says}</div></div>
    <div class="lvh-net"><div class="eyebrow">Net gamma, all expiries</div><div class="lvh-mid ${s.net >= 0 ? "c-pos" : "c-neg"}">${money(s.net)}</div><div class="lvh-sub">per 1% move</div></div>
    <p class="lvh-say" id="lvSay">${esc(stateSentence({m: market, regime: s.regime, ref, zg: zgp, zgStatus: L.zero_gamma_status || s.zero_gamma_status,
      emd, cw: lvPrice(L.call_wall), pw: lvPrice(L.put_wall), backup: !!s.backup}))}</p>`;
  $("regimeCard").parentElement.classList.add("accent"); $("regimeCard").parentElement.style.setProperty("--accent", R[2]);
  $("regimeCard").innerHTML = `<div class="eyebrow">Gamma regime (model)</div>
    <div class="regime"><span class="tag" style="border-color:${R[2]}">${R[1]}</span><span style="color:${R[2]}">${R[0]}</span>${changed ? '<span class="chip">changed since last update</span>' : ""}</div>
    <div class="expl">${R[3]}</div>${sigTxt}`;
  const fop = /_FOP$/.test(w.source);                 // levels straight from CME options on the future
  $("priceCard").innerHTML = `<div class="eyebrow">Reference price${refAt(s.ref_time)}</div>
    <div class="big">${num(ref)}</div>
    <div class="kv"><span>${fop ? esc(s.underlying || market) + " future" : esc(w.source) + " close / last"}</span><b>${num(s.ref_price)}</b></div>
    <div class="expl">${fop ? "Levels come from CME options on the " + market + " future itself, so they are already in futures prices; no conversion needed."
      : w.result.mapped ? market + " equivalent of the index price, from " + (/^measured/.test(w.result.mapped.mapping.futures_ref_mode || "") ? "the measured futures / index basis" : "the carry model") + ". Your TradingView chart uses the live price." : "Options-underlying price (no futures conversion available)."}</div>`;
  $("netCard").innerHTML = `<div class="eyebrow">Net gamma exposure</div>
    <div class="big sm" style="color:${s.net>=0?"var(--pos)":"var(--neg)"}">${money(s.net)}<span class="fs-base c-ink3"> per 1% move</span></div>
    <div class="kv"><span>Expirations included</span><b>${s.basket.length} (to ${esc((s.basket.at(-1)||"").slice(5))})</b></div>
    <div class="expl">Roughly how many dollars of stock or futures dealers would trade for a 1% move. The bigger the number, the stronger the effect described on the left.</div>`;
}

function levels(L, X){
  const p = v => v && typeof v === "object" ? v.price : v;
  const n = X.nearest || {}, lab = n.label || "0DTE", em = X.expected_move || {};
  const a = em.anchor_fut ?? em.anchor, d = em.daily_points_fut ?? em.daily_points, wk = em.weekly_points_fut ?? em.weekly_points;
  const out = [
    ["key","zg","Zero gamma (est.)", p(L.zero_gamma), "Estimated price where modeled dealer gamma flips sign. Above it hedging tends to calm moves; below it hedging tends to amplify them."],
    ["key","call","Call wall", p(L.call_wall), "Strike at or above price with the most call gamma. Often watched as resistance, since hedging there can slow a rally."],
    ["key","put","Put wall", p(L.put_wall), "Strike at or below price with the most put gamma. Often watched as support; a clean break below can speed up selling."],
    ["key","call","Largest +GEX strike", p(L.max_positive), "Strike with the most positive gamma. Price often gets 'sticky' around big positive-gamma strikes."],
    ["key","put","Largest -GEX strike", p(L.max_negative), "Strike with the most negative gamma. Moves through it can accelerate."],
    ["key","ag","Absolute gamma strike", p(L.abs_gamma), "Strike with the most total gamma, calls and puts together. It often acts like a magnet, and it doesn't depend on any assumption about who holds the options."],
    ["odte","zg",`${lab} zero gamma`, p(n.zero_gamma), "The same flip point using only today's expiring options. It matters most intraday and stops mattering at the close."],
    ["odte","call",`${lab} call wall`, p(n.call_wall), "Biggest call-gamma strike above price for today's expiration. A common intraday ceiling."],
    ["odte","put",`${lab} put wall`, p(n.put_wall), "Biggest put-gamma strike below price for today's expiration. A common intraday floor."],
    ["flow","vol","Volume call wall", p(X.vol_call), "Strike above price where the most calls traded today. Shows where today's upside bets are concentrated; it moves during the session."],
    ["flow","vol","Volume put wall", p(X.vol_put), "Strike below price where the most puts traded today. Shows where today's hedging or downside bets are concentrated."],
    ["flow","oi","OI call wall", p(X.oi_call), "Strike above price with the most open calls as of yesterday's close. Large open positions that dealers may be hedging."],
    ["flow","oi","OI put wall", p(X.oi_put), "Strike below price with the most open puts as of yesterday's close."],
    ...(X.max_pain || []).slice(0, 2).map((m, i) => ["mp","mp",`Max pain ${m.expiration.slice(5)}`, m.price, i === 0 ? "Price where option holders lose the most at this expiration. Some traders watch for a drift toward it into the close; it is not a target." : "Max pain for the next expiration."]),
    ["range","em","Expected high today", a != null && d != null ? a + d : null, "One standard deviation above the previous close, priced from options. If options are priced right, about two days in three stay inside the band."],
    ["range","em","Expected low today", a != null && d != null ? a - d : null, "One standard deviation below the previous close."],
    ["range","em",`Expected high this week`, a != null && wk != null ? a + wk : null, `The same range through ${esc((em.weekly_expiry||"").slice(5))}, this week's last expiration.`],
    ["range","em","Expected low this week", a != null && wk != null ? a - wk : null, "One standard deviation below, through this week's last expiration."],
  ];
  return out.filter(x => x[3] != null && isFinite(x[3]));
}

function renderLadder(L, X, ref){
  if(!VIEWS.some(v => v[0] === view)) view = "all";
  $("filters").innerHTML = VIEWS.map(([k, t]) => `<button role="tab" aria-selected="${view === k}" data-v="${k}">${t}</button>`).join("");
  [...$("filters").children].forEach(b => b.onclick = () => { view = b.dataset.v; store.set("gex.view", view); render(); });
  const all = levels(L, X);
  const rows = all.filter(x => view === "all" || x[0] === view).sort((a, b) => b[3] - a[3]);
  // levels at the same price share one row: the first key level names it, the rest are listed under it
  const merged = [];
  for(const r of rows){
    const same = merged.find(m => Math.abs(m[0][3] - r[3]) < 0.005);
    if(same) same.push(r); else merged.push([r]);
  }
  let html = "", placed = false;
  for(const grp of merged){
    grp.sort((a, b) => (b[0] === "key") - (a[0] === "key"));
    const [g, kind, name, price] = grp[0], isKey = grp.some(x => x[0] === "key");
    if(!placed && price < ref){ html += nowRow(ref); placed = true; }
    const also = grp.slice(1).map(x => x[2]);
    html += `<div class="row${isKey ? " key" : ""}"><div class="rule" style="background:${KIND_COLOR[kind]}"></div>
      <div><div class="name">${esc(name)} ${isKey ? '<span class="badge">KEY</span>' : `<span class="kind">${esc(GROUPS.find(x => x[0] === g)[1])}</span>`}</div>${also.length ? `<div class="also">also ${also.map(esc).join(" · ")}</div>` : ""}<div class="desc">${grp.map(x => x[4]).join(" ")}</div></div>
      <div class="px"><span class="p">${num(price)}</span><span class="d">${signed(price - ref)}</span></div></div>`;
  }
  if(!placed) html += nowRow(ref);
  const missing = view === "all" || view === "key" ? KEY_NAMES.filter(n => !all.some(x => x[2] === n)) : [];
  $("ladder").innerHTML = (rows.length ? html : `<div class="expl">No levels in this group right now.</div>`)
    + (missing.length ? `<div class="expl">Not available right now: ${missing.map(esc).join(", ")}. ${KEY_WHY}</div>` : "");
}
const KEY_NAMES = ["Zero gamma (est.)", "Call wall", "Put wall", "Largest +GEX strike", "Largest -GEX strike", "Absolute gamma strike"];
const KEY_WHY = "Zero gamma is shown only when the model finds a crossing near price; a wall is missing when no strike on that side has exposure.";
const nowRow = ref => `<div class="now"><span>PRICE ${num(ref)}</span></div>`;

function renderChart(w, s, L, ref){
  const m = w.result.mapped, f = m ? (p => p*m.mapping.factor + m.mapping.offset) : (p => p);
  // window: +/-3% of price, widened to include zero gamma and both walls (up to +/-8%)
  const keys = [pickP(L.zero_gamma), pickP(L.call_wall), pickP(L.put_wall)].filter(p => p != null && Math.abs(p / ref - 1) <= 0.08);
  const win = ref * 0.03, pad = ref * 0.004;
  const lo = Math.min(ref - win, ...keys.map(p => p - pad)), hi = Math.max(ref + win, ...keys.map(p => p + pad));
  const bars =w.result.by_strike.map(b => ({p:f(b.strike), k:b.strike, net:b.net})).filter(b => b.p >= lo && b.p <= hi);
  if(showTable){
    $("chartwrap").hidden = true; $("chartTable").hidden = false; $("tableToggle").textContent = "View as chart";
    $("chartTable").innerHTML = `<table><tr><th>Price</th><th>Strike (${esc(w.source)})</th><th>Net GEX per 1%</th></tr>${bars.slice().reverse().map(b => `<tr><td class="m">${num(b.p)}</td><td class="m">${num(b.k,0)}</td><td class="m" style="color:${b.net>=0?"var(--pos)":"var(--neg)"}">${money(b.net)}</td></tr>`).join("")}</table>`;
    return;
  }
  $("chartwrap").hidden = false; $("chartTable").hidden = true; $("tableToggle").textContent = "View as table";
  const svg = $("chart"), W = Math.max($("chartwrap").clientWidth, 280), H = 440, padL = 66, padR = 150, padT = 8, padB = 8;
  const y = p => padT + (hi - p) / (hi - lo) * (H - padT - padB);
  const mx = Math.max(1, ...bars.map(b => Math.abs(b.net)));
  const cx = padL + (W - padL - padR) / 2, xs = (W - padL - padR) / 2 - 4;
  const step = bars.length > 1 ? Math.min(...bars.slice(1).map((b, i) => Math.abs(b.p - bars[i].p)).filter(d => d > 0)) : win;
  const bh = Math.max(2, Math.min(12, step / (hi - lo) * (H - padT - padB) - 2));   // 2px surface gap between bars
  let g = "";
  for(let i = 0; i <= 6; i++){ const p = lo + (hi - lo) * i / 6; g += `<line x1="${padL}" x2="${W-padR}" y1="${y(p)}" y2="${y(p)}" stroke="rgba(var(--fg-rgb),.05)"/><text x="${padL-8}" y="${y(p)+4}" text-anchor="end">${num(p,0)}</text>`; }
  g += `<line x1="${cx}" x2="${cx}" y1="${padT}" y2="${H-padB}" stroke="rgba(var(--fg-rgb),.14)"/>`;
  bars.forEach((b, i) => {
    const len = Math.abs(b.net) / mx * xs, x = b.net >= 0 ? cx : cx - len;
    g += `<rect data-i="${i}" x="${x}" y="${y(b.p) - bh/2}" width="${Math.max(len, 1)}" height="${bh}" rx="${Math.min(3, bh / 2)}" fill="${b.net>=0?"var(--pos)":"var(--neg)"}" fill-opacity=".9"/>`;
  });
  const marks = [[ref, "Price", "var(--ink)", ""], [pickP(L.zero_gamma), "Zero gamma", "var(--zg)", "5 4"],
                 [pickP(L.call_wall), "Call wall", "var(--pos)", "2 3"], [pickP(L.put_wall), "Put wall", "var(--neg)", "2 3"],
                 [pickP(L.abs_gamma), "Abs gamma", "var(--ag)", "1 3"]]
    .filter(m => m[0] != null && m[0] >= lo && m[0] <= hi);
  marks.forEach(([p, , color, dash]) => { g += `<line x1="${padL}" x2="${W-padR}" y1="${y(p)}" y2="${y(p)}" stroke="${color}" stroke-width="1.5" ${dash ? `stroke-dasharray="${dash}"` : ""}/>`; });
  // labels sorted top to bottom and pushed apart so they never overlap
  let lastY = -1e9;
  marks.slice().sort((a, b) => y(a[0]) - y(b[0])).forEach(([p, name, color]) => {
    const ly = Math.max(y(p) + 4, lastY + 14); lastY = ly;
    g += `<text x="${W-padR+8}" y="${ly}" style="fill:${color}">${name} ${num(p,0)}</text>`;
  });
  svg.setAttribute("width", W); svg.setAttribute("height", H); svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = g;
  const tip = $("tip");
  svg.onmousemove = e => {
    const r = svg.getBoundingClientRect(), py = e.clientY - r.top;
    if(!bars.length) return;
    let best = 0; bars.forEach((b, i) => { if(Math.abs(y(b.p) - py) < Math.abs(y(bars[best].p) - py)) best = i; });
    const b = bars[best];
    tip.innerHTML = `${num(b.p)} <span class="c-ink3">(${esc(w.source)} ${num(b.k,0)})</span><br><span class="${b.net>=0? "c-pos" : "c-neg"}">${money(b.net)}</span> per 1%`;
    tipAt(tip, Math.min(e.clientX - r.left + 14, W - 190), (y(b.p) - 18));
  };
  svg.onmouseleave = () => { tip.classList.remove("on"); };
}

const POINT_VALUE = {NQ: 20, MNQ: 2, ES: 50, MES: 5};        // $ per index point per futures contract
function renderStats(w, s, L, X){
  const r = X.ratios || {}, em = X.expected_move || {}, g = X.greeks || {}, d = w.result.delta, f = w.result.mapped ? w.result.mapped.mapping.factor : 1;
  const nearExp = s.basket[0], near = (s.by_expiry || {})[nearExp], lab = (X.nearest && X.nearest.label) || "Nearest";
  const fut = L.futures_equiv_of_ref ?? s.ref_price, contract = fut * (POINT_VALUE[market] || 1);    // $ notional of one contract
  const ct = usd => usd == null || !isFinite(usd) ? null : usd / contract;
  const tile = (k, v, sub, color) => `<div class="stat"><div class="eyebrow">${k}</div><div class="v"${color ? ` style="color:${color}"` : ""}>${v}</div><div class="s">${sub}</div></div>`;
  // the levels a trader looks for first: each with its distance from price
  const p = v => v && typeof v === "object" ? v.price : v, emd = em.daily_points_fut ?? em.daily_points;
  const emc = em.anchor_fut ?? fut;                     // the range's centre: the same anchor the plan, ladder and levels use
  const away = v => v == null ? "" : `${num(Math.abs(v - fut), 0)} pts ${v >= fut ? "above" : "below"}${emd ? ` · ${num(Math.abs(v - fut) / emd, 1)}σ` : ""}`;
  const key = (k, v, color, why) => tile(k, v == null ? "-" : num(v), v == null ? "unavailable" + (why ? ": " + esc(why) : "") : away(v), v == null ? "" : color);
  const zgWhy = /^NO CROSSING/i.test(L.zero_gamma_status || s.zero_gamma_status || "") ? "no crossing near price" : L.zero_gamma_status || s.zero_gamma_status || "";
  $("keyStrip").innerHTML = key("Zero gamma (est.)", p(L.zero_gamma), "var(--zg)", zgWhy) + key("Call wall", p(L.call_wall), "var(--pos)")
    + key("Put wall", p(L.put_wall), "var(--neg)")
    + tile("Expected move today", emd == null ? "-" : "±" + num(emd, 0), emd == null ? "" : `${num(emc - emd, 0)} – ${num(emc + emd, 0)} ${em.anchor_label ? "· " + esc(em.anchor_label) : "(1σ)"}`);   // ink: --em text read 4.4:1 in light
  const hedge = ct(s.net), charm = ct(g.charm_flow_usd_per_day), vanna = ct(g.vanna_usd_per_vol_pt == null ? null : -g.vanna_usd_per_vol_pt);
  const cts = x => num(Math.abs(x), 0) + " " + market;
  $("stats").innerHTML = [
    tile("Hedging per 1% move", hedge == null ? "-" : cts(hedge), hedge == null ? "" : hedge >= 0
      ? "dealers trade AGAINST a 1% move (sell rallies, buy dips), which calms price" : "dealers trade WITH a 1% move (buy rallies, sell dips), which adds fuel", hedge == null ? "" : hedge >= 0 ? "var(--pos)" : "var(--neg)"),
    tile("Charm flow per day", charm == null ? "-" : (charm >= 0 ? "Buy " : "Sell ") + cts(charm), "dealer hedging from time decay alone, strongest in the last 2 hours; can pull price toward big strikes into the close", charm == null ? "" : charm >= 0 ? "var(--pos)" : "var(--neg)"),
    tile("Vanna: if IV rises 1 pt", vanna == null ? "-" : (vanna >= 0 ? "Buy " : "Sell ") + cts(vanna), "dealer hedging if implied vol rises one point (the reverse if it falls); vol crushes after events often trigger this", vanna == null ? "" : vanna >= 0 ? "var(--pos)" : "var(--neg)"),
    tile("Zero gamma moved", !d || d.zero_gamma == null ? "-" : signed(d.zero_gamma * f) + " pts", `since the previous update${!d || d.net_change == null ? "" : "; net GEX " + money(d.net_change)}`, !d || d.zero_gamma == null ? "" : d.zero_gamma >= 0 ? "var(--pos)" : "var(--neg)"),
    tile("Put / call OI", r.pc_oi == null ? "-" : num(r.pc_oi), "open puts per open call; above 1 = more puts held"),
    tile("Put / call volume", r.pc_volume == null ? "-" : num(r.pc_volume), "puts traded per call today; jumps on hedging days"),
    tile("ATM implied vol", em.daily_iv == null ? "-" : num(em.daily_iv * 100, 1) + "%", "annualized, next expiration; higher = bigger expected swings"),
    tile(`${esc(lab)} share of gamma`, near && s.gross ? num(100 * near.abs / s.gross, 0) + "%" : "-", "how much of all gamma expires next; high = levels can shift fast"),
  ].join("");
}

const BIAS_FLIP = 0.75, GAUGE_MAX = 2;      // the score that makes a call (gexsys/bias.py), and where the gauge ends
const whole = t => t.replace(/(\d,\d{3})\.\d\d(?!\d)/g, "$1");      // index levels in a sentence, to the point
const BIAS_COLOR = {Bullish: "var(--pos)", Bearish: "var(--neg)", Neutral: "var(--zg)"};
// CFTC positioning: fetched once per page load, it only changes weekly
let cot = null, cotAsked = false;
async function loadCot(){
  if(cotAsked) return;
  cotAsked = true;
  try { cot = await (await fetchFresh(API.positioning)).json(); renderCot(); } catch(e){ cotAsked = false; }
}
function renderCot(){
  const s = ((cot || {}).markets || {})[market];
  $("cotCard").hidden = !s;
  if(!s) return;
  const when = new Date(s.asof + "T12:00:00Z").toLocaleDateString("en-US", {month: "short", day: "numeric", timeZone: "UTC"});
  $("cotSub").textContent = `${s.contract} · as of ${when}`;
  const n = v => (v > 0 ? "+" : "") + Math.round(v).toLocaleString("en-US");
  $("cotBody").innerHTML = `<table class="trk-table"><tr><th>Group</th><th>Net</th><th>Week</th><th>Rank</th><th>Reading</th></tr>
    ${s.groups.map(g => `<tr><td>${esc(g.name)}</td><td class="m">${n(g.net)}</td><td class="m">${n(g.change)}</td><td class="m"><span class="rk"><i style="width:${Math.max(0, Math.min(100, g.rank))}%"></i></span><b>${num(g.rank, 0)}%</b></td><td class="trk-mean">${esc(g.label)}</td></tr>`).join("")}</table>`;
}
// no cash session today (weekend, holiday): the card shows the latest bias and says so
const biasDay = () => sessionPhase(new Date(), data && data.calendar).phase === "no cash session today" ? "Latest bias, no session today" : "Today's bias";
function renderBias(w){
  loadCot(); renderCot();
  const b = w.result.bias, dayLab = biasDay();
  if(!b){ $("biasCard").innerHTML = `<div class="eyebrow">${dayLab}</div><div>${stateHtml("empty", "No bias yet", "It needs today's levels and an expected move. It appears with the next refresh that has both.")}</div>`; return; }
  const col = BIAS_COLOR[b.bias], ref = b.ref;
  const tm = iso => new Date(iso).toLocaleTimeString("en-US", {...ET, hour:"numeric", minute:"2-digit"});
  const card = $("biasCard").parentElement; card.classList.add("accent"); card.style.setProperty("--accent", col);
  const sg = v => (v > 0 ? "+" : v < 0 ? "\u2212" : "") + num(Math.abs(v)), at = v => 50 + 50 * Math.max(-1, Math.min(1, v / GAUGE_MAX));
  const drift = b.target - ref;
  const lean = {Bullish: "Positioning leans up.", Bearish: "Positioning leans down.", Neutral: "No directional lean."}[b.bias];
  const moves = {positive: "Moves are likely to be capped (positive gamma).", negative: "Moves are likely to extend (negative gamma)."}[b.side] || "Price is at the flip: the day type depends on which side of zero gamma it holds.";
  $("biasCard").innerHTML = `<div class="eyebrow">${dayLab} (positioning model)</div>
    <div class="bv-top">
      <div class="bv-call"><div class="regime"><span class="tag" style="border-color:${col}">${b.bias === "Bullish" ? "▲" : b.bias === "Bearish" ? "▼" : "◆"}</span><span style="color:${col}">${b.bias}</span><span class="chip">${b.confidence} confidence</span></div>
        <div class="bv-day"><span>Day type</span><b>${esc(b.day_type)}</b></div></div>
      <div class="bv-gauge" role="img" aria-label="Score ${sg(b.score)}. Bearish at ${sg(-BIAS_FLIP)} or less, bullish at ${sg(BIAS_FLIP)} or more.">
        <div class="bv-ends"><span>Bearish</span><b>Score <em style="color:${col}">${sg(b.score)}</em></b><span>Bullish</span></div>
        <div class="bv-track"><i class="neg" style="width:${at(-BIAS_FLIP)}%"></i><i class="pos" style="left:${at(BIAS_FLIP)}%"></i><u></u><b style="left:${at(b.score)}%;background:${col}"></b></div>
        <div class="bv-scale"><span style="left:${at(-BIAS_FLIP)}%">${sg(-BIAS_FLIP)}</span><span style="left:50%">0</span><span style="left:${at(BIAS_FLIP)}%">${sg(BIAS_FLIP)}</span></div>
      </div>
    </div>
    <div class="bv-line">${lean} ${moves}</div>
    <div class="bv-facts"><div><span>Base case by the close</span><b>${num(b.target, 0)}</b><em>${Math.abs(drift) < 0.5 ? "no drift expected" : signed(drift, 0) + " pts from " + num(ref, 0)}</em></div>
      <div><span>Model range</span><b>${num(b.range[0], 0)} – ${num(b.range[1], 0)}</b><em>the 1σ move ±${num(b.expected_move, 0)} pts, scaled for the gamma side</em></div></div>`;
  $("biasSummary").textContent = "";                                    // the strip above says it; replay puts its own hint here
  $("biasWhen").textContent = b.session.live ? `Session in progress · calculated ${ago(w.result.summary.asof)}` : `Plan for the ${new Date(b.session.open).toLocaleDateString("en-US", {...ET, weekday:"long", month:"short", day:"numeric"})} session`;
  const day = b.factors.filter(f => f.name === "Gamma side"), dir = b.factors.filter(f => f.name !== "Gamma side");
  $("biasFactors").innerHTML = day.map(f => `<div class="fx-day"><span>${esc(b.day_type)}</span>${esc(whole(f.why))}. This sets the day type, not the direction.</div>`).join("")
    + dir.map(f => { const c = f.score > 0 ? "var(--pos)" : f.score < 0 ? "var(--neg)" : "var(--ink3)", wd = 50 * Math.min(1, Math.abs(f.score));
      return `<div class="fx"><span class="fx-n">${esc(f.name)}</span><span class="fx-bar"><i style="width:${wd}%;${f.score < 0 ? "right" : "left"}:50%;background:${c}"></i></span><b style="color:${c}">${sg(f.score)}</b><span class="fx-why">${esc(whole(f.why))}</span></div>`; }).join("")
    + (dir.length ? `<div class="fx fx-sum"><span class="fx-n">Score</span><span class="fx-bar"></span><b style="color:${col}">${sg(b.score)}</b><span class="fx-why">The leans added up. ${sg(BIAS_FLIP)} or more is bullish, ${sg(-BIAS_FLIP)} or less is bearish, anything between is neutral.</span></div>`
      : `<div>${stateHtml("empty", "No directional factor today", "Nothing in today's positioning leans either way, so the score is 0 and the bias is neutral.")}</div>`);
  rpSync(b, col);
}

const BIAS_SHORT = {"Call wall": "CW", "Put wall": "PW", "Zero gamma": "ZG", "Abs gamma": "AG", "Max pain 0DTE": "MP", "Base case": "Base"};
const BIAS_LC = {"Call wall": "var(--pos)", "Put wall": "var(--neg)", "Zero gamma": "var(--zg)", "Abs gamma": "var(--ag)", "Max pain 0DTE": "var(--mp)"};
function drawBias(b, col){
  const svg = $("biasChart"), W = Math.max($("biasWrap").clientWidth, 280), H = 420, padT = 14, padB = 30;
  const narrow = W < 520, padL = narrow ? 50 : 70, padR = narrow ? 92 : 132;                // phones: short names, more plot
  const SHORT = BIAS_SHORT;
  const nm = n => narrow ? SHORT[n] || n : n;
  const lv = Object.entries(b.levels || {}).filter(([, p]) => Math.abs(p - b.ref) <= 1.6 * b.expected_move);
  const ys = [...b.cone.flatMap(c => [c[1], c[2]]), ...b.path.map(p => p[1]), ...b.range, ...lv.map(([, p]) => p)];
  const lo = Math.min(...ys) - b.expected_move * 0.08, hi = Math.max(...ys) + b.expected_move * 0.08, T = b.session.minutes;
  const x = m => padL + m / T * (W - padL - padR), y = p => padT + (hi - p) / (hi - lo) * (H - padT - padB);
  const open = new Date(b.session.open);
  const clock = m => new Date(open.getTime() + m * 60000).toLocaleTimeString("en-US", {...ET, hour:"numeric", minute:"2-digit"});
  let g = "";
  for(let i = 0; i <= 6; i++){ const p = lo + (hi - lo) * i / 6; g += `<line x1="${padL}" x2="${W-padR}" y1="${y(p)}" y2="${y(p)}" stroke="var(--line)"/><text x="${padL-8}" y="${y(p)+4}" text-anchor="end">${num(p,0)}</text>`; }
  const every = [60, 120, 180].find(s => (W - padL - padR) * s / T >= (narrow ? 44 : 64)) || 180;     // ticks that never collide
  for(let m = 30; m <= T; m += every){ g += `<line x1="${x(m)}" x2="${x(m)}" y1="${padT}" y2="${H-padB}" stroke="var(--line)"/><text x="${x(m)}" y="${H-10}" text-anchor="middle">${narrow ? clock(m).replace(":00", "") : clock(m)}</text>`; }
  // range band and cone
  g += `<rect x="${x(b.session.start_minute)}" y="${y(b.range[1])}" width="${x(T) - x(b.session.start_minute)}" height="${y(b.range[0]) - y(b.range[1])}" fill="${col}" opacity=".06"/>`;
  g += `<polygon points="${b.cone.map(c => `${x(c[0])},${y(c[2])}`).join(" ")} ${b.cone.slice().reverse().map(c => `${x(c[0])},${y(c[1])}`).join(" ")}" fill="${col}" fill-opacity=".1" stroke="${col}" stroke-opacity=".5" stroke-width="1"/>`;
  // key levels with collision-free labels
  const LC = BIAS_LC;
  lv.forEach(([n, p]) => { g += `<line x1="${padL}" x2="${W-padR}" y1="${y(p)}" y2="${y(p)}" stroke="${LC[n]}" stroke-width="1.3" stroke-dasharray="${n === "Zero gamma" ? "6 4" : "2 3"}"/>`; });
  // levels at the same (rounded) price share one label: "Put wall · Abs gamma 7,021"
  const merged = list => Object.values(list.reduce((acc, [n, p]) => {
    const k = num(p, 0);
    (acc[k] = acc[k] || {p, names: [], color: LC[n]}).names.push(n);
    return acc;
  }, {}));
  const fits = t => t.length * 6.4 <= padR - 12;          // ~6.4 px a character at the chart's 11 px font
  const named = (names, p) => { const t = `${names.map(nm).join(" · ")} ${num(p,0)}`; return fits(t) ? t : `${names.map(n => SHORT[n] || n).join(" · ")} ${num(p,0)}`; };
  const labels = [...merged(lv).map(m => [m.p, named(m.names, m.p), m.color]), [b.target, named(["Base case"], b.target), col]];
  let last = -1e9;
  labels.sort((a, c) => y(a[0]) - y(c[0])).forEach(([p, t, c]) => { const ly = Math.max(y(p) + 4, last + 14); last = ly; g += `<text x="${W-padR+8}" y="${ly}" style="fill:${c}">${esc(t)}</text>`; });
  // levels too far away to draw at this scale: named at the edge they lie beyond (farthest outermost), with their distance
  const off = merged(Object.entries(b.levels || {}).filter(([n, p]) => p != null && !lv.some(([m]) => m === n))).sort((a, c) => c.p - a.p);
  // text inside the plot sits on a plate, so no level line runs through it
  const tag = (X, ly, t, fill, end) => { const w = t.length * 6.4 + 8; return `<rect x="${end ? X - w + 4 : X - 4}" y="${ly - 10}" width="${w}" height="13" rx="2" fill="var(--panel)"/><text x="${X}" y="${ly}"${end ? ' text-anchor="end"' : ""} style="fill:${fill}">${esc(t)}</text>`; };
  const edge = (m, ly, arrow) => tag(W - padR - 6, ly, `${arrow} ${m.names.map(nm).join(" · ")} ${num(m.p,0)} (${m.p > b.ref ? "+" : ""}${num(m.p - b.ref,0)})`, m.color, true);
  off.filter(m => m.p > b.ref).forEach((m, i) => { g += edge(m, padT + 12 + (i + (narrow ? 1 : 0)) * 14, "↑"); });     // phones: under the "open" tag
  off.filter(m => m.p <= b.ref).reverse().forEach((m, i) => { g += edge(m, H - padB - 8 - i * 14, "↓"); });
  // path, start and now markers
  g += `<polyline fill="none" stroke="${col}" stroke-width="2.5" stroke-linejoin="round" points="${b.path.map(p => `${x(p[0])},${y(p[1])}`).join(" ")}"/>`;
  const s0 = b.path[0];
  g += `<circle cx="${x(s0[0])}" cy="${y(s0[1])}" r="5" fill="${col}" stroke="var(--panel)" stroke-width="2"/>`;
  if(b.session.live) g += `<line x1="${x(s0[0])}" x2="${x(s0[0])}" y1="${padT}" y2="${H-padB}" stroke="var(--ink3)" stroke-dasharray="3 3"/>` + tag(x(s0[0]) + 6, padT + 12, "now", "var(--ink2)");
  else g += tag(x(0) + 6, padT + 12, "open", "var(--ink2)");
  const pe = b.path.at(-1);
  g += `<circle cx="${x(pe[0])}" cy="${y(pe[1])}" r="4" fill="var(--panel)" stroke="${col}" stroke-width="2"/>`;
  svg.setAttribute("width", W); svg.setAttribute("height", H); svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = g;
  $("pathSw").style.background = col; $("coneSw").style.background = col;
  document.querySelectorAll("#biasLegend [data-lv]").forEach(el => { el.hidden = !(lv.some(([n]) => n === el.dataset.lv) || off.some(m => m.names.includes(el.dataset.lv))); });   // only what is shown
  const tip = $("biasTip");
  svg.onmousemove = e => {
    const r = svg.getBoundingClientRect(), mx = (e.clientX - r.left - padL) / (W - padL - padR) * T;
    let i = 0; b.path.forEach((p, k) => { if(Math.abs(p[0] - mx) < Math.abs(b.path[i][0] - mx)) i = k; });
    const p = b.path[i], c = b.cone[i];
    tip.innerHTML = `${clock(p[0])} ET<br>Base case <b style="color:${col}">${num(p[1], 0)}</b><br><span class="c-ink3">1σ ${num(c[1],0)} – ${num(c[2],0)}</span>`;
    tipAt(tip, Math.min(x(p[0]) + 12, W - 170), (y(p[1]) - 30));
  };
  svg.onmouseleave = () => { tip.classList.remove("on"); };
}

// ---------- Bias replay: the session's levels as the site had them, minute by minute (gexsys/timeline.py).
// Nothing after the slider's minute is drawn or used: not price, not a level, not the axis range. At the right end
// ("Live") the chart is drawBias's own, untouched.
const rp = {tl: null, key: null, ver: null, stale: true, min: null, b: null, col: null, busy: null, empty: false, idx: -1};
const RP_GAP_S = 600;                   // no saved snapshot for 10 minutes: the page says the levels are held
const rpUrl = () => STATIC ? `data/bias-history-${market}.json` : `/api/bias-history?market=${encodeURIComponent(market)}`;
const rpTime = (tl, sec) => new Date(Date.parse(tl.session.open) + sec * 1000).toLocaleTimeString("en-US", {...ET, hour: "numeric", minute: "2-digit"});
const rpDay = tl => new Date(tl.session.open).toLocaleDateString("en-US", {...ET, weekday: "short", month: "short", day: "numeric"});

function rpSync(b, col){
  rp.b = b; rp.col = col;
  if(rp.key !== market) Object.assign(rp, {tl: null, key: market, stale: true, min: null, empty: false, idx: -1});
  if(data && rp.ver !== data.now){ rp.ver = data.now; rp.stale = true; }       // a new refresh: fetch again when needed
  $("biasReplay").hidden = rp.empty;
  if(rp.min == null) return rpLive(true);
  rpLoad().then(() => { if(rp.min != null){ rpBounds(); drawReplay(); } });     // scrubbing: the slider stays put
  rpMode(false);
  drawReplay();
}
async function rpLoad(){
  if(rp.tl && !rp.stale) return rp.tl;
  if(!rp.busy) rp.busy = (async () => {
    const want = market;
    try {
      const tl = await (await fetchFresh(rpUrl())).json();
      if(want === market){ rp.tl = tl; rp.stale = false; rp.empty = !tl.rows.length; rpMarks(); }
    } catch(e){ /* keep the copy we have */ }
    finally { rp.busy = null; }
  })();
  await rp.busy;
  return rp.tl;
}
function rpBounds(){
  const s = $("rpSlider"), tl = rp.tl;
  if(!tl) return;
  s.max = Math.max(1, tl.session.now_minute);
  if(rp.min != null && rp.min >= +s.max) rp.min = +s.max - 1;
  rpFill();
}
function rpFill(){ const s = $("rpSlider"); s.style.setProperty("--p", (100 * s.value / (s.max || 1)) + "%"); }
function rpMarks(){
  const tl = rp.tl, max = Math.max(1, tl.session.now_minute), at = m => `${Math.min(100, 100 * m / max)}%`;
  let h = tl.rows.filter(r => r.at(-1)).map(r => `<b style="left:${at(r[0])}"></b>`).join("");      // options levels that moved
  const seen = tl.seen.filter(sv => sv >= 0).concat([tl.session.now_minute * 60]);
  for(let k = 1; k < seen.length; k++) if(seen[k] - seen[k - 1] > RP_GAP_S)
    h += `<s style="left:${at(seen[k - 1] / 60)};width:${Math.min(100, 100 * (seen[k] - seen[k - 1]) / 60 / max)}%"></s>`;
  $("rpMarks").innerHTML = h;
  $("biasReplay").hidden = rp.empty;
}
const RP_TEXT = {};                     // the chart card's own words, put back on Live
function rpMode(live){
  const h = $("biasWhen").parentElement.querySelector("h2"), foot = $("biasLegend").nextElementSibling;
  if(!RP_TEXT.h) Object.assign(RP_TEXT, {h: h.textContent, foot: foot.textContent});
  h.textContent = live ? RP_TEXT.h : "The session as it happened";
  foot.textContent = live ? RP_TEXT.foot : "Each line is where the site had that level at the time (faint: earlier values). Levels come from 15-min delayed options data, placed at the minute they were fetched; nothing after the cursor is shown.";
  if(!live && rp.tl){
    $("biasWhen").textContent = `Replay · ${rpDay(rp.tl)} · 15-min delayed data${rp.tl.estimated ? " · futures mapping estimated" : ""}`;
    $("biasSummary").textContent = "Drag the slider, or use ← → (Shift for 15 minutes). Live or End returns to now.";
  }
  $("rpLive").setAttribute("aria-pressed", live);
  $("biasReplay").classList.toggle("on", !live);
  document.querySelectorAll("#biasLegend [data-live]").forEach(el => { el.hidden = !live; });
  document.querySelectorAll("#biasLegend [data-rp]").forEach(el => { el.hidden = live; });
  $("biasChart").setAttribute("aria-label", live ? "Illustrative path for the session with expected-move cone and key levels"
    : "Replay: futures price and the key levels as they were at the chosen minute");
}
function rpLive(fromRender){
  const s = $("rpSlider"), b = rp.b;
  rp.min = null; rp.idx = -1;
  s.max = rp.tl && !rp.stale ? Math.max(1, rp.tl.session.now_minute)
    : b.session.live ? Math.max(1, Math.floor((Date.now() - Date.parse(b.session.open)) / 60000)) : 390;
  s.value = s.max; s.setAttribute("aria-valuetext", "Live"); rpFill(); rpMode(true);
  $("rpRead").textContent = `Drag to replay ${b.session.live ? "today's session" : "the last session"}`;
  if(fromRender) drawBias(b, rp.col);
  else renderBias(curW());
}
// one redraw per screen frame, however many input events a drag sends
let rpFrame = 0;
const rpDraw = () => { if(!rpFrame) rpFrame = requestAnimationFrame(() => { rpFrame = 0; drawReplay(); }); };
async function rpInput(){
  const s = $("rpSlider");
  rpFill();
  if(+s.value >= +s.max) return rpLive();
  rp.min = +s.value;
  if(!rp.tl){
    $("rpRead").innerHTML = `<span class="skeleton sk-line">Loading the session</span>`;
    await rpLoad();
    if(!rp.tl || rp.empty){ rp.min = null; $("biasReplay").hidden = true; return renderBias(curW()); }
    rpBounds();
    if(rp.min == null) return;
  } else if(rp.stale) rpLoad().then(() => { if(rp.min != null){ rpBounds(); rpDraw(); } });   // keep dragging on the copy we have
  if(!$("biasReplay").classList.contains("on")) rpMode(false);
  rpDraw();
}

function drawReplay(){
  const tl = rp.tl, m = rp.min, col = rp.col;
  if(!tl || m == null) return;
  const svg = $("biasChart"), W = Math.max($("biasWrap").clientWidth, 280), H = 420, padT = 14, padB = 30;
  const narrow = W < 520, padL = narrow ? 50 : 70, padR = narrow ? 92 : 132, T = tl.session.minutes;
  const nm = n => narrow ? BIAS_SHORT[n] || n : n;
  const rows = tl.rows, cols = tl.cols;
  let i = -1;
  while(i + 1 < rows.length && rows[i + 1][0] <= m) i++;
  const cur = i >= 0 ? rows[i] : null;
  const px = tl.price.filter(p => p[0] + 1 <= m);                       // bars closed by the slider's minute
  const ref = px.length ? px.at(-1)[1] : cur ? cur.slice(1, -2).find(v => v != null) : null;
  const seen = tl.seen.filter(sv => sv <= m * 60).at(-1);
  const age = seen == null ? null : m * 60 - Math.max(0, seen);
  // readout
  $("rpSlider").setAttribute("aria-valuetext", `${rpTime(tl, m * 60)} Eastern`);
  $("rpRead").innerHTML = `<b>${rpTime(tl, m * 60)}</b> · ` + (seen == null ? "no levels yet" : age > RP_GAP_S ? `levels as of ${rpTime(tl, seen)}` : `levels ${rpTime(tl, seen)}`);
  if(ref == null){
    svg.innerHTML = `<text class="f-ink3" x="${W / 2}" y="${H / 2}" text-anchor="middle">Nothing saved yet at this time</text>`;
    return;
  }
  // the price axis: only what was known by m. It is held steady while dragging: levels count when they are near the
  // price range so far (which only widens as the session goes on), and the ends snap to round grid steps, so the
  // scale changes only when price or a level crosses a gridline, not every minute
  const p0 = px.length ? px[0][1] : ref, pmin = px.length ? Math.min(...px.map(p => p[1])) : ref, pmax = px.length ? Math.max(...px.map(p => p[1])) : ref;
  const reach = p0 * 0.012, near = v => v != null && v >= pmin - reach && v <= pmax + reach;
  let lo = pmin, hi = pmax;
  for(let k = 0; k <= i; k++) cols.forEach((n, c) => { const v = rows[k][c + 1]; if(near(v)){ lo = Math.min(lo, v); hi = Math.max(hi, v); } });
  const raw = Math.max(hi - lo, p0 * 0.004) / 5, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(f => f * mag).find(st => st >= raw);
  lo = Math.floor((lo - step * 0.25) / step) * step; hi = Math.ceil((hi + step * 0.25) / step) * step;
  const x = mm => padL + mm / T * (W - padL - padR), y = p => padT + (hi - p) / (hi - lo) * (H - padT - padB);
  const clock = mm => rpTime(tl, mm * 60);
  let g = `<defs><clipPath id="rpClip"><rect x="${padL}" y="${padT}" width="${W - padL - padR}" height="${H - padT - padB}"/></clipPath>` +
    `<pattern id="rpHatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="var(--line2)" stroke-width="1"/></pattern></defs>`;
  for(let p = lo; p <= hi + step / 2; p += step){ g += `<line x1="${padL}" x2="${W-padR}" y1="${y(p)}" y2="${y(p)}" stroke="var(--line)"/><text x="${padL-8}" y="${y(p)+4}" text-anchor="end">${num(p, step < 1 ? 2 : 0)}</text>`; }
  const every = [60, 120, 180].find(sp => (W - padL - padR) * sp / T >= (narrow ? 44 : 64)) || 180;
  for(let mm = 30; mm <= T; mm += every){ g += `<line x1="${x(mm)}" x2="${x(mm)}" y1="${padT}" y2="${H-padB}" stroke="var(--line)"/><text x="${x(mm)}" y="${H-10}" text-anchor="middle">${narrow ? clock(mm).replace(":00", "") : clock(mm)}</text>`; }
  // after m: not known yet, so nothing is drawn there
  if(m < T) g += `<rect x="${x(m)}" y="${padT}" width="${x(T) - x(m)}" height="${H - padT - padB}" fill="url(#rpHatch)" opacity=".7"/>`;
  // each level's history up to m: faint steps, the value in force at m solid (it flashes when it has just changed)
  let body = "";
  cols.forEach((n, c) => {
    let d = "", seg = "";
    for(let k = 0; k <= i; k++){
      const v = rows[k][c + 1], pv = k ? rows[k - 1][c + 1] : null, x0 = x(rows[k][0]), x1 = x(k < i ? rows[k + 1][0] : m);
      if(v == null) continue;
      if(pv != null && pv !== v) d += `M${x0},${y(pv)}V${y(v)}`;
      if(k < i) d += `M${x0},${y(v)}H${x1}`; else seg = `M${x0},${y(v)}H${x1}`;
    }
    const moved = i > 0 && rows[i][c + 1] != null && (rows[i].at(-1) & (1 << c)) && rp.idx !== i;
    const dash = n === "Zero gamma" ? "6 4" : "2 3";
    if(d) body += `<path d="${d}" fill="none" stroke="${BIAS_LC[n]}" stroke-width="1.1" stroke-dasharray="${dash}" opacity=".45"/>`;
    if(seg) body += `<path d="${seg}" fill="none" stroke="${BIAS_LC[n]}" stroke-width="1.6" stroke-dasharray="${dash}"${moved ? ' class="rp-flash"' : ""}/>`;
  });
  if(px.length > 1) body += `<polyline fill="none" stroke="var(--ink)" stroke-width="1.6" stroke-linejoin="round" points="${px.map(p => `${x(p[0] + 1)},${y(p[1])}`).join(" ")}"/>`;
  g += `<g clip-path="url(#rpClip)">${body}</g>`;
  // the cursor at m
  g += `<line x1="${x(m)}" x2="${x(m)}" y1="${padT}" y2="${H-padB}" stroke="${col}" stroke-width="1.2"/>`;
  if(px.length) g += `<circle cx="${x(px.at(-1)[0] + 1)}" cy="${y(ref)}" r="4" fill="var(--ink)" stroke="var(--panel)" stroke-width="2"/>`;
  g += `<text class="f-ink2" x="${Math.min(x(m) + 6, W - padR - 44)}" y="${padT + 12}">${esc(clock(m))}</text>`;
  if(age != null && age > RP_GAP_S) g += `<text class="f-ink3" x="${padL + 8}" y="${padT + 12}">levels held since ${esc(rpTime(tl, seen))}: no newer ones were saved</text>`;
  // labels: the values in force at m (same-price levels share one), with the last change if it is under 15 min old
  const lastMove = c => {
    for(let k = i; k > 0; k--) if(rows[k].at(-1) & (1 << c))           // the options level moved, not just the basis
      return m - rows[k][0] <= 15 && rows[k - 1][c + 1] != null && rows[k][c + 1] != null ? rows[k][c + 1] - rows[k - 1][c + 1] || null : null;
    return null;
  };
  const live = cur ? cols.map((n, c) => [n, cur[c + 1], c]).filter(([, v]) => v != null) : [];
  const groups = list => Object.values(list.reduce((acc, [n, p, c]) => {
    const k = num(p, 0), d = lastMove(c);
    (acc[k] = acc[k] || {p, names: [], color: BIAS_LC[n], mv: null}).names.push(n);
    if(d) acc[k].mv = d;
    return acc;
  }, {}));
  const onChart = v => near(v) && v >= lo && v <= hi;
  const inn = groups(live.filter(([, v]) => onChart(v))), out = groups(live.filter(([, v]) => !onChart(v))).sort((a, c) => c.p - a.p);
  let last = -1e9;
  inn.sort((a, c) => y(a.p) - y(c.p)).forEach(gp => {
    const ly = Math.max(y(gp.p) + 4, last + 14); last = ly;
    const mv = gp.mv ? ` <tspan class="f-ink2">${gp.mv > 0 ? "▲" : "▼"}</tspan>` : "";      // moved in the last 15 min
    g += `<text x="${W-padR+8}" y="${ly}" style="fill:${gp.color}">${esc(gp.names.map(nm).join(" · "))} ${num(gp.p,0)}${mv}</text>`;
  });
  const edge = (gp, ly, arrow) => `<text x="${W-padR-6}" y="${ly}" text-anchor="end" style="fill:${gp.color}">${arrow} ${esc(gp.names.map(nm).join(" · "))} ${num(gp.p,0)} (${gp.p > ref ? "+" : ""}${num(gp.p - ref,0)})</text>`;
  out.filter(gp => gp.p > ref).forEach((gp, k) => { g += edge(gp, padT + 12 + (k + 1) * 14, "↑"); });     // under the time label
  out.filter(gp => gp.p <= ref).reverse().forEach((gp, k) => { g += edge(gp, H - padB - 8 - k * 14, "↓"); });
  rp.idx = i;
  svg.setAttribute("width", W); svg.setAttribute("height", H); svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = g;
  document.querySelectorAll("#biasLegend [data-lv]").forEach(el => { el.hidden = !live.some(([n]) => n === el.dataset.lv); });
  // hover: what was known at the hovered minute, never past m
  const tip = $("biasTip");
  svg.onmousemove = e => {
    const r = svg.getBoundingClientRect(), mm = Math.max(0, Math.min(m, Math.round((e.clientX - r.left - padL) / (W - padL - padR) * T)));
    const bar = px.filter(p => p[0] + 1 <= mm).at(-1);
    let k = -1;
    while(k + 1 <= i && rows[k + 1][0] <= mm) k++;
    const lv = k >= 0 ? cols.map((n, c) => [n, rows[k][c + 1], k > 0 && rows[k - 1][c + 1] != null && (rows[k].at(-1) & (1 << c)) ? rows[k][c + 1] - rows[k - 1][c + 1] : 0]).filter(([, v]) => v != null) : [];
    tip.innerHTML = `${clock(mm)} ET${bar ? `<br>Price <b>${num(bar[1])}</b>` : ""}${lv.map(([n, v, d]) => `<br><span style="color:${BIAS_LC[n]}">${esc(n)}</span> ${num(v)}${d ? ` <span class="c-ink3">${d > 0 ? "+" : ""}${num(d)}</span>` : ""}`).join("")}`;
    tipAt(tip, Math.min(x(mm) + 12, W - 190), (bar ? Math.max(0, y(bar[1]) - 30) : padT));
  };
  svg.onmouseleave = () => { tip.classList.remove("on"); };
}
(() => {
  const s = $("rpSlider");
  ["pointerdown", "focus"].forEach(ev => s.addEventListener(ev, () => { rpLoad(); }));
  s.addEventListener("input", rpInput);
  s.addEventListener("keydown", e => {
    if(e.shiftKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")){
      e.preventDefault();
      s.value = Math.max(0, Math.min(+s.max, +s.value + (e.key === "ArrowRight" ? 15 : -15)));
      rpInput();
    }
  });
  $("rpLive").addEventListener("click", () => { if(rp.min != null) rpLive(); });
})();

function renderExpiry(s){
  const rows = Object.entries(s.by_expiry || {}).sort((a, b) => a[0].localeCompare(b[0])).slice(0, 8);
  const mx = Math.max(1, ...rows.map(([, v]) => v.abs));
  $("byExpiry").innerHTML = rows.length ? `<table><tr><th>Expiration</th><th>Net gamma</th><th style="width:38%">Share of total</th></tr>${rows.map(([e, v]) => {
    const dLbl = new Date(e + "T12:00:00Z").toLocaleDateString("en-US", {weekday:"short", month:"short", day:"numeric", timeZone:"UTC"});
    return `<tr><td>${esc(dLbl)}</td><td class="m" style="color:${v.net >= 0 ? "var(--pos)" : "var(--neg)"}">${money(v.net)}</td>
      <td><span class="xbar" style="width:${Math.max(2, 100 * v.abs / mx * 0.7)}%;background:${v.net >= 0 ? "var(--pos)" : "var(--neg)"}"></span> <span class="m c-ink3">${s.gross ? num(100 * v.abs / s.gross, 0) : "-"}%</span></td></tr>`; }).join("")}</table>` : `<div>${stateHtml("empty", "Nothing to list yet", "This table fills from the options chain. It appears with the next refresh, about a minute while the market is open.")}</div>`;
}

function renderMaxPain(X){
  const mp = (X.max_pain || []).slice(0, 8);
  $("maxpain").innerHTML = mp.length ? `<table><tr><th>Expiration</th><th>Max pain</th><th>Open interest</th></tr>${mp.map(m => {
    const d = new Date(m.expiration + "T12:00:00Z").toLocaleDateString("en-US",{weekday:"short",month:"short",day:"numeric",timeZone:"UTC"});
    return `<tr><td>${esc(d)}</td><td class="m c-mp">${num(m.price)}</td><td class="m">${num(m.oi,0)}</td></tr>`; }).join("")}</table>` : `<div>${stateHtml("empty", "Nothing to list yet", "This table fills from the options chain. It appears with the next refresh, about a minute while the market is open.")}</div>`;
}

// =====================================================================================================
// Terminal: pages, ticker, clock, command line, keyboard, explain drawer, and the pro modules
// (live table, track record, library)
// =====================================================================================================
const PAGES = [
  ["levels", "Levels", "LVL"], ["ladder", "Live table", "LIVE"], ["heatmap", "Heatmap", "HEAT"], ["screener", "Screener", "SCRN"],
  ["bias", "Bias", "BIAS"], ["track", "Track record", "TRK"], ["briefings", "Briefings", "BRF"], ["news", "News", "NEWS"], ["indicator", "Indicator", "IND"],
  ["library", "Library", "LIB"], ["glossary", "Glossary", "GLOS"], ["health", "Data health", "DATA"],
  ["backtest", "Backtesting", "BT"]];          // last, so number keys 1-9, 0 keep opening the same pages as before it existed
const NO_MARKET_PAGES = ["news", "indicator", "briefings", "library", "glossary", "track", "backtest", "health"];
const pickP = v => v && typeof v === "object" ? v.price : v;
const curW = () => data && (data.workers.find(x => x.market === market && x.result) || data.workers.find(x => x.market === market));

// ---------- clock and session state (New York)
// Times come only from the build's market calendar (gexsys/marketcal.py via data.calendar): the state changes and the
// cash sessions in UTC. Without them the page says the session is unknown instead of assuming 09:30 or 16:00.
const etDay = d => d.toLocaleDateString("en-CA", ET);
function calState(d, cal){
  const st = (cal && cal.states) || [];
  if(!st.length || d < Date.parse(st[0][0])) return null;
  let i = 0; while(i + 1 < st.length && Date.parse(st[i + 1][0]) <= d) i++;
  // past the last change the export is too old to say (it covers 9 days)
  return i === st.length - 1 && d - Date.parse(st[i][0]) > 3 * 864e5 ? null : {state: st[i][1], next: st[i + 1] ? Date.parse(st[i + 1][0]) : null, then: st[i + 1] ? st[i + 1][1] : null};
}
function sessionPhase(d, cal){
  const ss = (cal && cal.sessions) || [], day = etDay(d), s = ss.find(x => x.date === day);
  if(!ss.length) return {phase: "session times unavailable"};
  if(!s){ const nx = ss.find(x => x.date > day); return {phase: "no cash session today", next: nx}; }
  const t = +d, o = Date.parse(s.open), c = Date.parse(s.close);
  return {phase: t < o ? "before the open" : t < c ? "cash session" : "after the close", session: s};
}
function sessionLabel(d){
  const cal = (data && data.calendar) || {}, cs = calState(+d, cal);
  if(!cs) return ["Session unknown", "warn"];
  if(cs.state === "RTH") return ["US cash open", "ok"];
  if(cs.state === "HOLIDAY") return ["Market holiday", "bad"];
  if(cs.state === "CLOSED") return cs.next && cs.next - d <= 3600e3 ? ["Daily break", "warn"] : ["Futures closed", "bad"];
  if(cs.then === "HOLIDAY") return ["Globex · holiday session", "warn"];     // a holiday morning: futures trade on to the halt
  const sp = sessionPhase(d, cal), h = +d.toLocaleString("en-US", {...ET, hour: "numeric", hour12: false}) % 24;
  return [sp.phase === "before the open" && h >= 4 ? "Globex · Europe" : "Globex · Asia", "warn"];
}
function tickClock(){
  const d = new Date(), [lab, cls] = sessionLabel(d);
  $("clock").innerHTML = `<i class="dot dot-inl ${cls}"></i>${d.toLocaleTimeString("en-US", {...ET, hour12:false})} ET · ${lab}`;
}
setInterval(tickClock, 1000); tickClock();

// ---------- ticker: both markets, always visible
function renderTicker(){
  if(!data) return;
  const cells = data.workers.filter(w => w.result).map(w => {
    const s = w.result.summary, L = w.result.mapped || s, em = (L.extras || {}).expected_move || {};
    const ref = L.futures_equiv_of_ref ?? s.ref_price, emd = em.daily_points_fut ?? em.daily_points;
    const rg = {POSITIVE: "+GAMMA", NEGATIVE: "-GAMMA", INDETERMINATE: "FLIP"}[s.regime] || "-";
    return `<div class="tk${w.market === market ? " on" : ""}" data-m="${esc(w.market)}" title="Switch to ${esc(w.market)} (${w.market === "NQ" ? "N" : "E"})">
      <span class="sym">${esc(w.market)}</span><span class="px">${num(ref)}</span><span class="rg ${esc(s.regime)}">${rg}</span>
      <span><em>ZG</em> <b>${num(pickP(L.zero_gamma), 0)}</b></span><span><em>CW</em> <b class="c-pos">${num(pickP(L.call_wall), 0)}</b></span>
      <span><em>PW</em> <b class="c-neg">${num(pickP(L.put_wall), 0)}</b></span><span><em>EM</em> <b>±${num(emd, 0)}</b></span>
      <span><em>NET</em> <b class="${s.net >= 0 ? "c-pos" : "c-neg"}">${money(s.net)}</b></span></div>`;
  }).join("");
  $("ticker").innerHTML = cells;          // data source, age and next paste are on each market page's header
  [...$("ticker").querySelectorAll(".tk[data-m]")].forEach(el => el.onclick = () => setMarket(el.dataset.m));
}
function setMarket(m){
  market = m; store.set("gex.market", m);
  // the per-page market toggles follow the site's switch (each page's own toggle can still pick another, or All)
  trkM = btM = stM = m; store.set("gex.trkm", m); store.set("gex.btm", m); store.set("gex.stm", m);
  render();
  if(trk && page === "track") renderTrack();          // a closed page redraws when it is opened (setPage)
  if(studies && page === "backtest") renderStudies();
}

// ---------- explain drawer: plain-English help for every module
const HELP = {
  regime: {title: "Gamma regime", tldr: "Are dealers likely to calm the market down, or push it further?",
    body: `<p>Options dealers hedge what they sell. When they hold <b>positive gamma</b>, their hedging buys dips and sells rips, which <b>dampens moves</b>: tighter ranges, more mean reversion.</p><p>With <b>negative gamma</b> they must sell into drops and buy into rallies, which <b>amplifies moves</b>: wider ranges, trend days, faster breaks.</p><p>The <b>σ distance</b> says how many of today's expected moves price sits from the flip (zero gamma). Under 0.3σ means the regime could change with a small move.</p>`,
    watch: ["Negative gamma + a level break = moves can accelerate", "Positive gamma = fade extremes toward the walls"],
    live: (w, s, L) => `Regime: ${s.regime}\nZero gamma: ${num(pickP(L.zero_gamma))}\nPrice: ${num(L.futures_equiv_of_ref ?? s.ref_price)}`},
  reference: {title: "Reference price", tldr: "The price every level here is measured against.",
    body: `<p>Levels are computed from <b>index and ETF options</b> (SPX + SPY for ES, NDX + QQQ for NQ). The big number is the <b>futures-equivalent</b> price, converted with the measured futures / index basis, so the levels sit in futures prices.</p><p>The data is <b>15 minutes delayed</b> (Cboe's free feed). TradingView re-maps every level to your live chart, so the indicator lines stay aligned in real time.</p><p>The <b>expected move</b> is the 1-standard-deviation range implied by option prices for the session: options price about a 68% chance the close ends inside it. The Track record page shows how often it actually has.</p>`},
  net_gex: {title: "Net gamma exposure", tldr: "How much dealers would have to trade for a 1% move, in dollars.",
    body: `<p>Adds up every option's gamma times its open interest, using the usual assumption that dealers are <b>long calls and short puts</b>. The result is the dollar amount of stock or futures dealers would buy or sell if price moved 1%.</p><p><b>Positive</b> = they trade against the move (calming). <b>Negative</b> = they trade with it (amplifying). Bigger magnitude = stronger effect.</p><p>It's a model of positioning, not observed trades: treat it as a map of where hedging pressure likely sits.</p>`},
  stats: {title: "Flow dashboard", tldr: "Translates the gamma model into contracts and flows you can feel on the tape.",
    body: `<p><b>Hedging per 1%</b>: futures contracts dealers trade for a 1% move. <b>Charm</b>: what dealers trade just from time passing (strongest into the close). <b>Vanna</b>: what they trade if implied volatility rises a point (vol drops after events often trigger the reverse).</p><p><b>Put/call ratios</b> show protection demand. <b>ATM IV</b> is the market's volatility forecast. <b>Share of gamma</b> in the nearest expiration says how quickly levels can shift.</p>`},
  ladder: {title: "Level ladder", tldr: "Every level, sorted by price, with your distance to it.",
    body: `<p><b>Key levels</b> come from all expirations: <b>call wall</b> (most call gamma above price, often resistance), <b>put wall</b> (most put gamma below, often support), <b>zero gamma</b> (the flip), <b>absolute gamma</b> (the biggest strike overall, often a magnet).</p><p><b>0DTE</b> levels use only today's expiring options: they dominate intraday and vanish at the close. <b>Volume and OI walls</b> show where contracts actually trade or sit. <b>Max pain</b> and <b>expected move</b> add context.</p><p>The white marker is where price is now.</p>`},
  by_strike: {title: "Gamma by price", tldr: "Where the gamma sits, strike by strike.",
    body: `<p>Each bar is one strike's net gamma. <b>Blue</b> strikes (positive) tend to slow price down near them; <b>orange</b> strikes (negative) tend to speed it up through them.</p><p>Clusters of big bars are the "walls". Hover for exact values, or switch to the table.</p>`},
  max_pain: {title: "Max pain", tldr: "The price where option buyers lose the most at expiration.",
    body: `<p>For each expiration, the settlement price that makes the most options expire worthless. Some traders watch for a drift toward it into expiry, especially for 0DTE. It's a statistic, not a target: strong trends ignore it.</p>`},
  by_expiry: {title: "Gamma by expiration", tldr: "Which expirations hold the gamma.",
    body: `<p>A big share in today's or this week's expirations means the levels are driven by short-dated options and can shift quickly, often around the open, after data releases and into the close.</p>`},
  bias: {title: "Daily bias", tldr: "A transparent, rule-based read of direction and day type.",
    body: `<p>Adds up a few positioning factors (magnet strike, walls, vanna, 0DTE max pain, and charm flow as a small tie-breaker) into a score. With no real lean it says Neutral rather than guess. The gamma side decides the <b>day type</b> (range, trend or pivot), not the direction. It's a starting scenario, not a forecast.</p>`},
  base_case: {title: "Base case", tldr: "Where the factors point by the close if nothing else intervenes.",
    body: `<p>In positive gamma it's usually the magnet strike; in negative gamma it's a move in the direction of the bias; near the flip it's zero gamma itself. News and flows can override it.</p>`},
  bias_range: {title: "Model range", tldr: "The likely range for the session given the gamma side.",
    body: `<p>The 1σ expected move from the Levels page, scaled by the model: positive gamma tightens it (0.7×, often to the walls), negative gamma widens it (1.2× each way, 0.8× on the side against the bias), near the flip 0.9×. So it differs from the plain 1σ range on Levels on purpose.</p>`},
  bias_chart: {title: "Session path", tldr: "An illustration of how the day could unfold.",
    body: `<p>The line is the base-case path; the cone is the ±1σ expected move growing through the session. About one day in three, price leaves the cone.</p>`},
  factors: {title: "Factors", tldr: "Each ingredient of the bias, with its score and reason.", body: `<p>Positive scores lean bullish, negative bearish. "Day type" rows set the character of the session rather than the direction.</p>`},
  briefings: {title: "Briefings", tldr: "A written summary before the US open and before the Asia session.",
    body: `<p><b>NY AM</b> at 9:00 AM ET: levels, regime, expected range, 0DTE levels, today's US data and market-moving posts. <b>Asia</b> at 7:00 PM ET: where we closed, what changed since the morning, the overnight Asia/Europe calendar and tomorrow's US data. <b>Weekly</b> after the week's last close: how the market moved, in under 10 sentences. It also shows what was behind the move: each stock's share of the index move, sectors, earnings reactions, economic data and headlines from the biggest days. Those are measured links by weight and timing, not proof of cause.</p>`},
  calendar: {title: "Economic calendar", tldr: "Scheduled data releases that can override any level.",
    body: `<p>From ForexFactory. High-impact USD releases (CPI, payrolls, Fed) move NQ and ES the most. Levels often break on these releases, then rebuild as options reposition.</p>`},
  posts: {title: "Trump posts", tldr: "Posts that have moved futures, tagged when they mention market topics.",
    body: `<p>Yellow tags flag market words (tariffs, the Fed, China, oil). Bullish/bearish is a keyword guess, shown only when clear: read the post before acting.</p>`},
  indicator: {title: "GEX PRO indicator", tldr: "The TradingView script that draws these levels on your chart.",
    body: `<p>Copy the code into TradingView's Pine Editor once (and again whenever the version changes). Then paste the levels payload (a new one every 30 minutes) into its settings: the indicator maps index levels to your live futures chart.</p>`},
  screener: {title: "Index drivers", tldr: "The handful of stocks that move NQ and ES, and how many points each is worth today.",
    body: `<p>A few giant companies make up most of the Nasdaq-100 and a big share of the S&P 500, so their moves <b>are</b> the futures' moves. This page shows the biggest weights in the index for the market you pick (NQ or ES at the top).</p><p><b>Index pts</b> = the stock's weight × its % move today × the futures price: roughly how many points of NQ or ES that stock explains. The bars show who is lifting and who is dragging. <b>Pre / after</b> is the latest pre-market or after-hours move, and the line above it says what those moves imply for the future before the cash open. <b>Rel vol</b> is today's volume against the 3-month average (1.5× or more is highlighted).</p><p>Watch the <b>earnings</b> dates: when a top-five name reports after the close, NQ and ES often gap on it overnight.</p>`,
    watch: ["Top names all red but the future green = narrow, fragile move", "A mega cap reporting AMC = overnight gap risk for NQ / ES"]},
  pastes: {title: "9:30 pastes for backtesting", tldr: "The exact levels from each past session's open, ready to paste into the indicator.",
    body: `<p>Every session, the paste from the last calculation before 9:30 ET is saved, the same one the Track record grades. Copy a day, paste it into the indicator's <b>Levels payload</b>, then scroll your chart back to that day: every level, tag, zone and IV band is drawn as it was at that open, plus the closing levels of the sessions before it.</p><p>The indicator marks it "Backtest" with the date instead of "stale", and its alerts stay off. Click <b>Copy for TradingView</b> at the top of any page and paste that to go back to live levels.</p><p>The website keeps these permanently from now on; days before this feature go back as far as the saved snapshots did (about a week).</p>`,
    watch: ["Compare where price reacted with the C / P tags and the walls that day", "Use Copy both on a layout with NQ and ES charts"]},
  studies: {title: "Backtesting studies", tldr: "Do the 9:30 levels give an edge? Tested against random levels, split by conditions, and as a rule, with the sample each still needs.",
    body: `<p>Four studies, each fixed in a written definition file before any result (its hash is on each card, so any result can be rerun exactly). They use only what was known before each session's 9:30 open, checked by a look-ahead audit on every build.</p><p><b>No proven edge yet</b> means no study has an interval that excludes zero, or a split or rule that survives its correction for the number of tests. That is a valid result: with few sessions, real edges and noise look alike.</p><p>Every trade on this page is hypothetical. Nothing here is advice.</p>`,
    watch: ["The verdict stays \"no proven edge yet\" until a study has enough sessions", "A study with too few sessions shows its count only, never a rate"]},
  studies_need: {title: "Sample needed", tldr: "How many sessions each study has, how many it needs, and when that is reached at today's rate.",
    body: `<p><b>Levels vs random:</b> the level type touched most often needs 20 touches before its rate is shown. <b>When it works:</b> the split closest to testable needs 20 sessions in its smallest group. <b>Rule tester:</b> 20 training sessions, then 30 out-of-sample trades, at today's touches per session.</p><p>The dates count trading days from the last data day. They are best cases: a rate seen over a few weeks can change, and the rule tester trades at most one position at a time, so it usually needs more.</p>`,
    watch: ["Dates move as the touch rate changes", "Reached means the study can report, not that it found anything"]},
  study_levels: {title: "Levels vs random levels", tldr: "Does price turn at a 9:30 level more often than at a random level the same distance away?",
    body: `<p>For each level type: how often price, on first reaching the level during the cash session, turned back 4 tolerances before a 1-minute close beyond it. <i>Random</i> is the same rule at random levels from the same sessions, on the same side and distance from the open.</p><p>The difference has a 95% interval from resampling whole sessions (touches on one day are not independent). <b>n&lt;20</b>: fewer than 20 touches, no rate shown. <i>Shifted</i>: the same with the levels moved by the typical futures mapping error, so a result that depends on a few points is visible.</p>`,
    watch: ["An interval that includes 0 is no proven edge", "Compare the shifted results: a real level effect survives a few points"]},
  study_splits: {title: "When it works", tldr: "Is the level effect different on some days: regime, volatility, events, opex, weekday?",
    body: `<p>Seven splits, each known before 9:30, registered before any result: gamma regime, distance from zero gamma, the VIX / VXN third (cutoffs from the past year only), USD high-impact event days, weekday, opex week and the 0DTE share of gamma.</p><p>A split is tested only when every group has 20 sessions, by shuffling whole sessions between groups 10,000 times. With many tests some look good by chance, so Benjamini-Hochberg at q = 0.10 decides which survive; only survivors show their groups' differences.</p>`,
    watch: ["\"Not enough data\" is shown with each group's count", "Event day and 0DTE share started recording on Nov 19, 2026"]},
  study_rules: {title: "Rule tester", tldr: "A written trading rule replayed on 1-minute bars, scored only on sessions it was not tuned on. Hypothetical.",
    body: `<p>The rule fades the first touch of a 9:30 level: short a level above the open, long one below. Fills are deliberately conservative: entry at the next bar's open plus a tick, stop and target a tick worse, the stop first if both are inside one bar, fees on every trade.</p><p>Eight settings (stop, target, time exit) are compared on past sessions only; the best one trades the next session, then the window grows by a day. Only those next sessions are scored. Under 30 such trades nothing is shown but the count. The p-value is also shown multiplied by every setting ever tried, so trying many rules cannot manufacture a result.</p><p>Hypothetical: no order is ever placed, and nothing here is advice.</p>`,
    watch: ["In-sample far above out-of-sample means the settings were fitted to noise", "R is the distance from entry to the stop"]},
  archive: {title: "History archive", tldr: "GEX PRO's own options history, saved every trading day since Nov 18, 2026.",
    body: `<p>Free options-chain history does not exist, so the site keeps its own. After 5:15 pm ET every trading day it saves, per market: the snapshot the 9:30 plan used, the one nearest noon and the last one before the close (levels, ranked levels, expected move, regime, the gamma profile and the 9:30 futures mapping), the list of every snapshot it chose from, and 1-minute bars for the future (the whole overnight-to-5 pm day) and the index (the cash session).</p><p>Files are only ever added, never changed: each day has a manifest with a SHA-256 fingerprint of every file, and a check fails if any saved file changes. Futures bars name their contract and flag roll weeks. Studies on this page say how many sessions they need and how many exist.</p>`,
    watch: ["A study needs enough sessions before its result means anything", "Missing days are listed, never skipped quietly"]},
  pastes_week: {title: "Whole weeks", tldr: "A week of 9:30 levels in one paste, each day drawn on its own day.",
    body: `<p>One paste holds every day of the week. On the chart, each day's zero gamma, call wall, put wall, abs gamma and top three call and put levels are drawn only across that day's 9:30 to 4 pm ET session, so Monday's levels never run into Tuesday's.</p><p>The panel reads "Backtest week" with the dates and alerts stay off. Click <b>Copy for TradingView</b> at the top to go back to live levels.</p>`,
    watch: ["Scroll day by day and note which levels price respected", "Compare with the reaction stats on the Track record page"]},
  level_history: {title: "Level history", tldr: "Each past session's key levels and how that day traded around them.",
    body: `<p>For every session since the track record started: zero gamma, the call and put walls and the absolute-gamma strike from the last calculation before the 9:30 ET open, the ±1σ expected-move band, and the day's range and close. A wall <b>held</b> when price reached it and closed back on its side, <b>broke</b> when it closed through, and was <b>not reached</b> otherwise.</p><p>The chart puts each day side by side: the grey column is the expected-move band, the line is the day's range with a tick at the close, and the coloured dashes are that day's levels. A level far outside every day's range is left off the chart (it is still in the table).</p><p>Levels are calculated on the index (NDX / SPX) and converted to NQ / ES with today's basis, so they line up with a back-adjusted continuous chart.</p>`,
    watch: ["A wall that keeps holding day after day is a level the market respects", "Days that closed outside the grey band were bigger than the options priced in"]},
  plan: {title: "Today's plan", tldr: "The regime, the key levels and what each side of them means, built from the latest data.",
    body: `<p>The plan uses the first expiry's levels (the same C / P / Ab as the TradingView indicator) and the gamma flip. Each line is a zone: <b>above C1</b> (positive-gamma extension), <b>between the flip and C1</b> (positive gamma: two-way trade), <b>between P1 and the flip</b> (negative gamma: moves extend) and <b>below P1</b>. The highlighted line is where price is now.</p><p><b>Day range ±1σ</b> is the range the options market prices in from the previous close. <b>Data today</b> lists the medium- and high-impact US releases still ahead; <b>Earnings ahead</b> lists drivers reporting before the next open, with the move their options price in and what that is worth in index points.</p>`},
  level_map: {title: "Level map", tldr: "Where price sits among today's levels, drawn to scale.",
    body: `<p>One vertical price scale, centred on the reference price and reaching 3.3 expected moves each way. Each line is a level: the <b>call wall</b> and <b>C1</b> in blue, <b>zero gamma</b> (and the 0DTE <b>flip</b> when there is one) dashed grey, <b>P1</b> and the <b>put wall</b> in orange; each label gives the distance in points and in expected moves (σ). A level beyond the scale is pinned to the edge with an arrow. The area above zero gamma is shaded blue (positive gamma), below it orange (negative gamma). The grey band is the day's ±1σ range.</p><p><b>The field.</b> The vertical axis in the middle is the meridian, and the price is the bead on it. The strip of colour on the meridian is the model's net gamma at each strike (blue positive, orange negative; deeper colour = more gamma, so the walls are where it is deepest). The curve is the model's total gamma if the price were at each level: right of the axis positive, left negative, so it crosses the axis at zero gamma. Point at the field, or tap it, for the exact numbers at any price; the strike value is rounded to 1% of the largest strike.</p><p>It shows the same numbers as the cards and the plan, so you can see the distances at a glance. It is a picture of the model, not a forecast.</p>`,
    watch: ["How far price is from zero gamma compared with the grey band", "Which wall price meets first"]},
  changes: {title: "What changed today", tldr: "Every level that moved since the 6 pm ET session start, and when.",
    body: `<p>Each line is a level that moved and stayed moved for at least two snapshots (one-off flickers are ignored): C1 / C2, P1 / P2, Ab1, the 0DTE flip, zero gamma, the walls, and the regime. <b>At the 9:30 open</b> shows where the main levels stood when the cash session began, so you can see how far the map has drifted. The TradingView indicator draws those open levels as faint ghosts.</p>`},
  glossary: {title: "Glossary", tldr: "Every term on this site and on the indicator, in one line each.",
    body: `<p>Search a word, pick a topic, or jump to a letter. Each term says what it means, which topic it belongs to and where you see it (a page, a tag on the indicator, the hover box...). <b>Lesson →</b> opens the Library lesson that explains it from zero.</p><p>Every Explain panel lists the glossary terms it mentions; click one to jump straight here.</p>`},
  library: {title: "The Library", tldr: "A short course that explains everything on this site from zero.",
    body: `<p>Six chapters: options basics, dealers and the Greeks, gamma exposure, volatility, the GEX PRO levels (C / P / Ab, first expiry, gamma zones) and using GEX PRO day to day. Start with <b>What an option is</b> and follow them in order, or search for a topic. Each lesson ends with a quick check; answer it correctly and the lesson is marked as read. Your progress is saved in this browser.</p><p>Every Explain panel links to the matching lesson, so you can jump from a number on the screen straight to the idea behind it.</p>`},
  health: {title: "Data health", tldr: "Every outside source, when it last worked and whether its last try failed.",
    body: `<p>GEX PRO uses only free sources: Cboe for the options chains, Yahoo Finance for prices and candles, ForexFactory for the calendar, Truth Social for posts, slickcharts for index weights and the CFTC for positioning. When one fails, its page keeps the <b>last good copy</b> instead of going blank, so a failure is easy to miss. This page shows each one.</p><p><b>Green</b> = working. <b>Amber</b> = late (no new data for longer than usual) or working only partly, e.g. on a backup source. <b>Red</b> = the last try failed. A red dot on <b>Data health</b> in the menu means something failed.</p>`,
    watch: ["Red options chain = levels and the TradingView paste are not updating", "The weekly CFTC report is normally up to 10 days old: that is still green"]},
  track: {title: "Live track record", tldr: "What GEX PRO said before each open, graded against what the market did.",
    body: `<p>At every session, the levels from the <b>last calculation timestamped before 09:30 ET</b> are frozen as that day's plan: expected move, regime, walls, zero gamma, bias. Nothing can be changed afterwards. After the close, the plan is graded against the index's open, high, low and close.</p><p>Everything is in index points (NDX for NQ, SPX for ES), so the futures basis can't flatter or hurt the result. Missed sessions are listed, not hidden.</p><p>Small samples lie. Until about 20 sessions are graded, read the numbers as a diary, not as proof. The 95% range shows how uncertain each rate still is.</p>`,
    watch: ["The 95% range narrows as sessions add up", "\"rebuilt\" = frozen later from saved snapshots, using only data from before the open"]},
  track_scorecard: {title: "Scorecard", tldr: "Each claim the model makes, and how often it came true.",
    body: `<p><b>Expected move:</b> a fair one-sigma band should contain the close about 68% of the time. Much more means the band is too wide; much less, too narrow.</p><p><b>Regime:</b> the model says negative-gamma sessions should range wider than positive-gamma ones, measured in expected moves.</p><p><b>Walls:</b> a wall is <i>touched</i> when price trades within 5% of an expected move of it, and <i>held</i> when the close stays on the near side.</p><p><b>Plain levels:</b> the same test on price levels with no options meaning, run on every session in the backtest history (SPX from 1990, NDX from 2009) at the same distances from price as the walls actually touched. A real wall should beat this. History uses the previous close and the 30-day vol index, so it is a close match, not an exact one.</p><p><b>Bias:</b> only Bullish and Bearish calls are graded, against the close vs the plan's price. Compare it with the baseline, which always picks the more common direction.</p>`},
  positioning: {title: "Big trader positioning", tldr: "How large funds were positioned in the E-minis, compared with their own last 3 years.",
    body: `<p>From the CFTC's weekly Traders in Financial Futures report. <b>Leveraged funds</b> are hedge funds and similar traders. <b>Asset managers</b> are pensions, mutual funds and insurers.</p><p><b>Net</b> is long contracts minus short contracts. <b>3-year rank</b> is the share of the last 3 years' reports with a lower net position: 90% means longer than 90% of the time. Read the rank, not the sign. Leveraged funds are often short ES as part of hedged trades, so a big short can be completely normal.</p><p>Extreme readings show how crowded a position is, not when it will turn. Positions are from Tuesday and published Friday.</p>`},
  track_moves: {title: "Daily move vs the expected band", tldr: "How far each session moved, measured in expected moves.",
    body: `<p>Each bar is one session's move from the plan price to the close, divided by the plan's expected move. The shaded strip is ±1σ. Bars that closed outside it are amber. A fair band has about a third of bars outside, roughly evenly up and down.</p>`},
  track_reactions: {title: "How price reacted at each level", tldr: "Do GEX levels actually stop or attract price more than any other strike?",
    body: `<p>For every level in the 9:30 plan, the first time price traded to it after the open, the page checks where price was 5, 15 and 60 minutes later: back on the side it came from (<b>bounced</b>), through the level (<b>broke</b>), or close to it (<b>stalled</b>). The bar is a quarter of the move normally expected over that time, so a few ticks of noise don't count.</p><p>The comparison that matters is the grey number: what <b>random strikes at the same distance</b> from the open did on the other days. Strikes are round numbers and price often pauses at round numbers anyway, so a level only has an edge if it beats them.</p><p>A verdict appears only with ${15}+ touches and when the gap from random survives a correction for testing every level type and horizon at once, so pure chance shows a false verdict on at most 1 page in 20. Until then, treat the rates as anecdotes.</p>`,
    watch: ["Bounced well above random = a level worth fading", "Broke well above random = a level that tends to give way, not hold", "No edge = trade it like any other strike"]},
  track_split: {title: "Where it worked", tldr: "The same results split by gamma regime and plan confidence.",
    body: `<p>Shows whether the band and the bias did better on some kinds of day. Groups here are small, so a big gap between them can easily be chance until there are many more sessions.</p>`},
  track_log: {title: "Every session", tldr: "The plan and its grade, one row per market per day.",
    body: `<p><b>Close</b> shows the close and how far it moved from the plan's price in expected moves (σ). <b>In band</b> means the close landed inside ± one expected move. Hover a wall result to see its price.</p><p>A plan marked <b>rebuilt</b> was frozen after the open from snapshots saved before it. Its data is still timestamped before the open, so no later information is used.</p>`},
  backtest: {title: "Historical backtest", tldr: "Decades of data on how well implied volatility predicts the next day's range.",
    body: `<p>Free history of option open interest doesn't exist, so the gamma levels can only be graded from the day GEX PRO started saving them. Implied volatility history does exist: <b>VIX</b> (S&P 500, since 1990) and <b>VXN</b> (Nasdaq-100, since 2009) are the 30-day implied vols of the same index options.</p><p>Each session's band is: previous close × IV × √(calendar days ÷ 365), the same convention GEX PRO uses for its daily expected move.</p><p>It's a proxy. GEX PRO's own band uses the same-day expiration's IV, which is usually different from the 30-day VIX.</p>`},
  backtest_year: {title: "Close inside the band, by year", tldr: "How often the next close stayed within one expected move, year by year.",
    body: `<p>The dashed line is 68.3%, what a perfectly fair one-sigma forecast would give. Bars above it are years where implied vol overstated the moves, which is the usual case. Dips mark stressed years, when realized moves caught up with implied ones. Faded bars are partial years (the first and the current one).</p>`},
  backtest_dist: {title: "Size of the daily move", tldr: "Every day's close-to-close move measured in expected moves.",
    body: `<p>Bars count sessions by how many expected moves (σ) the close moved. The grey curve is a normal distribution, the shape the band assumes.</p><p>Real markets have a taller middle (most days are quieter than implied) and fatter tails (the big days are bigger than a normal curve allows). That's why a band can hold most days and still be blown through on a few.</p>`},
  backtest_vol: {title: "By volatility level", tldr: "Does the band hold better in calm or stressed markets?",
    body: `<p>Sessions split into five equal groups by the vol index the evening before. Compare the close-inside rate and the breaks across the groups to see when the band is most and least reliable.</p>`},
  livetable: {title: "GEX live table", tldr: "Gamma, delta, open interest and volume at every strike near price, for the expirations you pick.",
    body: `<p>Each row is a price band (strikes grouped every few points) in futures prices. <b>Net GEX</b> is the dealer gamma there, in $ per 1% move: right and blue = positive (hedging calms moves), left and orange = negative (hedging adds to moves). <b>Net DEX</b> is the dealers' dollar delta at that strike, <b>Net OI</b> is call minus put open interest, and <b>Net volume</b> is call minus put contracts traded today.</p><p>The highlighted row is price; the amber underline is zero gamma. Chips on the left mark the levels (C1, P1, Ab1, ZG, walls, expected move). Hover a row for its numbers.</p>`,
    watch: ["Big orange bars just below price = support that can break fast", "Pick only today's expiration to see the 0DTE map"]},
  ladder_strip: {title: "Expirations", tldr: "Pick which expirations the table adds up.",
    body: `<p>Each chip is one expiration: its date, days to expiry, M for monthly (AM for morning settlement), a dot and bar for its net GEX. Click chips to add or remove them; Σ All goes back to every expiration. LATER pools everything further out in the basket.</p>`},
  ladder_side: {title: "Net exposure", tldr: "Totals for the expirations selected.",
    body: `<p>Net GEX and net DEX added up over the selected expirations (all strikes, not just the rows shown). The regime line always uses every expiration.</p>`},
  ladder_levels: {title: "Key levels", tldr: "Every level on the table, highest first, with its distance from price.",
    body: `<p>+G = the strikes near price with the most positive net GEX, −G = the most negative, AG = the most total gamma, each over every expiry (so they are not the indicator's first-expiry C1 / P1 / Ab1). ZG = zero gamma, CW / PW = the main walls, EM = today's expected move.</p>`},
  ladder_activity: {title: "Chain activity", tldr: "Who is positioned, and what is trading today.",
    body: `<p>Put/call ratios over the selected expirations and the rows shown: above 1 means more puts. Open interest is from yesterday's close; volume is today's.</p>`},
  heatmap: {title: "GEX heatmap", tldr: "Futures candles with dealer gamma painted behind them, snapshot by snapshot.",
    body: `<p>Behind the candles is the net dealer gamma from every GEX PRO snapshot, each one shown from the moment it was taken until the next, with neighbouring price bands blended into soft zones (hover for the exact value at any price and time). <b>Today</b>, <b>2 days</b> (the default) and <b>All</b> (about a week) pick how much price action is shown. <b>Blue</b> = positive gamma (hedging leans against moves, so price tends to stall or pin there); <b>orange</b> = negative gamma (hedging adds to moves). Brighter = more gamma.</p><p>The lines are the call wall (blue) and put wall (orange) wherever they held for an hour or more; the ZG, CW and PW labels on the price axis are where zero gamma and the walls were in the latest saved snapshot. Times are New York time; a dashed line marks each 9:30 cash open.</p><p>The space right of the last candle shows <b>GEX</b> with the latest saved snapshot's time: that snapshot as bars (right = more gamma, blue or orange by sign), with today's key levels from the first expiry: C1 / C2, P1 / P2, Ab1 and the 0DTE flip, the same levels the TradingView indicator draws. <b>Today / 2 days / All</b> sets how much history is in view; the colour scale under the chart says how much gamma the brightest colour means. Watch how price reacts when it reaches a bright band, and how the bands move during the day. Hover anywhere for the numbers.</p><p><b>Hatched ground</b> means no GEX was saved for that time: the newest snapshot is more than 90 minutes older than the candle (for example while Cboe refuses requests, since the backup estimate is not saved). The page leaves it uncoloured rather than stretch an old snapshot over it.</p><p>Candles: Yahoo Finance, delayed. Gamma: Cboe options, 15-min delayed, mapped to futures with today's basis. History builds up as snapshots are saved (about 12 days in the app, 5 on the hosted site).</p>`,
    watch: ["Price stalling at a bright blue band = positive-gamma support or resistance", "Price slicing through orange = negative gamma, moves can extend"]},
  paste: {title: "The scheduled paste", tldr: "One text block that carries all levels to TradingView.",
    body: `<p>Published every 30 minutes (:00 and :30 ET), plus 09:45 ET. One paste holds NQ and ES; each chart draws only its own market. The indicator marks levels stale after 90 minutes.</p>`},
};
const PAGE_HELP = {levels: "regime", ladder: "livetable", heatmap: "heatmap", screener: "screener", bias: "bias", briefings: "briefings", news: "calendar", indicator: "indicator", library: "library", glossary: "glossary", track: "track", backtest: "studies", health: "health"};
let exKey = null;
function openExplain(key){
  const h = HELP[key]; if(!h) return;
  exKey = key;
  $("exKicker").textContent = "Explain · " + (PAGES.find(p => p[0] === page) || ["", ""])[1];
  $("exTitle").textContent = h.title;
  const w = curW(), s = w && w.result && w.result.summary, L = w && w.result && (w.result.mapped || s);
  const live = h.live && s ? `<h4>Right now (${esc(market)})</h4><div class="live">${esc(h.live(w, s, L))}</div>` : "";
  $("exBody").innerHTML = `<div class="tldr">${h.tldr}</div>${h.body}${h.watch ? `<h4>What to watch</h4><ul>${h.watch.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}${live}`;
  const rel = [...document.querySelectorAll(`#${page}View [data-help]`)].map(e => e.dataset.help).filter((k, i, a) => HELP[k] && k !== key && a.indexOf(k) === i);
  const lesson = (window.GEX_LIBRARY || {lessons: []}).lessons.find(l => l.id === ((window.GEX_LIBRARY || {}).forHelp || {})[key]);
  $("exMore").innerHTML = (lesson ? `<button class="ex-learn" data-lesson="${esc(lesson.id)}"><span class="eyebrow">Learn the basics</span><b>${esc(lesson.title)}</b><span>${lesson.minutes} min lesson in the Library →</span></button>` : "")
    + (rel.length ? `<span class="eyebrow w-100">Also on this page</span>` + rel.map(k => `<button data-k="${k}">${esc(HELP[k].title)}</button>`).join("") : "")
    + (() => { const ts = glTermsIn(h.title + " " + h.tldr + " " + h.body); return ts.length ? `<span class="eyebrow w-100">Terms in the glossary</span>` + ts.map(t => `<button data-g="${esc(t)}">${esc(t)}</button>`).join("") : ""; })();
  [...$("exMore").querySelectorAll("button[data-g]")].forEach(b => b.onclick = () => openGlossary(b.dataset.g));
  [...$("exMore").querySelectorAll("button[data-k]")].forEach(b => b.onclick = () => openExplain(b.dataset.k));
  const lb = $("exMore").querySelector("[data-lesson]");
  if(lb) lb.onclick = () => { closeExplain(); openLesson(lb.dataset.lesson); };
  document.querySelectorAll(".ex").forEach(b => b.classList.toggle("on", b.dataset.help === key));
  $("explain").classList.add("open"); $("explain").setAttribute("aria-hidden", "false"); $("explain").inert = false; document.body.classList.add("ex-open");
}
function closeExplain(){
  $("explain").classList.remove("open"); $("explain").setAttribute("aria-hidden", "true"); $("explain").inert = true; document.body.classList.remove("ex-open");
  document.querySelectorAll(".ex.on").forEach(b => b.classList.remove("on")); exKey = null;
}
$("explainTab").onclick = () => exKey ? closeExplain() : openExplain(PAGE_HELP[page] || "regime");
$("exClose").onclick = closeExplain;
document.querySelectorAll("[data-help]").forEach(el => {
  const key = el.dataset.help; if(!HELP[key]) return;
  const b = document.createElement("button");
  b.className = "ex"; b.textContent = "?"; b.title = "Explain: " + HELP[key].title; b.dataset.help = key; b.setAttribute("aria-label", "Explain " + HELP[key].title);
  b.onclick = e => { e.stopPropagation(); exKey === key ? closeExplain() : openExplain(key); };
  const head = [...el.children].find(c => c.classList.contains("head"));
  const title = head && head.querySelector("h2, .eyebrow");
  if(title) title.after(b);                  // right after the module's title, so it never wraps away
  else (head || el).appendChild(b);
});

// ---------- light / dark mode (the page sets the saved theme before it paints; see index.html)
function setTheme(t){
  document.documentElement.dataset.theme = t; store.set("gex.theme", t);
  $("themeBtn").title = `Switch to ${t === "light" ? "dark" : "light"} mode (T)`;
  if(window.__hmTheme) window.__hmTheme();          // the heatmap chart takes its colours from the theme
}
$("themeBtn").onclick = () => setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");

// ---------- command line
const COMMANDS = [
  ...PAGES.map(([p, name, code]) => ({code, desc: `Open ${name}`, run: () => setPage(p)})),
  {code: "NQ", desc: "Switch to NQ", run: () => setMarket("NQ")}, {code: "ES", desc: "Switch to ES", run: () => setMarket("ES")},
  {code: "COPY", desc: "Copy the TradingView paste (NQ + ES)", run: () => $("copyAll").click()},
  {code: "COPYNQ", desc: "Copy the NQ paste only", run: () => copyFrom(pineUrl("NQ"), "the scheduled update for NQ")},
  {code: "COPYES", desc: "Copy the ES paste only", run: () => copyFrom(pineUrl("ES"), "the scheduled update for ES")},
  {code: "CODE", desc: "Copy the indicator's source code", run: async () => { if(!ind) await loadIndicator(); copyCode(); }},
  {code: "EXPLAIN", desc: "Explain this page", run: () => openExplain(PAGE_HELP[page] || "regime")},
  {code: "REFRESH", desc: "Reload all data now", run: () => { load(); loadNews(); loadPosts(); toast("Refreshing data..."); }},
  {code: "HELP", desc: "Keyboard shortcuts", run: () => showKeys(true)},
  {code: "NOTES", desc: "Show or hide the notes under numbers", run: () => $("notesBtn").click()},
  {code: "LIGHT", desc: "Light mode", run: () => setTheme("light")}, {code: "DARK", desc: "Dark (night) mode", run: () => setTheme("dark")},
  {code: "LEARN", desc: "Start the beginner course", run: () => openLesson(LIB.lessons[0].id)},
  {code: "GLOSSARY", desc: "Open the A-Z glossary", run: () => setPage("glossary")},
  {code: "PASTES", desc: "Past days' 9:30 level pastes, for backtesting", run: showPastes},
  {code: "GLANCE", desc: "Levels at a glance: price, key levels, plan, map", run: () => { setDensity("glance"); setPage("levels"); }},
  {code: "WORK", desc: "Levels: today's full screen", run: () => { setDensity("work"); setPage("levels"); }},
  {code: "STUDY", desc: "Levels with history and every number open", run: () => { setDensity("study"); setPage("levels"); }},
];
// the command bar also finds today's levels (the same prices as Levels, in the same units) and every glossary term
const CMD_LEVELS = [["CW", "Call wall", s => pickP(s.call_wall)], ["PW", "Put wall", s => pickP(s.put_wall)], ["ZG", "Zero gamma", s => pickP(s.zero_gamma)],
  ["AG", "Abs gamma", s => pickP(s.abs_gamma)], ["C1", "C1, first expiry", (s, lv) => lv.C1], ["P1", "P1, first expiry", (s, lv) => lv.P1],
  ["AB1", "Ab1, first expiry", (s, lv) => lv.Ab1], ["FLIP", "0DTE flip", (s, lv) => lv.flip]];
function cmdLevels(){
  const w = curW(), r = w && w.result; if(!r) return [];
  const s = r.mapped || r.summary, lv = (r.session && r.session.levels) || {}, ref = (r.mapped || {}).futures_equiv_of_ref ?? s.ref_price;
  return CMD_LEVELS.map(([code, name, get]) => { const v = get(s, lv);
    return {code, kind: "Level", desc: v == null ? `${market} ${name}: unavailable (Levels says why)` : `${market} ${name} ${num(v, 2)} · ${signed(v - ref, 0)} pts from ${num(ref, 2)}`,
      run: () => { setPage("levels"); const el = $("lvMap"); if(el) el.scrollIntoView({block: "center"}); }}; });
}
const cmdTerms = () => LIB.glossary.map(([t, d]) => ({code: t, kind: "Term", desc: d, run: () => openGlossary(t)}));
// ranking: an exact or starting code, a level named in words, a word in a description, then terms; at most 12, terms from 2 letters
function cmdSearch(q, pool){
  q = q.trim().toLowerCase();
  if(!q) return pool.filter(c => !c.kind);
  const score = c => { const code = c.code.toLowerCase(), desc = c.desc.toLowerCase();
    if(code === q) return 0; if(code.startsWith(q)) return 1; if(new RegExp("\\b" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).test(desc)) return 2;
    return desc.includes(q) || code.includes(q) ? 3 : 9; };
  const rank = c => { const s = score(c); return c.kind === "Level" && s === 2 ? .4 : s + (c.kind === "Term" ? .5 : 0); };   // a level named in words beats the term of that name
  return pool.filter(c => (c.kind !== "Term" || q.length >= 2) && score(c) < 9).map((c, i) => [rank(c), i, c])
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]).slice(0, 12).map(x => x[2]);
}
let cmdSel = 0;
function cmdMatches(q){ return cmdSearch(q, [...COMMANDS, ...cmdLevels(), ...cmdTerms()]); }
function renderCmdList(){
  const ms = cmdMatches($("cmd").value), list = $("cmdList"), box = $("cmd");
  if(document.activeElement !== box){ list.hidden = true; box.setAttribute("aria-expanded", "false"); return; }
  cmdSel = Math.min(cmdSel, Math.max(0, ms.length - 1));
  list.innerHTML = ms.map((c, i) => `<div class="${i === cmdSel ? "on" : ""}" data-i="${i}" id="cmdOpt${i}" role="option" aria-selected="${i === cmdSel}"><b>${esc(c.kind === "Term" ? "TERM" : c.code)}</b><span>${c.kind === "Term" ? `<em>${esc(c.code)}</em> ` : ""}${esc(c.desc)}</span><span>${c.kind || "↵"}</span></div>`).join("")
    || `<div role="option" aria-disabled="true"><b>?</b><span>Nothing found. Try a page (LIVE), a level (CW) or a term (gamma)</span><span></span></div>`;
  list.hidden = false; box.setAttribute("aria-expanded", "true");
  box.setAttribute("aria-activedescendant", ms.length ? "cmdOpt" + cmdSel : "");
  [...list.querySelectorAll("[data-i]")].forEach(el => el.onmousedown = e => { e.preventDefault(); runCmd(ms[Number(el.dataset.i)]); });
  const on = list.querySelector(".on"); if(on) on.scrollIntoView({block: "nearest"});
}
function runCmd(c){ if(!c) return; $("cmd").value = ""; $("cmd").blur(); $("cmdList").hidden = true; document.body.classList.remove("cmd-open"); c.run(); }
$("cmd").addEventListener("input", () => { cmdSel = 0; renderCmdList(); });
$("cmd").addEventListener("focus", renderCmdList);
$("cmd").addEventListener("blur", () => setTimeout(() => { $("cmdList").hidden = true; }, 120));
$("cmd").addEventListener("keydown", e => {
  const ms = cmdMatches($("cmd").value);
  if(e.key === "ArrowDown"){ cmdSel = Math.min(ms.length - 1, cmdSel + 1); renderCmdList(); e.preventDefault(); }
  else if(e.key === "ArrowUp"){ cmdSel = Math.max(0, cmdSel - 1); renderCmdList(); e.preventDefault(); }
  else if(e.key === "Enter"){ runCmd(ms[cmdSel]); e.preventDefault(); }          // an exact code ranks first
  else if(e.key === "Escape"){ $("cmd").value = ""; $("cmd").blur(); document.body.classList.remove("cmd-open"); }
});

// ---------- keyboard
const KEYS = [["/  or  Ctrl+K", "Search pages, levels, terms and commands"], ["1 - 9, 0", "Pages (Levels, Live table, Heatmap, Screener, Bias, Track record, Briefings, News, Indicator, Library); GLOS opens the Glossary"],
  ["N  /  E", "Switch to NQ / ES"], ["X", "Explain this page"], ["T", "Light / dark mode"], ["D", "Notes under numbers on / off"], ["C", "Copy the TradingView paste"], ["?", "This list"], ["Esc", "Close panels"]];
function showKeys(on){ $("keys").hidden = !on; if(on) $("keysGrid").innerHTML = KEYS.map(([k, d]) => `<kbd>${esc(k)}</kbd><span>${esc(d)}</span>`).join(""); }
$("keysBtn").onclick = () => showKeys(true);
// one-line notes under the numbers: off by default for a clean screen; the Explain panel has the full text
function setNotes(on){ document.body.classList.toggle("notes", on); $("notesBtn").setAttribute("aria-pressed", String(on)); store.set("gex.notes", on ? "1" : "0"); }
$("notesBtn").onclick = () => setNotes(!document.body.classList.contains("notes"));
setNotes(store.get("gex.notes", "0") === "1");
$("keysClose").onclick = () => showKeys(false);
$("keys").onclick = e => { if(e.target === $("keys")) showKeys(false); };
// rows and posts that open on a click also open with Enter or Space
document.addEventListener("keydown", e => {
  if((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches('[role="button"][tabindex]')){ e.preventDefault(); e.target.click(); }
});
document.addEventListener("keydown", e => {
  const typing = /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || "");
  if((e.key === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing)){ e.preventDefault(); $("cmd").focus(); return; }
  if(e.key === "Escape"){ showKeys(false); closeExplain(); $("copyBox").hidden = true; closeStockChart(); return; }
  if(typing || e.ctrlKey || e.metaKey || e.altKey) return;
  const n = e.key === "0" ? 10 : Number(e.key);
  if(n >= 1 && n <= PAGES.length) setPage(PAGES[n - 1][0]);
  else if(e.key === "n" || e.key === "N") setMarket("NQ");
  else if(e.key === "e" || e.key === "E") setMarket("ES");
  else if(e.key === "x" || e.key === "X") $("explainTab").click();
  else if(e.key === "t" || e.key === "T") $("themeBtn").click();
  else if(e.key === "d" || e.key === "D") $("notesBtn").click();
  else if(e.key === "c" || e.key === "C") $("copyAll").click();
  else if(e.key === "?") showKeys(true);
});


// ---------- Library: the beginner course (content in assets/library.js)
const LIB = window.GEX_LIBRARY || {chapters: [], lessons: [], glossary: [], diagrams: {}, forHelp: {}};
let libLesson = store.get("gex.lib", LIB.lessons[0] ? LIB.lessons[0].id : ""), libTab = "course";
const libRead = (() => { try { return new Set(JSON.parse(store.get("gex.libread", "[]"))); } catch(e){ return new Set(); } })();
const saveRead = () => store.set("gex.libread", JSON.stringify([...libRead]));
function openLesson(id){ libLesson = id; store.set("gex.lib", id); libTab = "course"; if(page !== "library") setPage("library"); else renderLibrary(); document.querySelector(".area").scrollTo({top: 0, behavior: "auto"}); }
function renderLibrary(){
  const q = ($("libSearch").value || "").trim().toLowerCase();
  const hit = s => !q || s.toLowerCase().includes(q);
  $("libTabs").innerHTML = [["course", "Course"], ["glossary", "Glossary"]].map(([k, t]) => `<button role="tab" aria-selected="${libTab === k}" data-k="${k}">${t}</button>`).join("");
  [...$("libTabs").children].forEach(b => b.onclick = () => { if(b.dataset.k === "glossary") return setPage("glossary"); libTab = b.dataset.k; renderLibrary(); });
  const n = LIB.lessons.length, done = LIB.lessons.filter(l => libRead.has(l.id)).length;
  $("libBar").style.width = (n ? 100 * done / n : 0) + "%";
  $("libCount").textContent = `${done} of ${n} lessons read`;
  const visible = LIB.lessons.filter(l => hit(l.title + " " + l.oneLiner + " " + l.body.replace(/<[^>]+>/g, " ")));
  $("libToc").innerHTML = LIB.chapters.map(([ck, ct]) => {
    const ls = visible.filter(l => l.chapter === ck);
    return ls.length ? `<div class="toc-ch">${esc(ct)}</div>` + ls.map(l => `<button class="toc-l${l.id === libLesson ? " on" : ""}" data-l="${esc(l.id)}"><i class="${libRead.has(l.id) ? "rd" : ""}"></i><span>${esc(l.title)}</span><em>${l.minutes}m</em></button>`).join("") : "";
  }).join("") || `<div class="expl m-2">No lesson matches "${esc(q)}".</div>`;
  [...$("libToc").querySelectorAll("[data-l]")].forEach(b => b.onclick = () => openLesson(b.dataset.l));
  const i = Math.max(0, LIB.lessons.findIndex(l => l.id === libLesson)), L = LIB.lessons[i];
  if(!L){ $("libArticle").innerHTML = ""; return; }
  const ch = (LIB.chapters.find(c => c[0] === L.chapter) || ["", ""])[1];
  const body = L.body.replace(/\{\{d:(\w+)\}\}/g, (_, k) => LIB.diagrams[k] ? `<figure class="lib-fig">${LIB.diagrams[k]()}</figure>` : "");
  const prev = LIB.lessons[i - 1], next = LIB.lessons[i + 1];
  $("libArticle").innerHTML = `<div class="eyebrow">${esc(ch)} · lesson ${i + 1} of ${n} · ${L.minutes} min</div>
    <h2 class="lib-title">${esc(L.title)}</h2>
    <div class="lib-one">${esc(L.oneLiner)}</div>
    <div class="lib-body">${body}</div>
    ${L.points ? `<div class="lib-key"><div class="eyebrow">Key points</div><ul>${L.points.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
    ${L.example ? `<div class="lib-ex"><div class="eyebrow">Example</div><p>${esc(L.example)}</p></div>` : ""}
    ${L.gex ? `<button class="btn ghost lib-try" data-p="${esc(L.gex[0])}">Try it in GEX PRO: ${esc(L.gex[1])} →</button>` : ""}
    ${L.quiz ? `<div class="lib-quiz" id="libQuiz"><div class="eyebrow">Quick check</div><p class="q">${esc(L.quiz.q)}</p>
      <div class="choices">${L.quiz.choices.map((c, k) => `<button data-k="${k}">${esc(c)}</button>`).join("")}</div><p class="why" hidden></p></div>` : ""}
    <div class="lib-nav">${prev ? `<button class="btn ghost" data-l="${esc(prev.id)}">← ${esc(prev.title)}</button>` : "<span></span>"}
      <button class="btn ghost" id="libMark">${libRead.has(L.id) ? "✓ Read" : "Mark as read"}</button>
      ${next ? `<button class="btn" data-l="${esc(next.id)}">${esc(next.title)} →</button>` : `<span></span>`}</div>`;
  [...$("libArticle").querySelectorAll(".lib-nav [data-l]")].forEach(b => b.onclick = () => { libRead.add(L.id); saveRead(); openLesson(b.dataset.l); });
  $("libMark").onclick = () => { libRead.has(L.id) ? libRead.delete(L.id) : libRead.add(L.id); saveRead(); renderLibrary(); };
  const tryBtn = $("libArticle").querySelector(".lib-try");
  if(tryBtn) tryBtn.onclick = () => setPage(tryBtn.dataset.p);
  const qz = $("libQuiz");
  if(qz) [...qz.querySelectorAll(".choices button")].forEach(b => b.onclick = () => {
    const right = Number(b.dataset.k) === L.quiz.answer;
    [...qz.querySelectorAll(".choices button")].forEach(x => { x.disabled = true; x.classList.toggle("right", Number(x.dataset.k) === L.quiz.answer); });
    if(!right) b.classList.add("wrong");
    const why = qz.querySelector(".why"); why.hidden = false; why.innerHTML = `<b>${right ? "Correct." : "Not quite."}</b> ${esc(L.quiz.why)}`;
    if(right){ libRead.add(L.id); saveRead(); $("libMark").textContent = "✓ Read"; $("libBar").style.width = 100 * LIB.lessons.filter(l => libRead.has(l.id)).length / n + "%";
      $("libCount").textContent = `${LIB.lessons.filter(l => libRead.has(l.id)).length} of ${n} lessons read`; }
  });
}
$("libSearch").addEventListener("input", renderLibrary);


// ---------- Track record: live sessions graded against what happened, plus the historical backtest
let trk = null, trkM = store.get("gex.trkm", "ALL"), btM = store.get("gex.btm", "ES");
async function loadTrack(){
  try { trk = await (await fetchFresh(API.track)).json(); }
  catch(e){ trk = trk || {error: offline()}; }
  renderTrack();
}
async function loadArchive(){
  let A;
  try { A = await (await fetchFresh(API.archive)).json(); } catch(e){ A = {unavailable: offline()}; }
  renderArchive(A);
}
function renderArchive(A){
  const day = d => d ? new Date(d + "T12:00:00Z").toLocaleDateString("en-US", {month: "short", day: "numeric", timeZone: "UTC"}) : "-";
  if(A.unavailable){ $("arcSub").textContent = "unavailable"; $("arcKpis").innerHTML = `<div class="expl">${esc(A.unavailable)}</div>`; return; }
  const thru = Object.values(A.markets).map(m => m.through).filter(Boolean).sort().at(-1);
  $("arcSub").textContent = `data through ${day(thru)} · checked ${new Date(A.checked).toLocaleTimeString("en-US", {...ET, hour: "numeric", minute: "2-digit"})} ET`;
  $("arcKpis").innerHTML = Object.entries(A.markets).map(([m, v]) => kpi(m, `${v.sessions} session${v.sessions === 1 ? "" : "s"}`, v.from ? `${day(v.from)} to ${day(v.through)}` : `starts ${day(A.first_day)}`)).join("")
    + (A.missing.length ? kpi("Missing", `${A.missing.length} day${A.missing.length === 1 ? "" : "s"}`, esc(A.missing.slice(-3).map(day).join(", ")), "var(--neg)") : "")
    + (A.error ? kpi("Last write", "failed", esc(A.error.slice(0, 80)), "var(--neg)") : "");
}
// ---------- Backtesting studies (phases 3-6): data/studies.json, recomputed only when their inputs change
let studies = null, stM = store.get("gex.stm") || "NQ";
async function loadStudies(){
  try { studies = await (await fetchFresh(API.studies)).json(); } catch(e){ studies = {unavailable: offline()}; }
  renderStudies();
}
const SPLIT_NAME = {regime: "Gamma regime", zg_distance: "Distance from zero gamma", vol_tercile: "VIX / VXN third", event_day: "Event day",
                    weekday: "Weekday", opex_week: "Opex week", zero_dte_tercile: "0DTE share third"};
const STUDY_NAME = {level_reaction: "Levels vs random", splits: "When it works", rules: "Rule tester"};
const sday = d => d ? new Date(d + "T12:00:00Z").toLocaleDateString("en-US", {month: "short", day: "numeric", timeZone: "UTC"}) : "-";
const sdayY = d => d ? new Date(d + "T12:00:00Z").toLocaleDateString("en-US", {month: "short", day: "numeric", year: "numeric", timeZone: "UTC"}) : "-";
const sgn = (x, d=3) => x == null ? "-" : (x > 0 ? "+" : "") + num(x, d);
const ivTxt = (iv, d=3) => iv ? `${sgn(iv[0], d)} to ${sgn(iv[1], d)}` : "";
const sha8 = h => h ? h.slice(0, 8) : "-";
function renderStudies(){
  const X = studies;
  if(!X) return;
  if(X.unavailable){
    ["stSub", "stNeedSub", "stLvlSub", "stSplitSub", "stRuleSub"].forEach(id => $(id).textContent = "unavailable");
    ["stKpis", "stNeed", "stLvl", "stSplit", "stRule"].forEach(id => $(id).innerHTML = "");
    $("stNote").textContent = X.unavailable; return;
  }
  const ms = Object.keys(X.markets);
  if(!ms.includes(stM)) stM = ms[0];
  $("stMarket").innerHTML = ms.map(m => `<button role="tab" aria-selected="${stM === m}" data-m="${m}">${m}</button>`).join("");
  [...$("stMarket").children].forEach(b => b.onclick = () => { stM = b.dataset.m; store.set("gex.stm", stM); renderStudies(); });
  const M = X.markets[stM], C = M.counts, St = X.studies, edge = M.verdict.edge.length;
  const at = new Date(X.computed_at).toLocaleString("en-US", {...ET, month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
  $("stSub").innerHTML = `<span class="trk-tag ${edge ? "" : "warn"} ml-0">${edge ? "evidence found" : "no proven edge yet"}</span> ${M.sessions} sessions, ${sday(M.data_from)} – ${sday(M.data_through)} · computed ${at} ET`;
  $("stKpis").innerHTML =
    kpi("Sessions", num(M.sessions, 0), `${sday(M.data_from)} to ${sday(M.data_through)} · ${M.archive_sessions} with 1-minute bars`)
    + kpi("Level types with 20+ touches", `${C.level_types_20} of ${C.level_types}`, "below 20 touches no rate is shown")
    + kpi("Splits tested", `${C.splits_tested} of ${C.splits_registered}`, `${St.splits.survivors.filter(x => x.endsWith(":" + stM)).length} survive · ${St.splits.registered} registered for both markets`)
    + kpi("Rule trades out of sample", `${C.oos_trades} of ${C.oos_needed}`, "hypothetical · walk-forward");
  $("stNote").innerHTML = (X.error ? `<b>The last update failed</b> (${esc(X.error)}); these are the results computed ${at} ET. ` : "")
    + (edge ? `Evidence, after each study's correction for the number of tests: ${esc(M.verdict.edge.join("; "))}.`
            : `No proven edge yet: ${M.sessions} sessions. Each study below says how many more it needs.`)
    + " Every rate and trade here comes from past data; none is advice.";
  // sample needed
  $("stNeedSub").textContent = "at today's rate · best case";
  $("stNeed").innerHTML = `<table class="trk-table rx-table"><tr><th>Study</th><th>Have</th><th>Need</th><th>Reached by</th></tr>${M.needs.map(n =>
    `<tr><td>${STUDY_NAME[n.study]}<div class="dim">${esc(n.basis)}</div></td><td class="m">${n.have}</td><td class="m">${n.need ?? "-"}</td><td class="m">${n.need == null ? "unknown" : n.reached ? "reached" : "~" + sdayY(n.est_date)}</td></tr>`).join("")}</table>`;
  // levels vs random
  const LV = St.level_reaction, sh = Object.keys((M.level_reaction[0] || {}).shifted || {});
  $("stLvlSub").textContent = `${M.sessions} sessions through ${sday(M.data_through)} · v${LV.version} ${sha8(LV.sha256)}`;
  $("stLvl").innerHTML = `<table class="trk-table rx-table"><tr><th>Level</th><th>Touches</th><th>Rejected</th><th>Random</th><th>Difference, 95%</th></tr>${M.level_reaction.map(r => {
      if(r.small) return `<tr class="dim"><td>${r.type}</td><td class="m">${r.touches}</td><td class="m" colspan="3">n&lt;20</td></tr>`;
      if(r.unavailable) return `<tr><td>${r.type}</td><td class="m">${r.touches}</td><td class="m">${pct(r.reject)}</td><td class="m" colspan="2">unavailable: ${esc(r.unavailable)}</td></tr>`;
      const out = r.interval[0] > 0 || r.interval[1] < 0;
      return `<tr><td>${r.type}</td><td class="m">${r.touches}</td><td class="m">${pct(r.reject)}</td><td class="m">${pct(r.baseline)}</td><td class="m"><b class="${out ? (r.difference > 0 ? "good" : "bad") : ""}">${sgn(r.difference)}</b><div class="dim">${ivTxt(r.interval)} · ${esc(r.interval_method)} · p ${num(r.p_value, 3)}<br>shifted ${sh.map(k => `${k}: ${sgn(r.shifted[k])}`).join(", ")}</div></td></tr>`;
    }).join("")}</table><div class="expl">Rejected: price turns 4 tolerances back before a 1-minute close beyond the level. Random: the same rule at ${LV.baseline_per_type.toLocaleString("en-US")} random levels per type, the same distance from the open. Intervals from 10,000 whole-session resamples, seed ${X.seed}. Roll-week sessions: ${M.roll_week_sessions}.</div>`;
  // splits
  const SP = St.splits;
  $("stSplitSub").textContent = `${C.splits_tested} of ${C.splits_registered} tested through ${sday(M.data_through)} · v${SP.version} ${sha8(SP.sha256)}`;
  $("stSplit").innerHTML = `<table class="trk-table rx-table"><tr><th>Split</th><th>Sessions per group</th><th>Result</th></tr>${M.splits.map(t => {
      const gs = Object.entries(t.groups).map(([g, v]) => `${esc(g.toLowerCase().replace(/_/g, " "))} ${v.sessions}${v.difference != null && v.interval ? ` (${sgn(v.difference)}, ${ivTxt(v.interval)})` : ""}`).join(" · ");
      const un = Object.values(t.unavailable || {}).reduce((a, b) => a + b, 0);
      const why = un ? `<div class="dim">${un} unavailable: ${esc(Object.keys(t.unavailable)[0])}</div>` : "";
      const res = t.status === "tested" ? `<span class="trk-tag ${t.survives ? "good" : ""} ml-0">${esc(t.verdict)}</span><div class="dim">p ${num(t.p_value, 3)}</div>` : `<span class="dim">${t.status === "unavailable" ? "unavailable: over 10% of shuffles left a group with no touch" : esc(t.status)}</span>`;
      return `<tr><td>${SPLIT_NAME[t.split] || esc(t.split)}</td><td>${gs}${why}</td><td>${res}</td></tr>`;
    }).join("")}</table><div class="expl">Tested only when every group has 20 sessions; ${SP.permutations.toLocaleString("en-US")} permutations of whole sessions; Benjamini-Hochberg at q = ${num(SP.q, 2)} across every test run.</div>`;
  // rule tester
  const RU = St.rules, r = M.rules || {};
  $("stRuleSub").textContent = `fade first touch · v${RU.version} ${sha8(RU.sha256)} · hypothetical`;
  const foot = `<div class="expl">Fade the first touch of a 9:30 level: entry at the next 1-minute bar's open + 1 tick, stop and target exits filled 1 tick worse (the stop first inside one bar), time exit, flat by the close, fees $${num(RU.fees_round_turn_usd, 2)} per round turn. Settings are picked on earlier sessions only (${RU.min_train_sessions} first) and scored on the next one. Tries to date: ${RU.tries} grid points. 1-minute bars: ${RU.data_from ? `${sday(RU.data_from)} to ${sday(RU.data_through)}` : "none yet"}${RU.backfilled_from ? ` (${sday(RU.backfilled_from)} to ${sday(RU.backfilled_through)} downloaded later from Yahoo's 30-day history, not captured on the day)` : ""}. No orders are ever placed.</div>`;
  if(r.status !== "tested"){
    $("stRule").innerHTML = `<div class="trk-kpis st-one"><div class="kpi"><div class="eyebrow">Out-of-sample trades</div><div class="big sm">${r.oos_trades ?? 0} of ${RU.min_oos_trades}</div><div class="s"><span class="trk-tag warn ml-0">not enough data</span> ${r.sessions ?? 0} session${r.sessions === 1 ? "" : "s"} with 1-minute bars; nothing is scored before ${RU.min_oos_trades} out-of-sample trades</div></div></div>` + foot;
    return;
  }
  const e = r.per_trade, ps = r.per_session, nr = r.without_roll_weeks || {};
  $("stRule").innerHTML = `<div class="trk-kpis">`
    + kpi("Expectancy per trade", `${sgn(e.r.mean, 2)} R`, `${ivTxt(e.r.interval, 2)} · ${sgn(e.pts.mean, 1)} pts · $${num(e.usd.mean, 0)} · p ${num(e.r.p_value, 3)}, ${num(r.p_adjusted, 3)} adjusted for ${r.tries} tries`)
    + kpi("Per session", `$${num(ps.usd.mean, 0)}`, `${ivTxt(ps.usd.interval, 0)} · ${r.oos_sessions} sessions`)
    + kpi("Win rate", pct(r.win_rate), `avg win $${num((r.avg_win || {}).usd, 0)} · avg loss $${num((r.avg_loss || {}).usd, 0)}`)
    + kpi("Max drawdown", `$${num(r.max_drawdown_usd, 0)}`, `longest losing streak ${r.longest_losing_streak} · in-sample ${sgn(r.in_sample_r, 2)} R vs ${sgn(r.out_of_sample_r, 2)} R out of sample`)
    + `</div>${equitySvg(r.equity)}<div class="expl">${r.oos_trades} hypothetical trades in ${r.oos_sessions} out-of-sample sessions. Without roll weeks: ${nr.status === "tested" ? sgn(nr.per_trade.r.mean, 2) + " R" : "not enough data"}. Levels shifted ${Object.entries(r.shifted || {}).map(([k, v]) => `${k}: ${v.r_per_trade == null ? "not enough data" : sgn(v.r_per_trade, 2) + " R"}`).join(", ")}.</div>` + foot;
}
function equitySvg(q){
  if(!q || !q.curve.length) return "";
  const n = q.curve.length, all = [...q.lo, ...q.hi, ...q.curve, 0], lo = Math.min(...all), hi = Math.max(...all), H = 120, W = 600;
  const x = i => n === 1 ? W / 2 : 4 + i * (W - 8) / (n - 1), y = v => 6 + (hi - v) * (H - 12) / ((hi - lo) || 1);
  const band = q.hi.map((v, i) => `${x(i)},${y(v)}`).concat(q.lo.map((v, i) => `${x(i)},${y(v)}`).reverse()).join(" ");
  return `<svg class="st-eq" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Cumulative hypothetical dollars by out-of-sample session, with a 95% bootstrap band"><polygon points="${band}" fill="var(--line2)"/><line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="var(--line3)" stroke-dasharray="3 3"/><polyline points="${q.curve.map((v, i) => `${x(i)},${y(v)}`).join(" ")}" fill="none" stroke="var(--ink)" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
}
const pct = r => r == null ? "-" : num(100 * r, 0) + "%";
const ciTxt = s => s && s.ci ? `${num(100 * s.ci[0], 0)}-${num(100 * s.ci[1], 0)}%` : "-";
const kpi = (label, value, sub, col) => `<div class="kpi"><div class="eyebrow">${label}</div><div class="big sm"${col ? ` style="color:${col}"` : ""}>${value}</div><div class="s">${sub}</div></div>`;
const MKT_NAME = {SPX: "S&P 500", NDX: "Nasdaq-100"};
function trkFilters(){
  const ms = ["ALL", ...Object.keys((trk && trk.stats) || {}).filter(k => k !== "ALL")];
  if(!ms.includes(trkM)) trkM = "ALL";
  $("trkMarket").innerHTML = ms.map(m => `<button role="tab" aria-selected="${trkM === m}" data-m="${m}">${m === "ALL" ? "All" : m}</button>`).join("");
  [...$("trkMarket").children].forEach(b => b.onclick = () => { trkM = b.dataset.m; store.set("gex.trkm", trkM); renderTrack(); });
  const bs = Object.keys(((trk && trk.backtest) || {}).markets || {});
  if(bs.length && !bs.includes(btM)) btM = bs[0];
  $("btMarket").innerHTML = bs.map(m => `<button role="tab" aria-selected="${btM === m}" data-m="${m}">${m} · ${esc(MKT_NAME[trk.backtest.markets[m].underlying] || m)}</button>`).join("");
  [...$("btMarket").children].forEach(b => b.onclick = () => { btM = b.dataset.m; store.set("gex.btm", btM); renderTrack(); });
}
function renderTrack(){
  if(!trk) return;
  if(trk.error && !trk.stats){ $("trkKpis").innerHTML = `<div class="expl">${esc(trk.error)}</div>`; return; }
  trkFilters();
  const S = trk.stats[trkM] || trk.stats.ALL || {sessions: 0};
  const n = S.sessions || 0;
  const emc = S.em_close || {}, wh = S.walls_held || {}, bi = S.bias || {};
  $("trkKpis").innerHTML =
    kpi("Sessions graded", num(n, 0), trk.started ? `since ${esc(trk.started)} · ${S.early ? `<span class="trk-tag warn">early: ${n} of ${trk.rules.min_sample}</span>` : `<span class="trk-tag good">sample ok</span>`}` : "starts with the next session")
    + kpi("Close inside expected move", pct(emc.rate), emc.n ? `${emc.k} of ${emc.n} · a fair band holds 68%` : "no graded sessions yet")
    + kpi("Walls held when touched", pct(wh.rate), wh.n ? `${wh.k} of ${wh.n} touches${wh.baseline ? ` · plain levels ${pct(wh.baseline.rate)}` : ""}` : "no wall touched yet")
    + kpi("Bias direction right", pct(bi.rate), bi.n ? `${bi.k} of ${bi.n} calls · baseline ${pct(bi.baseline)}` : "no directional calls graded yet");
  const proof = trk.proof_url ? ` Every plan and grade is committed to a public git branch as it happens: <a href="${esc(trk.proof_url)}" target="_blank" rel="noopener">see the history</a>.` : "";
  $("trkNote").innerHTML = (S.early ? `Early days: ${n} graded session${n === 1 ? "" : "s"}. The numbers need about ${trk.rules.min_sample} sessions before they mean much, and 100+ to be convincing. ` : "")
    + `Each plan uses the last GEX PRO calculation timestamped before the 09:30 ET open, frozen once and graded after the close against the index's open, high, low and close. Missed sessions stay in the list.` + proof;
  // scorecard
  const row = (name, st, meaning) => st ? `<tr><td>${name}</td><td class="m"><b>${pct(st.rate)}</b></td><td class="m">${st.n ? `${st.k}/${st.n}` : "-"}</td><td class="m">${ciTxt(st)}</td><td class="trk-mean">${meaning}</td></tr>` : "";
  const rp = (S.range_em || {}).positive || {}, rn = (S.range_em || {}).negative || {};
  // a verdict needs a few sessions on each side; one day proves nothing either way
  const regimeVerdict = rp.n >= 5 && rn.n >= 5 ? (rn.mean > rp.mean ? `<span class="trk-tag good">as modeled</span>` : `<span class="trk-tag bad">not as modeled</span>`)
    : rp.n && rn.n ? `<span class="trk-tag">too few sessions to judge</span>` : "";
  // plain verdicts: the band against its 68% target (by the 95% range), the bias against always picking the commoner direction
  const bandVerdict = !emc.ci ? "" : emc.ci[0] > emc.expected ? `<span class="trk-tag warn">band looks too wide</span>` : emc.ci[1] < emc.expected ? `<span class="trk-tag warn">band looks too narrow</span>` : `<span class="trk-tag good">in line with 68%</span>`;
  const wb = wh.baseline, wallVerdict = !wb || !wh.ci ? "" : wh.ci[1] < wb.rate ? `<span class="trk-tag bad">worse than plain levels</span>`
    : wh.ci[0] > wb.rate ? `<span class="trk-tag good">beats plain levels</span>` : wh.rate > wb.rate ? `<span class="trk-tag">above plain levels, not proven</span>` : `<span class="trk-tag">no edge so far</span>`;
  const biasVerdict = bi.rate == null || bi.baseline == null ? "" : !bi.ci || bi.ci[0] <= bi.baseline ? (bi.rate > bi.baseline ? `<span class="trk-tag">above baseline, not proven</span>` : `<span class="trk-tag bad">no edge so far</span>`) : `<span class="trk-tag good">beats baseline</span>`;
  $("trkScoreSub").textContent = n ? `${n} session${n === 1 ? "" : "s"} · ${trkM === "ALL" ? "NQ and ES together" : trkM}` : "";
  $("trkScore").innerHTML = n ? `<table class="trk-table"><tr><th>Test</th><th>Result</th><th>Count</th><th>95% range</th><th>What it means</th></tr>
    ${row("Close inside the expected move", S.em_close, `A fair 1σ band holds about 68%. Far above = band too wide; far below = too narrow. ${bandVerdict}`)}
    ${row("Whole session inside the band", S.em_range, "Both the high and the low stayed inside the band.")}
    ${row("Broke above the band", S.em_up_break, "The high went past the upper edge.")}
    ${row("Broke below the band", S.em_down_break, "The low went past the lower edge.")}
    <tr><td>Range: positive vs negative gamma</td><td class="m"><b>${rp.mean == null ? "-" : num(rp.mean, 2) + "×"}</b> vs <b>${rn.mean == null ? "-" : num(rn.mean, 2) + "×"}</b></td><td class="m">${rp.n || 0} / ${rn.n || 0}</td><td class="m">-</td>
      <td class="trk-mean">Session range in expected moves. The model says negative gamma runs wider. ${regimeVerdict}</td></tr>
    ${row("Call wall held when touched", S.call_wall.held, `Reached on ${S.call_wall.touched.k} of ${S.call_wall.touched.n} sessions with a wall above.`)}
    ${row("Put wall held when touched", S.put_wall.held, `Reached on ${S.put_wall.touched.k} of ${S.put_wall.touched.n} sessions with a wall below.`)}
    ${row("Walls held vs plain levels", wh, wb ? `Plain price levels at the same distances held ${pct(wb.rate)}, over ${wb.days.toLocaleString("en-US")} real sessions. ${wallVerdict}` : "Needs a touched wall to compare.")}
    ${row("Traded through zero gamma", S.zg_crossed, "How often the flip level was crossed during the session.")}
    ${row("Bias direction right", S.bias, `Neutral days are not graded. Baseline: always picking the more common direction = ${pct(bi.baseline)}. ${biasVerdict}`)}
    ${row("Base case beat \"no change\"", S.target_beat, "The close was nearer the base-case target than to the price the plan was made at.")}
    ${row("Closed nearer the magnet strike", S.magnet, "Positive gamma only: the close ended nearer the absolute gamma strike than the open.")}
  </table>` : `<div class="expl">Nothing graded yet. The first plan is graded after its session closes.</div>`;
  // every session
  const ss = (trk.sessions || []).filter(s => trkM === "ALL" || s.market === trkM);
  renderTrackMoves(ss); renderTrackSplit(ss); renderReactions();
  $("trkCsv").onclick = () => trackCsv(ss);
  $("trkLogSub").textContent = `${ss.length} session${ss.length === 1 ? "" : "s"} · newest first`;
  const wall = w => !w ? `<span class="dim">-</span>` : !w.touched ? `<span class="dim" title="${num(w.level, 2)}">not reached</span>`
    : w.held ? `<span class="good" title="${num(w.level, 2)}">held</span>` : `<span class="bad" title="${num(w.level, 2)}">broke</span>`;
  const yes = (v, a = "yes", b = "no") => v == null ? `<span class="dim">-</span>` : v ? `<span class="good">${a}</span>` : `<span class="bad">${b}</span>`;
  // the 09:30 open in real time, whichever side of daylight saving the session falls on
  const openMs = day => { const noon = Date.parse(day + "T16:00:00Z") / 1000; return (Date.parse(day + "T09:30:00Z") / 1000 + noon - chartTimeET(noon)) * 1000; };
  const rebuilt = s => s.plan && s.plan.frozen_at && Date.parse(s.plan.frozen_at) - openMs(s.session) > 4 * 3600e3;
  $("trkLog").innerHTML = ss.length ? `<table class="trk-table"><tr><th>Session</th><th>Mkt</th><th>Plan</th><th>Ref</th><th>±EM</th><th>Close</th><th>In band</th><th>Call wall</th><th>Put wall</th><th>Bias</th><th></th></tr>${ss.map(s => {
    const p = s.plan, o = s.outcome, day = new Date(s.session + "T12:00:00Z").toLocaleDateString("en-US", {weekday: "short", month: "short", day: "numeric", timeZone: "UTC"});
    if(!p) return `<tr><td>${esc(day)}</td><td>${esc(s.market)}</td><td colspan="9" class="dim">${esc(s.why || s.status)}</td></tr>`;
    const reg = (p.regime || "").toLowerCase(), regCol = p.regime === "POSITIVE" ? "var(--pos)" : p.regime === "NEGATIVE" ? "var(--neg)" : "var(--zg)";
    const tail = s.status === "pending" ? `<span class="trk-tag">waiting for the close</span>` : s.status === "no_prices" ? `<span class="trk-tag bad">no price data</span>` : "";
    const rb = rebuilt(s) ? `<span class="trk-tag" title="Frozen later from saved snapshots; the data is timestamped ${esc(new Date(p.asof).toLocaleString("en-US", {...ET, month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}))} ET, before the open">rebuilt</span>` : "";
    const fix = s.correction ? `<span class="trk-tag" title="Graded first on the 15:59 minute bar (${esc(num(s.correction.recorded, 2))}), which misses the closing print. Shown here on the official close, ${esc(num(s.correction.official, 2))}. The original grade stays in the public record.">corrected</span>` : "";
    return `<tr><td>${esc(day)}</td><td>${esc(s.market)}</td><td><span style="color:${regCol}">${esc(reg)}</span> · ${esc(p.bias || "-")}</td><td class="m">${num(p.ref, 2)}</td><td class="m">${num(p.em, 0)}</td>
      <td class="m">${o ? `${num(o.close, 2)} <span class="${o.move >= 0 ? "c-good" : "c-bad"}">${signed(o.move_em, 2)}σ</span>` : "-"}</td>
      <td>${o ? yes(o.em_close) : "-"}</td><td>${o ? wall(o.cw) : "-"}</td><td>${o ? wall(o.pw) : "-"}</td><td>${o ? yes(o.bias_hit, "right", "wrong") : "-"}</td><td>${tail}${rb}${fix}</td></tr>`;
  }).join("")}</table>` : `<div>${stateHtml("empty", "No sessions yet", "A session is added when its plan is frozen before the 9:30 ET open, and graded after the close.")}</div>`;
  renderBacktest();
}
// each graded session's move from the plan price against the ±1σ band; ALL pairs NQ and ES day by day
function renderTrackMoves(ss){
  const rows = ss.filter(s => s.outcome && s.outcome.move_em != null).slice().sort((a, b) => a.session.localeCompare(b.session) || a.market.localeCompare(b.market));
  const wrap = $("trkMoveWrap"), svg = $("trkMove"), tip = $("trkMoveTip");
  if(!rows.length){ $("trkMoveSub").textContent = ""; svg.innerHTML = ""; svg.setAttribute("height", 0); return; }
  const out = rows.filter(s => !s.outcome.em_close).length;
  $("trkMoveSub").textContent = `${out} of ${rows.length} closed outside the band (amber)${trkM === "ALL" ? " · ES left, NQ right on each day" : ""}`;
  const W = Math.max(wrap.clientWidth, 280), H = 220, pl = 40, pr = 10, pt = 12, pb = 26;
  const edge = Math.max(2, Math.ceil(Math.max(...rows.map(s => Math.abs(s.outcome.move_em))))), days = [...new Set(rows.map(s => s.session))];
  const y = v => pt + (edge - v) / (2 * edge) * (H - pt - pb), bw = (W - pl - pr) / rows.length;
  let g = `<rect x="${pl}" y="${y(1)}" width="${W - pl - pr}" height="${y(-1) - y(1)}" fill="rgba(var(--fg-rgb),.05)"/>`;
  for(let v = -edge; v <= edge; v++) g += `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(var(--fg-rgb),${v === 0 ? .25 : .05})"/><text x="${pl - 6}" y="${y(v) + 4}" text-anchor="end">${v === 0 ? "0" : signed(v, 0) + "σ"}</text>`;
  rows.forEach((s, i) => {
    const v = s.outcome.move_em, top = y(Math.max(v, 0)), h = Math.max(1, Math.abs(y(v) - y(0)));
    g += `<rect x="${pl + i * bw + bw * 0.2}" y="${top}" width="${Math.max(2, bw * 0.6)}" height="${h}" rx="1.5" fill="${s.outcome.em_close ? "var(--pos)" : "var(--warn)"}"/>`;
  });
  const every = Math.ceil(days.length / Math.max(2, Math.floor((W - pl - pr) / 60)));
  days.forEach((d, i) => { if(i % every) return;
    const first = rows.findIndex(s => s.session === d), n = rows.filter(s => s.session === d).length;
    g += `<text x="${pl + (first + n / 2) * bw}" y="${H - 8}" text-anchor="middle">${esc(d.slice(5))}</text>`; });
  svg.setAttribute("width", W); svg.setAttribute("height", H); svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.innerHTML = g;
  svg.onmousemove = e => {
    const i = Math.max(0, Math.min(rows.length - 1, Math.floor((e.clientX - svg.getBoundingClientRect().left - pl) / bw))), s = rows[i], o = s.outcome;
    tip.innerHTML = `<b>${esc(s.session)} ${esc(s.market)}</b><br>Move ${signed(o.move, 0)} pts · ${signed(o.move_em, 2)}σ<br>${o.em_close ? "Closed inside the band" : "Closed outside the band"} · ${esc((s.plan.regime || "").toLowerCase())} gamma`;
    tipAt(tip, Math.min(pl + i * bw + 12, W - 230), 14);
  };
  svg.onmouseleave = () => { tip.classList.remove("on"); };
}
// the same results split by gamma regime and by the plan's confidence, counted from the sessions in view
// level reactions (trackrecord/reactions.py): first touch of each level vs random strikes at the same distance
let rxH = store.get("gex.rxh", "15");
function renderReactions(){
  const R = trk && trk.reactions;
  $("trkRxH").innerHTML = ["5", "15", "60"].map(h => `<button role="tab" aria-selected="${rxH === h}" data-h="${h}">${h} min</button>`).join("");
  [...$("trkRxH").children].forEach(b => b.onclick = () => { rxH = b.dataset.h; store.set("gex.rxh", rxH); renderReactions(); });
  if(!R || !R.types){ $("trkRxSub").textContent = ""; $("trkRx").innerHTML = `<div class="expl">Starts once a graded session's 1-minute prices are saved.</div>`; return; }
  const need = R.rules.min_touches;
  $("trkRxSub").textContent = `${R.days} session${R.days === 1 ? "" : "s"} · NQ and ES together · after ${rxH} min`;
  const rate = c => c.rate == null ? `<span class="dim">-</span>` : `<b title="${c.ci ? `95% range ${pct(c.ci[0])} to ${pct(c.ci[1])} (${c.k} of ${c.n})` : `${c.k} of ${c.n}`}">${pct(c.rate)}</b> <span class="dim nowrap">vs ${pct(c.random)}</span>`;
  const VERDICT = {bounce: ["good", "bounces more"], break: ["warn", "breaks more"], fewer_bounces: ["bad", "bounces less"],
                   fewer_breaks: ["good", "breaks less"], none: ["", "no edge"]};
  const rows = R.types.map(t => { const c = t.h[rxH]; if(!c) return "";
    const [cls, word] = c.verdict === "few" ? ["", `too few (${c.touches}/${need})`] : VERDICT[c.verdict] || ["", c.verdict];
    return `<tr><td>${esc(t.name)}</td><td class="m">${c.touches}</td><td class="m">${rate(c.bounce)}</td><td class="m">${rate(c.break)}</td><td class="ta-l"><span class="trk-tag ${cls} ml-0">${word}</span></td></tr>`; }).join("");
  $("trkRx").innerHTML = `<table class="trk-table rx-table"><tr><th>Level</th><th>Touches</th><th>Bounced</th><th>Broke</th><th title="Compared with random strikes at the same distance">Vs random</th></tr>${rows}</table>
    <div class="expl mt-2">A bounce or break means price moved at least a quarter of the move normally expected in ${rxH} minutes, back from or through the level; anything less is a stall. A verdict needs ${need}+ touches and a difference from random strikes that survives testing every level type and horizon at once (Holm correction, with errors clustered by day as NQ and ES move together): on random-walk test days at most 5% of pages show any false verdict. A real 13-point edge typically takes about 120 sessions to confirm. The four key levels go back to ${esc(R.since || "the start")}${R.full_since && R.full_since !== R.since ? `; the other level types to ${esc(R.full_since)}, when full 9:30 pastes began to be saved` : ""}.</div>`;
}
function renderTrackSplit(ss){
  const done = ss.filter(s => s.plan && s.outcome), tally = (rows, f) => { const v = rows.map(f).filter(x => x != null); return {k: v.filter(Boolean).length, n: v.length}; };
  const cell = t => t.n ? `<td class="m"><b>${pct(t.k / t.n)}</b> <span class="dim">${t.k}/${t.n}</span></td>` : `<td class="m dim">-</td>`;
  const group = (label, key, order) => order.map(v => { const r = done.filter(s => s.plan[key] === v); if(!r.length) return "";
    return `<tr><td>${label} ${esc(v.toLowerCase())}</td><td class="m">${r.length}</td>${cell(tally(r, s => s.outcome.em_close))}${cell(tally(r, s => s.outcome.bias_hit))}</tr>`; }).join("");
  const others = (key, known) => [...new Set(done.map(s => s.plan[key]).filter(v => v && !known.includes(v)))];
  const regs = ["POSITIVE", "NEGATIVE"], confs = ["High", "Medium", "Low"];
  $("trkSplitSub").textContent = done.length ? `${done.length} graded · small groups swing a lot` : "";
  $("trkSplit").innerHTML = done.length ? `<table class="trk-table"><tr><th>Group</th><th>Sessions</th><th>Close in band</th><th>Bias right</th></tr>
    ${group("Regime:", "regime", [...regs, ...others("regime", regs)])}${group("Confidence:", "confidence", [...confs, ...others("confidence", confs)])}</table>` : `<div>${stateHtml("empty", "Nothing graded yet", "The breakdown appears once a session's plan has been graded, after its close.")}</div>`;
}
function trackCsv(ss){
  const q = v => v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
  const head = ["session", "market", "status", "regime", "bias", "confidence", "ref", "expected_move", "open", "high", "low", "close", "move_pts", "move_sigma", "closed_in_band", "bias_right"];
  const rows = ss.map(s => { const p = s.plan || {}, o = s.outcome || {}; return [s.session, s.market, s.status, p.regime, p.bias, p.confidence, p.ref, p.em, o.open, o.high, o.low, o.close, o.move, o.move_em, o.em_close, o.bias_hit].map(q).join(","); });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([[head.join(","), ...rows].join("\n") + "\n"], {type: "text/csv"}));
  a.download = `gex-track-record-${trkM}.csv`; a.click(); URL.revokeObjectURL(a.href);
}
function renderBacktest(){
  const B =(((trk || {}).backtest || {}).markets || {})[btM];
  if(!B){ $("btTitle").textContent = "Backtest data not available yet"; $("btKpis").innerHTML = ""; return; }
  const O = B.overall, R = B.recent, g1 = B.after_gap.one_day, gw = B.after_gap.weekend_or_holiday;
  $("btTitle").textContent = `${MKT_NAME[B.underlying] || B.underlying} with ${B.vol_index}, ${B.start.slice(0, 4)} to ${B.end.slice(0, 4)}: ${O.n.toLocaleString("en-US")} sessions`;
  $("btKpis").innerHTML = kpi("Close inside the band", pct(O.close_in.rate), `vs 68.3% for a fair band · 95% ${ciTxt(O.close_in)}`, "var(--pos)")
    + kpi("Whole session inside", pct(O.range_in.rate), "high and low both inside")
    + kpi("Broke above / below", `${pct(O.up_break.rate)} / ${pct(O.down_break.rate)}`, "share of sessions")
    + kpi("Last 12 months", pct(R.close_in.rate), `close inside · ${R.n} sessions · avg ${B.vol_index} ${num(R.avg_vol, 1)}`);
  const rich = O.close_in.rate > 0.683;
  const side = O.down_break.rate > O.up_break.rate ? `Breaks were more often to the downside (${pct(O.down_break.rate)} vs ${pct(O.up_break.rate)} up): falls come faster than rallies.` : `Breaks were more often to the upside (${pct(O.up_break.rate)} vs ${pct(O.down_break.rate)} down).`;
  $("btNote").innerHTML = `${rich ? `Implied volatility has usually <b>overstated</b> the next day's move: the close landed inside the band ${pct(O.close_in.rate)} of the time, more than the 68% a fair forecast would give. Option sellers are paid for taking risk, so implied moves tend to run larger than realized ones.` : `The close landed inside the band ${pct(O.close_in.rate)} of the time, close to or below the 68% a fair forecast would give.`}
    ${side} After weekends and holidays the band held ${pct(gw.close_in.rate)} vs ${pct(g1.close_in.rate)} after one-day gaps${gw.close_in.rate > g1.close_in.rate + 0.05 ? ", so counting calendar days overstates weekend risk" : ""}.
    <br><b>Proxy:</b> this uses the 30-day ${B.vol_index} because free history of GEX PRO's own same-day IV does not exist. The live track record above uses GEX PRO's actual band.`;
  // by year
  const ys = B.by_year, wrap = $("btYearWrap"), svg = $("btYear");
  const W = Math.max(wrap.clientWidth, 280), H = 260, pl = 44, pr = 10, pt = 12, pb = 26, lo = 0.4, hi = 1.0;
  const bw = (W - pl - pr) / ys.length, y = v => pt + (hi - Math.max(lo, Math.min(hi, v))) / (hi - lo) * (H - pt - pb);
  let g = "";
  for(let v = 0.4; v <= 1.0001; v += 0.1) g += `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(var(--fg-rgb),.05)"/><text x="${pl - 6}" y="${y(v) + 4}" text-anchor="end">${num(100 * v, 0)}%</text>`;
  ys.forEach((r, i) => {
    const v = r.close_in.rate;
    g += `<rect x="${pl + i * bw + bw * 0.15}" y="${y(v)}" width="${Math.max(1, bw * 0.7)}" height="${y(lo) - y(v)}" rx="1.5" fill="var(--pos)" fill-opacity="${r.year === B.end.slice(0, 4) || r.year === B.start.slice(0, 4) ? 0.45 : 0.85}"/>`;
    if(ys.length < 16 || i % Math.ceil(ys.length / 9) === 0) g += `<text x="${pl + i * bw + bw / 2}" y="${H - 8}" text-anchor="middle">${r.year}</text>`;
  });
  g += `<line x1="${pl}" x2="${W - pr}" y1="${y(0.6827)}" y2="${y(0.6827)}" stroke="var(--prompt)" stroke-width="1.5" stroke-dasharray="5 3"/>`;
  svg.setAttribute("width", W); svg.setAttribute("height", H); svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.innerHTML = g;
  const full = ys.filter(r => r.year !== B.end.slice(0, 4) && r.year !== B.start.slice(0, 4)), best = (full.length ? full : ys).reduce((a, r) => r.close_in.rate < a.close_in.rate ? r : a, (full.length ? full : ys)[0]);
  $("btYearSub").textContent = `Lowest full year: ${best.year} (${pct(best.close_in.rate)}, avg ${B.vol_index} ${num(best.avg_vol, 1)})`;
  const tip = $("btYearTip");
  svg.onmousemove = e => {
    const i = Math.max(0, Math.min(ys.length - 1, Math.floor((e.clientX - svg.getBoundingClientRect().left - pl) / bw))), r = ys[i];
    tip.innerHTML = `<b>${r.year}</b> · ${r.n} sessions<br>Close inside <b>${pct(r.close_in.rate)}</b> · whole range ${pct(r.range_in.rate)}<br>Broke up ${pct(r.up_break.rate)} · down ${pct(r.down_break.rate)} · avg ${esc(B.vol_index)} ${num(r.avg_vol, 1)}`;
    tipAt(tip, Math.min(pl + i * bw + 12, W - 250), 14);
  };
  svg.onmouseleave = () => { tip.classList.remove("on"); };
  // distribution of moves vs the normal curve
  const hst = B.hist, dw = $("btDistWrap"), ds = $("btDist"), DW = Math.max(dw.clientWidth, 280), DH = 260, nb = hst.counts.length;
  const top = Math.max(...hst.counts, ...hst.normal) * 1.08, bx = i => pl + i / nb * (DW - pl - pr), by = v => pt + (1 - v / top) * (DH - pt - pb);
  let d = `<rect x="${bx((hst.edge - 1) / hst.bin)}" y="${pt}" width="${bx((hst.edge + 1) / hst.bin) - bx((hst.edge - 1) / hst.bin)}" height="${DH - pt - pb}" fill="rgba(var(--fg-rgb),.035)"/>`;
  hst.counts.forEach((c, i) => { d += `<rect x="${bx(i) + 1}" y="${by(c)}" width="${Math.max(1, bx(1) - bx(0) - 2)}" height="${by(0) - by(c)}" rx="1.5" fill="var(--pos)" fill-opacity=".8"/>`; });
  d += `<polyline fill="none" stroke="var(--ink2)" stroke-width="1.6" points="${hst.normal.map((v, i) => `${(bx(i) + bx(i + 1)) / 2},${by(v)}`).join(" ")}"/>`;
  for(let s = -hst.edge; s <= hst.edge; s += 1) d += `<text x="${bx((s + hst.edge) / hst.bin)}" y="${DH - 8}" text-anchor="middle">${s === 0 ? "0" : signed(s, 0) + "σ"}</text>`;
  ds.setAttribute("width", DW); ds.setAttribute("height", DH); ds.setAttribute("viewBox", `0 0 ${DW} ${DH}`); ds.innerHTML = d;
  const tails = hst.counts[0] + hst.counts[nb - 1], ntails = hst.normal[0] + hst.normal[nb - 1];
  $("btDistSub").textContent = `Beyond ±3σ: ${tails} sessions vs ${num(ntails, 0)} on a normal curve`;
  const dt = $("btDistTip");
  ds.onmousemove = e => {
    const i = Math.max(0, Math.min(nb - 1, Math.floor((e.clientX - ds.getBoundingClientRect().left - pl) / (bx(1) - bx(0))))), a = -hst.edge + i * hst.bin;
    dt.innerHTML = `${i === 0 ? "below " + signed(a + hst.bin, 2) : i === nb - 1 ? "above " + signed(a, 2) : `${signed(a, 2)} to ${signed(a + hst.bin, 2)}`}σ<br>Actual <b>${hst.counts[i]}</b> · normal ${num(hst.normal[i], 0)}`;
    tipAt(dt, Math.min(bx(i) + 12, DW - 190), 14);
  };
  ds.onmouseleave = () => { dt.classList.remove("on"); };
  // by vol level
  $("btVolSub").textContent = `${B.vol_index} the evening before, in five equal groups`;
  $("btVol").innerHTML = `<table class="trk-table"><tr><th>${esc(B.vol_index)} level</th><th>Sessions</th><th>Close inside</th><th>Whole range inside</th><th>Broke above</th><th>Broke below</th><th>Avg |move|</th></tr>${B.by_vol.map(r =>
    `<tr><td class="m">${num(r.lo, 1)} to ${num(r.hi, 1)}</td><td class="m">${r.n.toLocaleString("en-US")}</td><td class="m"><b>${pct(r.close_in.rate)}</b></td><td class="m">${pct(r.range_in.rate)}</td><td class="m">${pct(r.up_break.rate)}</td><td class="m">${pct(r.down_break.rate)}</td><td class="m">${num(r.mean_abs_move_em, 2)}σ</td></tr>`).join("")}</table>
    ${B.by_vol.length > 1 && B.by_vol[0].close_in.rate > B.by_vol.at(-1).close_in.rate ? `<div class="expl">When implied vol is low the band is generous; in high-vol regimes realized moves catch up with it and breaks become more common.</div>` : ""}`;
}


// ---------- GEX live table: net DEX / GEX / OI / volume by strike, for the expirations you pick
let ldSel = (() => { try { return new Set(JSON.parse(store.get("gex.ldsel", "[]"))); } catch(e){ return new Set(); } })();
let ldRowsN = Number(store.get("gex.ldrows", "51"));
const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const ldDate = d => d === "other" ? "LATER" : `${MON[Number(d.slice(5, 7)) - 1]} ${Number(d.slice(8, 10))}`;
const compact = x => x == null || !isFinite(x) ? "-" : (x < 0 ? "-" : "+") + (Math.abs(x) >= 1e9 ? num(Math.abs(x) / 1e9, 2) + "B" : Math.abs(x) >= 1e6 ? num(Math.abs(x) / 1e6, 1) + "M" : num(Math.abs(x) / 1e3, 0) + "K");
function renderLiveTable(){
  const w = curW();
  if(!w || !w.result){ $("ldRows").innerHTML = `<div>${stateHtml("empty", "No table yet", "The live table is built from the options chain. It appears with the first calculation, within a minute.")}</div>`; return; }
  const r = w.result, s = r.summary, L = r.mapped || s, LD = r.ladder;
  if(!LD || !LD.rows || !LD.rows.length){ $("ldRows").innerHTML = `<div class="expl">The live table appears after the next refresh.</div>`; return; }
  const m = r.mapped && r.mapped.mapping, fac = m ? m.factor : 1, off = m ? m.offset || 0 : 0;
  const fut = k => Math.round((k * fac + off) * 4) / 4;
  const ref = L.futures_equiv_of_ref || s.ref_price;
  const E = LD.expirations;
  [...ldSel].forEach(i => { if(!E[i]) ldSel.delete(i); });
  const all = ldSel.size === 0, on = i => all || ldSel.has(i);
  // expiration strip
  const emax = Math.max(1, ...E.map(e => Math.abs(e.net)));
  $("ldStrip").innerHTML = E.map((e, i) => {
    const h = Math.max(3, Math.round(Math.abs(e.net) / emax * 34)), pos = e.net >= 0;
    return `<button class="ld-exp${on(i) ? " on" : ""}" data-i="${i}" type="button" title="${esc(e.date === "other" ? "Every later expiration in the basket" : e.date)}: net GEX ${esc(money(e.net))}, net DEX ${esc(compact(e.dex))}">
      <span class="ld-d">${ldDate(e.date)}</span><span class="ld-dte">${e.dte == null ? "rest" : num(e.dte, 1) + " DTE"}</span><span class="ld-tag">${esc(e.tag || "")}</span>
      <i class="ld-dot" style="background:${pos ? "var(--pos)" : "var(--neg)"}"></i>
      <span class="ld-mini"><i style="height:${h}px;background:${pos ? "var(--pos)" : "var(--neg)"}"></i></span><span class="ld-v ${pos ? "pos" : "neg"}">${compact(e.net)}</span></button>`;
  }).join("");
  [...$("ldStrip").children].forEach(b => b.onclick = () => { const i = Number(b.dataset.i); ldSel.has(i) ? ldSel.delete(i) : ldSel.add(i); if(ldSel.size === E.length) ldSel.clear(); store.set("gex.ldsel", JSON.stringify([...ldSel])); renderLiveTable(); });
  $("ldAll").onclick = () => { ldSel.clear(); store.set("gex.ldsel", "[]"); renderLiveTable(); };
  $("ldAll").classList.toggle("on", all);
  $("ldStripSub").textContent = all ? "all expirations" : `${ldSel.size} selected · click to add or remove`;
  // rows: sums over the selected expirations
  const sum = row => { const t = [0, 0, 0, 0, 0, 0]; for(const [i, v] of Object.entries(row.x)) if(on(Number(i))) v.forEach((x, j) => t[j] += x); return t; };
  let rows = LD.rows.map(row => ({k: row.k, f: fut(row.k), v: sum(row)}));
  const near = rows.reduce((b, x, i) => Math.abs(x.f - ref) < Math.abs(rows[b].f - ref) ? i : b, 0);
  const half = Math.floor(ldRowsN / 2);
  rows = rows.slice(Math.max(0, near - half), Math.max(0, near - half) + ldRowsN);
  $("ldZoom").innerHTML = [[21, "Tight"], [35, "Normal"], [51, "Wide"]].map(([n, t]) => `<button role="tab" aria-selected="${ldRowsN === n}" data-n="${n}">${t}</button>`).join("");
  [...$("ldZoom").children].forEach(b => b.onclick = () => { ldRowsN = Number(b.dataset.n); store.set("gex.ldrows", String(ldRowsN)); renderLiveTable(); });
  const col = j => Math.max(1, ...rows.map(x => Math.abs(j === 2 ? x.v[2] - x.v[3] : j === 4 ? x.v[4] - x.v[5] : x.v[j])));
  const mx = {dex: col(1), gex: col(0), oi: col(2), vol: col(4)};
  // levels, in futures prices, placed on the nearest row
  const lv = [];
  const addL = (p, code, name, cls, share) => { if(p != null && isFinite(p)) lv.push({p, code, name, cls, share}); };
  addL(pickP(L.zero_gamma), "ZG", "Zero gamma", "zg"); addL(pickP(L.call_wall), "CW", "Call wall", "pos"); addL(pickP(L.put_wall), "PW", "Put wall", "neg");
  const rk = s.ranked || {};
  // strikes ranked near price over every expiry: named apart from the indicator's first-expiry C1 / P1 / Ab1
  (rk.call || []).forEach((x, i) => addL(fut(x.price), "+G" + (i + 1), `Most +GEX near price${i ? " #" + (i + 1) : ""}`, "pos", x.share));
  (rk.put || []).forEach((x, i) => addL(fut(x.price), "−G" + (i + 1), `Most −GEX near price${i ? " #" + (i + 1) : ""}`, "neg", x.share));
  (rk.abs || []).forEach((x, i) => addL(fut(x.price), "AG" + (i + 1), `Most gamma near price${i ? " #" + (i + 1) : ""}`, "ag", x.share));
  const X = (L.extras || {}).expected_move || {};
  const emd = X.daily_points_fut || X.daily_points, ema = X.anchor_fut || X.anchor;
  if(emd && ema){ addL(ema + emd, "EM+", "Expected high", "em"); addL(ema - emd, "EM-", "Expected low", "em"); }
  const at = new Map();
  lv.forEach(l => { const i = rows.reduce((b, x, j) => Math.abs(x.f - l.p) < Math.abs(rows[b].f - l.p) ? j : b, 0);
    if(Math.abs(rows[i].f - l.p) <= LD.width * fac * 0.75) (at.get(i) || at.set(i, []).get(i)).push(l); });
  const zgRow = [...at.entries()].find(([, ls]) => ls.some(l => l.code === "ZG"));
  const priceRow = rows.reduce((b, x, i) => Math.abs(x.f - ref) < Math.abs(rows[b].f - ref) ? i : b, 0);
  const bar = (v, max) => { const p = Math.min(50, Math.abs(v) / max * 50); return `<i class="${v >= 0 ? "p" : "n"}" style="${v >= 0 ? "left:50%" : `left:${50 - p}%`};width:${p}%"></i>`; };
  $("ldRows").innerHTML = rows.map((x, i) => {
    const ls = at.get(i) || [], v = x.v;
    return `<div class="ld-row${i === priceRow ? " px" : ""}${zgRow && zgRow[0] === i ? " zgr" : ""}" data-i="${i}">
      <span class="ld-lv">${ls.map(l => `<b class="ld-chip ${l.cls}">${esc(l.code)}</b>`).join("")}${i === priceRow ? `<b class="ld-chip now">${num(ref, 2)}</b>` : ""}</span>
      <span class="ld-bar">${bar(v[1], mx.dex)}</span>
      <span class="ld-bar ld-gex">${bar(v[0], mx.gex)}<em class="${v[0] >= 0 ? "p" : "n"}">${Math.abs(v[0]) >= mx.gex * 0.08 ? compact(v[0]) : ""}</em></span>
      <span class="ld-bar">${bar(v[2] - v[3], mx.oi)}</span>
      <span class="ld-k">${num(x.f, 0)}</span>
      <span class="ld-bar">${bar(v[4] - v[5], mx.vol)}</span></div>`;
  }).join("");
  const tip = $("ldTip");
  [...$("ldRows").children].forEach(el => {
    el.onmouseenter = () => {
      const x = rows[Number(el.dataset.i)], v = x.v, ls = at.get(Number(el.dataset.i)) || [];
      tip.innerHTML = `<b>${num(x.f, 2)}</b> <span class="c-ink3">(${esc(s.options_source || w.source)} ${num(x.k, 0)})</span>
        <br>Net GEX <b class="${v[0] >= 0 ? "c-pos" : "c-neg"}">${money(v[0])}</b> per 1% · net DEX ${compact(v[1])}
        <br>OI calls ${num(v[2], 0)} / puts ${num(v[3], 0)} · ${s.backup ? "volume unavailable (backup estimate)" : `volume calls ${num(v[4], 0)} / puts ${num(v[5], 0)}`}${ls.length ? `<br>${ls.map(l => esc(l.code + " " + l.name + (l.share ? ` (${num(100 * l.share, 1)}% of gamma)` : ""))).join("<br>")}` : ""}`;
      tipAt(tip, 170, (el.offsetTop + el.offsetHeight + 40));
    };
    el.onmouseleave = () => { tip.classList.remove("on"); };
  });
  $("ldSub").textContent = `${num(LD.width * fac, 1)}-pt rows in ${w.market} prices · ${all ? "all expirations" : `${ldSel.size} expiration${ldSel.size === 1 ? "" : "s"}`} · ${s.backup ? "OCC backup estimate (open interest only)" : "Cboe 15-min delayed"}`;
  // side panel
  const T = LD.rows.reduce((t, row) => { sum(row).forEach((x, j) => t[j] += x); return t; }, [0, 0, 0, 0, 0, 0]);
  const gT = E.reduce((a, e, i) => a + (on(i) ? e.net : 0), 0), dT = E.reduce((a, e, i) => a + (on(i) ? e.dex : 0), 0);
  $("ldPrice").innerHTML = `<div class="eyebrow">${esc(w.market)} · ${esc((s.options_source || w.source) + (s.etf ? "+" + s.etf : ""))}${refAt(s.ref_time)}</div>
    <div class="big">${num(ref, 2)}</div>
    <div class="ld-cards"><div><div class="eyebrow">Net GEX</div><b class="${gT >= 0 ? "c-pos" : "c-neg"}">${money(gT)}</b><span>per 1% move</span></div>
      <div><div class="eyebrow">Net DEX</div><b class="${dT >= 0 ? "c-pos" : "c-neg"}">${compact(dT)}</b><span>dealer delta, $</span></div></div>
    <div class="expl mt-2">${all ? "All expirations" : "Selected expirations only"}. Regime (all expirations): <b>${esc((s.regime || "").toLowerCase())}</b>.</div>`;
  const lvs = lv.filter((l, i, a) => a.findIndex(z => z.code === l.code) === i).sort((a, b) => b.p - a.p);
  $("ldLevels").innerHTML = `<div class="ld-list">${lvs.map(l => `<div><b class="ld-chip ${l.cls}">${esc(l.code)}</b><span${l.share ? ` title="${num(100 * l.share, 1)}% of gamma"` : ""}>${esc(l.name)}</span><em>${num(l.p, 2)}</em><i class="${l.p >= ref ? "c-pos" : "c-neg"}">${signed((l.p / ref - 1) * 100, 2)}%</i></div>`).join("")}
    <div class="now"><b class="ld-chip now">PX</b><span>${esc(w.market)} ${w.result.mapped ? "equiv. of " + esc(w.source) : "price"}</span><em>${num(ref, 2)}</em><i></i></div></div>`;
  const pcOI = T[2] ? T[3] / T[2] : null, pcV = T[4] ? T[5] / T[4] : null;
  const act = rows.reduce((b, x) => x.v[4] + x.v[5] > b.v[4] + b.v[5] ? x : b, rows[0]);
  $("ldActivity").innerHTML = `<div class="metrics">
    <div class="metric"><div class="eyebrow">Put/call OI</div><div class="v">${pcOI == null ? "-" : num(pcOI, 2)}</div><div class="s">${pcOI == null ? "" : pcOI > 1 ? "more puts open" : "more calls open"}</div></div>
    <div class="metric"><div class="eyebrow">Put/call volume</div><div class="v">${s.backup || pcV == null ? "-" : num(pcV, 2)}</div><div class="s">${s.backup ? "unavailable" : pcV == null ? "" : pcV > 1 ? "puts trading more today" : "calls trading more today"}</div></div>
    <div class="metric"><div class="eyebrow">Most traded strike</div><div class="v">${s.backup ? "-" : num(act.f, 0)}</div><div class="s">${s.backup ? "unavailable" : num(act.v[4] + act.v[5], 0) + " contracts today"}</div></div>
    <div class="metric"><div class="eyebrow">Biggest GEX strike</div><div class="v">${num(rows.reduce((b, x) => Math.abs(x.v[0]) > Math.abs(b.v[0]) ? x : b, rows[0]).f, 0)}</div><div class="s">in the rows shown</div></div></div>
    <div class="expl">${s.backup ? "Backup estimate: open interest from OCC as of the last close; no volume while Cboe refuses." : "Open interest is as of yesterday's close; volume is today's, 15-min delayed."}</div>`;
}

// ---------- market tape: real quotes (Yahoo, exchange data delayed), scrolling across the top
let quotes = null;
async function loadQuotes(){
  try { quotes = await (await fetchFresh(API.quotes)).json(); } catch(e){ return; }
  renderTape();
}
function renderTape(){
  const qs = (quotes && quotes.quotes) || [];
  if(!qs.length){ $("mqTrack").innerHTML = ""; return; }
  const one = qs.map(q => {
    const pc = Math.round(q.pct * 100) / 100, up = pc > 0, dn = pc < 0, cls = up ? "up" : dn ? "dn" : "";
    // like a trading desk tape: $ on every price, whole dollars from 1,000 up, cents below
    const px = q.kind === "yield" ? num(q.price, 2) + "%" : "$" + num(q.price, q.price >= 1000 ? 0 : 2);
    const when = new Date(q.time).toLocaleString("en-US", {...ET, month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
    return `<span class="mq-i${q.stale ? " stale" : ""}" title="${esc(q.symbol)} · last ${esc(when)} ET${q.stale ? " (could not refresh)" : ""}"><b>${esc(q.label)}</b><em>${px}</em><i class="${cls}">${up ? "▲ " : dn ? "▼ " : ""}${pc === 0 ? "+0.00" : signed(pc, 2)}%</i></span>`;
  }).join("");
  $("mqTrack").innerHTML = `<div class="mq-run">${one}</div><div class="mq-run" aria-hidden="true">${one}</div>`;
  $("mqTrack").style.setProperty("--mq-dur", Math.max(40, qs.length * 4.5) + "s");
}

// ---------- GEX heatmap: futures candles (Lightweight Charts) with the gamma history painted underneath
let hm = null, hmChart = null, hmCandles = null, hmLines = {}, hmPrim = null, hmMarket = null;
let hmSpan = store.get("gex.hmspan2", "2d");        // visible range: today's session, two sessions (default), or everything loaded
let hmReset = true;          // next draw starts at the latest candles with auto-scaled prices (open, market or timeframe change)
let hmTf = store.get("gex.hmtf", "5m"), hmOpacity = Number(store.get("gex.hmop", "50")), hmShowLv = store.get("gex.hmlv", "1") === "1";
const hmUrl = () => STATIC ? `data/heatmap-${market}-${hmTf}.json` : `/api/heatmap?market=${encodeURIComponent(market)}&tf=${hmTf}`;
// a chart tooltip: shown (class "on") at x, y inside its chart; hidden by removing "on"
const tipAt = (el, x, y) => { el.classList.add("on"); Object.assign(el.style, {left: x + "px", top: y + "px"}); };
const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
// any CSS colour (hex, rgb() or the OKLCH tokens) as [r, g, b]: painted on a 1-pixel canvas and read back, because
// getComputedStyle returns OKLCH as OKLCH and the chart library (lightweight-charts 4.2) cannot parse it
const RGB_PX = document.createElement("canvas").getContext("2d", {willReadFrequently: true});
function rgbOf(c){ RGB_PX.clearRect(0, 0, 1, 1); RGB_PX.fillStyle = "#000"; RGB_PX.fillStyle = c; RGB_PX.fillRect(0, 0, 1, 1); return [...RGB_PX.getImageData(0, 0, 1, 1).data.slice(0, 3)]; }
// a token for the chart library: always rgb()
const lcVar = n => `rgb(${rgbOf(cssVar(n)).join(",")})`;
async function loadHeatmap(){
  if(!window.LightweightCharts){ $("hmMsg").textContent = "The chart library could not load (it comes from unpkg.com). Check your connection and refresh."; $("hmMsg").hidden = false; return; }
  const want = market + hmTf;
  let got;
  try { got = await (await fetchFresh(hmUrl())).json(); }
  catch(e){ $("hmMsg").textContent = offline(); $("hmMsg").hidden = false; return; }
  if(want !== market + hmTf) return;                       // the market or timeframe changed while loading
  hm = got; hm._key = want;                                 // which market and timeframe this data is for
  renderHeatmap();
}
// a level's path through the snapshots without short flickers: median of 7, then a change only
// counts once it holds for two snapshots in a row (walls often hop between two strikes and back)
function hmSteady(vals){
  const med = vals.map((v, i) => { const w = vals.slice(Math.max(0, i - 3), i + 4).filter(x => x != null).sort((a, b) => a - b); return v == null || !w.length ? null : w[w.length >> 1]; });
  const out = []; let cur = null;
  med.forEach((v, i) => { if(cur == null || (v != null && v !== cur && med[i + 1] === v)) cur = v; out.push(v == null ? null : cur); });
  return out;
}
// New York time for the heatmap's axis and crosshair (the chart library would show UTC)
const hmFmt = {
  hm: new Intl.DateTimeFormat("en-US", {...ET, hour: "2-digit", minute: "2-digit", hourCycle: "h23"}),
  day: new Intl.DateTimeFormat("en-US", {timeZone: "UTC", month: "short", day: "numeric"}),      // the chart's day marks are UTC midnights
  full: new Intl.DateTimeFormat("en-US", {...ET, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}),
  wd: new Intl.DateTimeFormat("en-US", {...ET, weekday: "short", day: "numeric"}),
};
// the card's "as of": the newest GEX snapshot and the newest candle in the file, not the time it was loaded
function hmAsOf(h, tf){
  const s = h.columns[h.columns.length - 1], c = h.candles[h.candles.length - 1], n = h.columns.length;
  return `${n} GEX snapshot${n === 1 ? "" : "s"}${s ? `, latest ${hmFmt.full.format(new Date(s.t * 1000))} ET` : ""}`
    + ` · candles ${tf}, delayed${c ? `, last ${etTime(c[0] * 1000)} ET` : ""}`;
}
function hmTimeOpts(){
  return {localization: {timeFormatter: t => hmFmt.full.format(new Date(t * 1000)) + " ET", priceFormatter: p => num(p, 2)},
    timeScale: {tickMarkFormatter: (t, type) => type < 3 ? hmFmt.day.format(new Date(t * 1000)) : hmFmt.hm.format(new Date(t * 1000))}};
}
// cash opens (09:30 ET, a marker each day) and futures-session starts (the first bar after 18:00 ET or after a gap)
function hmSessions(times){
  const opens = [], starts = [];
  times.forEach((t, i) => {
    const clock = hmFmt.hm.format(new Date(t * 1000));
    if(clock === "09:30"){ const q = Object.fromEntries(hmFmt.wd.formatToParts(new Date(t * 1000)).map(x => [x.type, x.value])); opens.push([t, `${q.weekday} ${q.day}`]); }
    if(i === 0 || clock === "18:00" || t - times[i - 1] > 3600) starts.push(i);
  });
  return {opens, starts};
}
// one column per candle: snapshots that fall in the same bar are averaged band by band (several 2 px
// slivers drawn on top of each other stacked their colour into stripes)
function hmPerBar(cols, times){
  const out = [];
  for(const c of cols){
    const bar = hmSnap(times, c.t), prev = out[out.length - 1];
    if(prev && prev._bar === bar && !!prev.rel === !!c.rel && prev.w === c.w && prev.base === c.base && prev.v.length === c.v.length){
      prev._n++; prev.v = prev.v.map((v, b) => v + (c.v[b] - v) / prev._n);   // running mean
      Object.assign(prev, {zg: c.zg, cw: c.cw, pw: c.pw, t: c.t});
    } else out.push({...c, v: c.v.slice(), _bar: bar, _n: 1});
  }
  return out;
}
// each band averaged with the same price band in the snapshots around it (same kind only), so
// back-to-back snapshots that differ slightly don't paint as stripes; the tooltip keeps the raw values
function hmSmooth(cols, k = 3){
  return cols.map((c, i) => {
    const sum = new Map(), n = [];
    for(let j = Math.max(0, i - k); j <= Math.min(cols.length - 1, i + k); j++){
      const o = cols[j];
      if(!!o.rel !== !!c.rel || o.w !== c.w) continue;
      n.push(j);
      o.v.forEach((v, b) => { const key = Math.round((o.base + b * o.w) * 100); sum.set(key, (sum.get(key) || 0) + v); });
    }
    return {...c, v: c.v.map((_, b) => (sum.get(Math.round((c.base + b * c.w) * 100)) || 0) / n.length)};
  });
}
// the heat as one image over the whole chart: a pixel per candle across, and 4 per price band down (top = highest).
// Each candle shows the latest snapshot at or before it. A band's middle rows keep its own value and only its edge
// rows blend a quarter of the neighbouring band, so bands stay crisp with soft edges when the image is stretched
const HM_ROWS = 4, HM_FLOOR = 0.18;
// a candle more than 90 minutes after the newest saved snapshot has no GEX: it gets the hatched "no saved GEX" ground
// instead of an old snapshot's colour (the hosted build runs every few minutes while futures trade, hourly when closed)
const HM_GAP_S = 5400;
// the runs of candles with no saved GEX, as [first, last] candle indexes
function hmGaps(times, cols){
  const out = []; let ci = -1;
  for(let k = 0; k < times.length; k++){
    while(ci + 1 < cols.length && (cols[ci + 1]._bar == null || cols[ci + 1]._bar <= times[k])) ci++;
    if(ci < 0 || times[k] - cols[ci].t <= HM_GAP_S) continue;
    const last = out[out.length - 1];
    last && last[1] === k - 1 ? last[1] = k : out.push([k, k]);
  }
  return out;
}
function hmAtlas(pos, neg, maxA){
  const C = hm._cols, times = hm._times, N = times.length;
  if(!C.length || !N) return null;
  const ws = {}; C.forEach(c => ws[c.w] = (ws[c.w] || 0) + 1);
  const w = Number(Object.keys(ws).sort((a, b) => ws[b] - ws[a])[0]);        // the usual band width
  const lo = Math.min(...C.map(c => c.base)), hi = Math.max(...C.map(c => c.base + (c.v.length - 1) * c.w));
  const B = Math.min(500, Math.round((hi - lo) / w) + 1), H = B * HM_ROWS;
  const cv = document.createElement("canvas"); cv.width = N; cv.height = H;
  const g = cv.getContext("2d"), img = g.createImageData(N, H), d = img.data;
  const band = new Float64Array(B + 2);                    // this candle's values per band, with an empty band each side
  let ci = -1, done = -1;
  for(let k = 0; k < N; k++){
    while(ci + 1 < C.length && (C[ci + 1]._bar == null || C[ci + 1]._bar <= times[k])) ci++;
    if(ci < 0) continue;                                   // before the first snapshot: no heat
    const c = C[ci], scale = c.rel ? 99 : hm._scale;
    if(times[k] - c.t > HM_GAP_S) continue;                // no saved GEX this late: the hatched ground, not old colour
    if(done !== ci){ for(let b = 0; b < B; b++) band[b + 1] = c.v[Math.round((hi - b * w - c.base) / c.w)] || 0; done = ci; }
    for(let r = 0; r < H; r++){
      const b = Math.floor(r / HM_ROWS) + 1, sub = r % HM_ROWS;
      const v = sub === 0 ? .75 * band[b] + .25 * band[b - 1] : sub === HM_ROWS - 1 ? .75 * band[b] + .25 * band[b + 1] : band[b];
      const a0 = Math.min(1, Math.abs(v) / scale);
      if(a0 < HM_FLOOR) continue;                          // noise floor: only bands with real gamma get colour
      const a = Math.pow((a0 - HM_FLOOR) / (1 - HM_FLOOR), 0.8) * maxA, rgb = v > 0 ? pos : neg, q = (r * N + k) * 4;
      d[q] = rgb[0]; d[q + 1] = rgb[1]; d[q + 2] = rgb[2]; d[q + 3] = Math.round(a * 255);
    }
  }
  g.putImageData(img, 0, 0);
  return {cv, lo: hi - (B - 1) * w, hi, w, N, H};            // lo as drawn (the band count is capped)
}
// bar time at or before t (columns snap to the candle they fall in)
function hmSnap(times, t){ let lo = 0, hi = times.length - 1; if(hi < 0 || t < times[0]) return null; while(lo < hi){ const m = (lo + hi + 1) >> 1; times[m] <= t ? lo = m : hi = m - 1; } return times[lo]; }
class HeatPrimitive {
  constructor(){ this._view = {zOrder: () => "bottom", renderer: () => ({draw: target => this.draw(target)})}; }
  attached(p){ this.chart = p.chart; this.series = p.series; this.requestUpdate = p.requestUpdate; }
  detached(){ this.chart = null; }
  updateAllViews(){}
  paneViews(){ return [this._view]; }
  draw(target){
    if(!this.chart || !hm || !hm._cols || !hm._cols.length) return;
    const ts = this.chart.timeScale(), times = hm._times, fac = hm.factor, off = hm.offset;
    const pos = rgbOf(cssVar("--pos")), neg = rgbOf(cssVar("--neg")), maxA = hmOpacity / 100;
    target.useBitmapCoordinateSpace(sc => {
      const ctx = sc.context, hr = sc.horizontalPixelRatio, vr = sc.verticalPixelRatio, W = sc.bitmapSize.width;
      // a snapshot before the first candle has no bar: it sits at the left edge
      const xOf = bt => bt == null ? 0 : ts.timeToCoordinate(bt);
      // the clear space right of the last candle holds the latest profile (the heat image ends at the last bar)
      const lastX = times.length ? ts.timeToCoordinate(times[times.length - 1]) : null, bar = ts.options().barSpacing || 6;
      const key = [hmOpacity, pos, neg].join();
      if(hm._atlasKey !== key){ hm._atlas = hmAtlas(pos, neg, maxA); hm._atlasKey = key; }
      const A = hm._atlas;
      if(A){
        // first and last bar centres (the library returns 0 for half-bar positions), widened by half a bar
        const x0 = ts.logicalToCoordinate(0), xn = ts.logicalToCoordinate(A.N - 1), half = A.N > 1 ? (xn - x0) / (A.N - 1) / 2 : bar / 2;
        const xa = x0 == null ? null : x0 - half, xb = xn == null ? null : xn + half;
        const ya = this.series.priceToCoordinate((A.hi + A.w / 2) * fac + off), yb = this.series.priceToCoordinate((A.lo - A.w / 2) * fac + off);
        if(xa != null && xb != null && ya != null && yb != null){
          ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
          ctx.drawImage(A.cv, 0, 0, A.N, A.H, xa * hr, ya * vr, (xb - xa) * hr, (yb - ya) * vr);
        }
        // the stretches with no saved GEX: a hatched ground that says so, never an old snapshot's colour
        if(x0 != null && xn != null){
          const Hb = sc.bitmapSize.height, pc = document.createElement("canvas"), st = Math.max(6, Math.round(8 * hr));
          pc.width = pc.height = st;
          const pg = pc.getContext("2d"); pg.strokeStyle = `rgba(${cssVar("--fg-rgb")},.16)`; pg.lineWidth = Math.max(1, hr);
          pg.beginPath(); pg.moveTo(0, st); pg.lineTo(st, 0); pg.stroke();
          ctx.save(); ctx.fillStyle = ctx.createPattern(pc, "repeat");
          ctx.font = `600 ${Math.round(10.5 * vr)}px ${cssVar("--mono") || "monospace"}`;
          for(const [k0, k1] of hm._gaps){
            const ga = (x0 + (xn - x0) * k0 / Math.max(1, A.N - 1) - half) * hr, gb = (x0 + (xn - x0) * k1 / Math.max(1, A.N - 1) + half) * hr;
            ctx.fillRect(ga, 0, gb - ga, Hb);
            const txt = "no saved GEX";
            if(gb - ga > ctx.measureText(txt).width + 16 * hr){
              ctx.fillStyle = `rgba(${cssVar("--fg-rgb")},.6)`; ctx.fillText(txt, ga + 8 * hr, Hb - 10 * vr); ctx.fillStyle = ctx.createPattern(pc, "repeat"); }
          }
          ctx.restore();
        }
      }
      // session markers: a faint line at each 09:30 ET cash open, with the day on top
      const Hpx = sc.bitmapSize.height, fs = Math.round(10.5 * vr);
      ctx.font = `600 ${fs}px ${cssVar("--mono") || "monospace"}`;
      ctx.fillStyle = ctx.strokeStyle = `rgba(${cssVar("--fg-rgb")},.28)`;
      ctx.lineWidth = Math.max(1, Math.round(vr)); ctx.setLineDash([3 * hr, 4 * hr]);
      // a day's label is drawn only where it clears the previous one and the GEX label on the right (phones, 2 days)
      const gx0 = lastX == null ? null : lastX + bar * 2;        // where the GEX label goes, when it is drawn (below)
      const gexX = gx0 != null && hm._profile && W / hr - gx0 - 6 >= 50 ? gx0 * hr : Infinity;
      let labEnd = -Infinity;
      for(const [t, lbl] of hm._opens || []){
        const x = ts.timeToCoordinate(t); if(x == null) continue;
        const X = Math.round(x * hr) + .5;
        ctx.beginPath(); ctx.moveTo(X, fs + 6 * vr); ctx.lineTo(X, Hpx); ctx.stroke();
        const txt = lbl + " open", x0 = X + 4 * hr, x1 = x0 + ctx.measureText(txt).width;
        if(x0 >= 0 && x0 >= labEnd + 8 * hr && x1 <= gexX - 8 * hr){ ctx.fillText(txt, x0, fs + 2 * vr); labEnd = x1; }
      }
      ctx.setLineDash([]);
      // the latest GEX profile and today's key levels, in the space right of the last candle
      const px0 = lastX == null ? null : lastX + bar * 2, pw = px0 == null ? 0 : W / hr - px0 - 6;
      if(hm._profile && pw >= 50){
        const P = hm._profile, mx = Math.max(1e-9, ...P.v.map(Math.abs)), len = pw * .5;
        ctx.globalAlpha = .9;
        P.v.forEach((v, j) => {
          if(!v) return;
          const p = (P.base + j * P.w) * fac + off, ya = this.series.priceToCoordinate(p + P.w * fac * .4), yb = this.series.priceToCoordinate(p - P.w * fac * .4);
          if(ya == null || yb == null) return;
          const rgb = v > 0 ? pos : neg;
          ctx.fillStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},.75)`;
          ctx.fillRect(Math.round(px0 * hr), Math.round(ya * vr), Math.max(1, Math.round(Math.abs(v) / mx * len * hr)), Math.max(1, Math.round((yb - ya) * vr)));
        });
        ctx.globalAlpha = 1;
        ctx.fillStyle = `rgba(${cssVar("--fg-rgb")},.45)`;
        const pt = new Date(P.t * 1000);       // the profile's own time: after a Cboe outage it is not "now"
        ctx.fillText(`GEX ${pt.toLocaleDateString("en-US", {...ET, weekday: "short"})} ${hmFmt.hm.format(pt)}`, Math.round(px0 * hr), fs + 2 * vr);
        if(hmShowLv) for(const m of hm._marks || []){
          const y = this.series.priceToCoordinate(m.p); if(y == null) continue;
          const Y = Math.round(y * vr) + .5;
          ctx.strokeStyle = m.col; ctx.fillStyle = m.col; ctx.lineWidth = Math.max(1, Math.round(1.5 * vr));
          ctx.beginPath(); ctx.moveTo(Math.round(px0 * hr), Y); ctx.lineTo(Math.round((px0 + pw * .54) * hr), Y); ctx.stroke();
          ctx.fillText(m.label, Math.round((px0 + pw * .56) * hr), Y + fs * .35);
        }
      }
      // walls: one solid line per stretch where the wall held for at least 12 bars (an hour on 5m); shorter
      // stays and zero gamma (an estimate that moves every snapshot) only show as axis labels
      if(!hmShowLv || !hm._lv) return;
      const MIN_BARS = 12;
      ctx.lineWidth = Math.max(1, Math.round(vr)); ctx.globalAlpha = .75;
      for(const [k, col] of [["cw", cssVar("--pos")], ["pw", cssVar("--neg")]]){
        ctx.strokeStyle = col;
        let run = null;
        const flush = () => {
          if(run && run.n >= MIN_BARS){ const y = this.series.priceToCoordinate(run.v);
            if(y != null){ ctx.beginPath(); ctx.moveTo(Math.round(run.x0 * hr), Math.round(y * vr) + .5); ctx.lineTo(Math.round(run.x1 * hr), Math.round(y * vr) + .5); ctx.stroke(); } }
          run = null; };
        hm._lv[k].forEach(([x0t, x1t, v], i, all) => {
          const x0 = xOf(x0t), x1 = i === all.length - 1 ? W / hr : xOf(x1t);
          if(v == null || x0 == null){ flush(); return; }
          if(run && run.v === v){ run.x1 = x1 ?? run.x1; run.n++; } else { flush(); run = {v, x0, x1: x1 ?? x0, n: 1}; }
        });
        flush();
      }
      ctx.globalAlpha = 1;
    });
  }
}
const hmGexW = () => Math.min(190, Math.round(Math.max(300, $("hmChart").clientWidth - 80) * 0.38));
function hmColors(){
  return {layout: {background: {type: "solid", color: lcVar("--panel")}, textColor: lcVar("--ink3"), fontFamily: cssVar("--mono"), fontSize: 11},
    grid: {vertLines: {visible: false}, horzLines: {visible: false}},
    rightPriceScale: {borderColor: `rgba(${cssVar("--fg-rgb")},.1)`}, timeScale: {borderColor: `rgba(${cssVar("--fg-rgb")},.1)`, timeVisible: true, secondsVisible: false},
    crosshair: {mode: 0, vertLine: {color: `rgba(${cssVar("--fg-rgb")},.3)`}, horzLine: {color: `rgba(${cssVar("--fg-rgb")},.3)`}}};
}
function renderHeatmap(){
  $("hmSpan").innerHTML = [["today", "Today"], ["2d", "2 days"], ["all", "All"]].map(([k, t]) => `<button role="tab" aria-selected="${hmSpan === k}" data-k="${k}">${t}</button>`).join("");
  [...$("hmSpan").children].forEach(b => b.onclick = () => { hmSpan = b.dataset.k; store.set("gex.hmspan2", hmSpan); hmReset = true; renderHeatmap(); });
  $("hmTf").innerHTML = [["1m", "1m"], ["5m", "5m"], ["15m", "15m"]].map(([k, t]) => `<button role="tab" aria-selected="${hmTf === k}" data-k="${k}">${t}</button>`).join("");
  [...$("hmTf").children].forEach(b => b.onclick = () => { hmTf = b.dataset.k; store.set("gex.hmtf", hmTf); hmReset = true; loadHeatmap(); });
  $("hmOpacity").value = hmOpacity; $("hmLevels").checked = hmShowLv;
  if(!hm || !window.LightweightCharts) return;
  const LC = window.LightweightCharts;
  if(!hm.candles.length && !hm.columns.length){ $("hmMsg").textContent = "No candles or GEX history yet. They appear after the next refresh."; $("hmMsg").hidden = false; return; }
  $("hmMsg").hidden = true;
  hm._times = hm.candles.map(c => c[0]);
  const vals = hm.columns.filter(c => !c.rel).flatMap(c => c.v.map(Math.abs)).filter(v => v > 0).sort((a, b) => a - b);
  hm._scale = vals.length ? vals[Math.floor(vals.length * 0.97)] || 1 : 1;
  hm._cols = hmSmooth(hmPerBar(hm.columns, hm._times), hmTf === "1m" ? 3 : hmTf === "5m" ? 2 : 1);
  hm._gaps = hmGaps(hm._times, hm._cols);
  hm._atlasKey = null;                                     // the heat image is rebuilt from these columns on the next draw
  const ses = hmSessions(hm._times);
  hm._opens = ses.opens; hm._starts = ses.starts;
  hm._profile = [...hm.columns].reverse().find(c => !c.rel) || null;
  // today's key levels from the latest calculation: the first expiry's C / P / Ab (index + ETF, as the indicator ranks them) and its flip
  const wk = data && data.workers.find(x => x.market === market && x.result), nr = wk && ((wk.result.summary.extras || {}).nearest || {});
  const rk = nr && (nr.ranked || nr.ranked_etf);
  const fut = p => Math.round((p * hm.factor + hm.offset) * 4) / 4;
  hm._marks = !rk ? [] : [
    ...(rk.call || []).slice(0, 2).map((x, i) => ({p: fut(x.price), label: "C" + (i + 1), col: cssVar("--pos")})),
    ...(rk.put || []).slice(0, 2).map((x, i) => ({p: fut(x.price), label: "P" + (i + 1), col: cssVar("--neg")})),
    ...(rk.abs || []).slice(0, 1).map(x => ({p: fut(x.price), label: "Ab1", col: cssVar("--ag") || "#a78bfa"})),
    ...(nr.zero_gamma && nr.zero_gamma.price != null ? [{p: fut(nr.zero_gamma.price), label: "0D flip", col: cssVar("--zg")}] : [])];
  // merge marks at the same price into one label (C1 · Ab1)
  hm._marks = hm._marks.reduce((a, m) => { const o = a.find(x => Math.abs(x.p - m.p) < 0.5); if(o) o.label += " · " + m.label; else a.push({...m}); return a; }, []);
  const fresh = !hmChart;
  if(fresh){
    hmChart = LC.createChart($("hmChart"), Object.assign({autoSize: true, handleScale: {axisPressedMouseMove: true}}, hmColors()));
    hmChart.applyOptions(hmTimeOpts());
    // two days of 1-minute bars (~2,700) must fit the width: below the library's default minimum bar spacing
    // (0.5 px) it ignores the requested range and falls back to its default zoom
    hmChart.applyOptions({timeScale: {minBarSpacing: 0.05}});
    // a real width change (window resize, phone rotation) re-frames the chosen span; the library alone keeps the old
    // bar spacing, so a wider window showed empty days on the left (sweep 2026-11-21)
    let hmW = $("hmChart").clientWidth, hmRT = 0;
    new ResizeObserver(() => { const w = $("hmChart").clientWidth;
      if(w >= 100 && Math.abs(w - hmW) > 40){ hmW = w; clearTimeout(hmRT); hmRT = setTimeout(() => { hmReset = true; renderHeatmap(); }, 200); } }).observe($("hmChart"));
    hmCandles = hmChart.addCandlestickSeries({upColor: lcVar("--good"), downColor: lcVar("--bad"), borderVisible: false, wickUpColor: lcVar("--good"), wickDownColor: lcVar("--bad"),
      priceLineVisible: true, priceLineStyle: LC.LineStyle.Dotted, priceLineWidth: 1});
    hmPrim = new HeatPrimitive(); hmCandles.attachPrimitive(hmPrim);
    hmChart.subscribeCrosshairMove(hmHover);
    let roTimer = null;
    hmChart.timeScale().subscribeVisibleLogicalRangeChange(() => { clearTimeout(roTimer); roTimer = setTimeout(() => {
      const want = Math.max(16, Math.ceil(hmGexW() / (hmChart.timeScale().options().barSpacing || 6)));
      if(Math.abs(want - hmChart.timeScale().options().rightOffset) > 2) hmChart.timeScale().applyOptions({rightOffset: want}); }, 150); });
    $("hmChart").appendChild($("hmTip")); $("hmChart").appendChild($("hmMsg"));   // keep them above the chart's canvases
  } else { hmChart.applyOptions(hmColors()); hmChart.applyOptions(hmTimeOpts()); }
  // room right of the last candle for the latest profile: about 190 px (less on a phone), whatever the zoom
  const ro = Math.max(16, Math.ceil(hmGexW() / (hmChart.timeScale().options().barSpacing || 6)));
  hmChart.timeScale().applyOptions({rightOffset: ro});
  // keep the user's zoom only for a redraw of the same data's market and timeframe (a range picked while
  // another timeframe loads applies when that data arrives)
  const keep = !hmReset && hmMarket === hm._key ? hmChart.timeScale().getVisibleLogicalRange() : null;
  hmCandles.setData(hm.candles.map(c => ({time: c[0], open: c[1], high: c[2], low: c[3], close: c[4]})));
  // level paths (steadied) as [from bar, to bar, price] per snapshot; today's values as axis labels only
  hm._lv = {};
  const C = hm._cols;
  for(const k of ["cw", "pw"]){
    const st = hmSteady(C.map(c => c[k] == null ? null : Math.round((c[k] * hm.factor + hm.offset) * 4) / 4));
    hm._lv[k] = C.map((c, i) => [c._bar, C[i + 1] ? C[i + 1]._bar : null, st[i]]);
  }
  (hmLines.tags || []).forEach(l => hmCandles.removePriceLine(l));
  const lastCol = hm.columns[hm.columns.length - 1];
  hmLines.tags = !hmShowLv || !lastCol ? [] : [["zg", "ZG", cssVar("--zg")], ["cw", "CW", cssVar("--pos")], ["pw", "PW", cssVar("--neg")]]
    .filter(([k]) => lastCol[k] != null)
    .map(([k, title, color]) => hmCandles.createPriceLine({price: Math.round((lastCol[k] * hm.factor + hm.offset) * 4) / 4, color, title, lineVisible: false, axisLabelVisible: true}));
  if(keep) hmChart.timeScale().setVisibleLogicalRange(keep);
  else if($("hmChart").clientWidth < 100){                 // not laid out yet (a hidden tab): set the view once it has a size
    hmReset = true;
    const ro0 = new ResizeObserver(() => { if($("hmChart").clientWidth >= 100){ ro0.disconnect(); renderHeatmap(); } }); ro0.observe($("hmChart"));
  } else {
    hmCandles.priceScale().applyOptions({autoScale: true}); hmReset = false;
    const n = hm.candles.length, st = hm._starts || [0];
    // a session under 3 hours old (just after the 18:00 reopen) is too short to count as one of the days shown
    const young = st.length > 1 && n && hm._times[n - 1] - hm._times[st[st.length - 1]] < 3 * 3600 ? 1 : 0;
    const from = Math.max(0, (hmSpan === "all" ? 0 : st[Math.max(0, st.length - (hmSpan === "2d" ? 2 : 1) - young)] || 0) - 2);
    // pick the right offset so the profile space is hmGexW() once the candles fill the rest of the width
    const plot = Math.max(300, $("hmChart").clientWidth - 80), bars = Math.max(1, n - from), gw = hmGexW();
    const ro2 = Math.max(16, Math.round(gw * bars / Math.max(100, plot - gw)));
    hmChart.timeScale().applyOptions({rightOffset: ro2});
    hmChart.timeScale().setVisibleLogicalRange({from, to: n + ro2});
    // autoSize measures the box a frame later and then keeps its default zoom: set the span again once it has
    requestAnimationFrame(() => requestAnimationFrame(() => hmChart.timeScale().setVisibleLogicalRange({from, to: n + ro2})));
  }
  if(hm._key === market + hmTf) hmMarket = hm._key;
  const rel = hm.columns.filter(c => c.rel).length;
  const hw = data && data.workers.find(x => x.market === market && x.result), hbk = hw && hw.result.summary.backup;
  $("hmSub").textContent = `${market} futures · ${hmAsOf(hm, hmTf)}${hbk ? " · Cboe snapshots only: the backup estimate is not saved, so no GEX after the last one" : ""}`;
  $("hmNote").textContent = rel ? `${rel} older snapshot${rel === 1 ? "" : "s"} shown at relative strength` : "";
  $("hmScale").innerHTML = `<i class="hm-ramp"></i>brightest ≈ ±${money(hm._scale * 1e6).replace(/^[+-]/, "")} of gamma per 1% move`;
  hmPrim.requestUpdate && hmPrim.requestUpdate();
}
function hmHover(p){
  const tip = $("hmTip");
  if(!p || !p.time || !p.point || !hm){ tip.classList.remove("on"); return; }
  const price = hmCandles.coordinateToPrice(p.point.y);
  let col = null; for(const c of hm.columns){ if(hmSnap(hm._times, c.t) <= p.time) col = c; else break; }
  if(price == null || !col){ tip.classList.remove("on"); return; }
  if(p.time - col.t > HM_GAP_S){
    tip.innerHTML = `<b>${num(price, 2)}</b> · no GEX saved for this time<br><span class="c-ink3">the newest saved snapshot is ${esc(new Date(col.t * 1000).toLocaleString("en-US", {...ET, weekday: "short", hour: "numeric", minute: "2-digit"}))} ET</span>`;
    tipAt(tip, Math.min(p.point.x + 16, $("hmChart").clientWidth - 260), Math.max(8, p.point.y - 60)); return; }
  const j = Math.round(((price - hm.offset) / hm.factor - col.base) / col.w), v = col.v[j];
  const when = new Date(col.t * 1000).toLocaleString("en-US", {...ET, weekday: "short", hour: "numeric", minute: "2-digit"});
  tip.innerHTML = `<b>${num(price, 2)}</b> · snapshot ${esc(when)} ET<br>${v == null ? "outside the saved range" : col.rel ? `relative gamma ${signed(v, 0)} (older snapshot)` : `net GEX <b class="${v >= 0 ? "c-pos" : "c-neg"}">${money(v * 1e6)}</b> per 1%`}`
    + `<br><span class="c-ink3">ZG ${num(col.zg * hm.factor + hm.offset, 0)} · CW ${num(col.cw * hm.factor + hm.offset, 0)} · PW ${num(col.pw * hm.factor + hm.offset, 0)}</span>`;
  tipAt(tip, Math.min(p.point.x + 16, $("hmChart").clientWidth - 260), Math.max(8, p.point.y - 60));
}
window.__hmTheme = () => { if(hmChart) renderHeatmap(); };
window.__hmOpen = () => { hmReset = true; if(data) loadHeatmap(); };
$("hmOpacity").addEventListener("input", e => { hmOpacity = Number(e.target.value); store.set("gex.hmop", String(hmOpacity)); hmPrim && hmPrim.requestUpdate && hmPrim.requestUpdate(); });
$("hmLevels").addEventListener("change", e => { hmShowLv = e.target.checked; store.set("gex.hmlv", hmShowLv ? "1" : "0"); renderHeatmap(); });

// ---------- screener: the stocks that move NQ and ES (index weights x today's move, in futures points)
let scr = null, scrSort = store.get("gex.drvsort", "impact"), scrDir = Number(store.get("gex.drvdir", "-1")) || -1;
const SCR_COLS = [["symbol", "Stock"], ["spark", "20 days"], ["price", "Price"], ["pct", "Today"], ["ext", "Pre / after"],
  ["weight", "Weight"], ["impact", "Index pts"], ["rel_volume", "Rel vol"], ["earnings", "Earnings"]];
async function loadScreener(){
  try { scr = await (await fetchFresh(STATIC ? "data/screener.json" : "/api/screener")).json(); }
  catch(e){ if(!scr) $("drvRows").innerHTML = `<tr><td colspan="9" class="expl">${esc(offline())}</td></tr>`; return; }
  renderScreener();
}
function spark(v){
  if(!v || v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v), W = 64, H = 18, x = i => (i / (v.length - 1) * W).toFixed(1), y = p => (H - 1 - (hi > lo ? (p - lo) / (hi - lo) : .5) * (H - 2)).toFixed(1);
  return `<svg class="drv-spark" viewBox="0 0 ${W} ${H}" aria-hidden="true"><polyline fill="none" stroke="var(${v[v.length - 1] >= v[0] ? "--good" : "--bad"})" stroke-width="1.2" points="${v.map((p, i) => x(i) + "," + y(p)).join(" ")}"/></svg>`;
}
const earnSoon = e => e && (Date.parse(e.date + "T12:00:00Z") - Date.now()) / 864e5 <= 7;
const earnTxt = e => e ? new Date(e.date + "T12:00:00Z").toLocaleDateString("en-US", {weekday: "short", month: "short", day: "numeric", timeZone: "UTC"}) + (e.when ? " · " + (e.when === "before open" ? "BMO" : "AMC") : "") : "-";
function renderScreener(){
  if(!scr || !scr.stocks){ return; }
  const k = market === "ES" ? "es" : "nq", T = (scr.totals || {})[market] || {}, F = T.futures;
  let rows = scr.stocks.filter(r => r["w_" + k]);
  if(!rows.length){ $("drvRows").innerHTML = `<tr><td colspan="9" class="expl">No ${market} drivers yet. They appear after the next refresh.</td></tr>`; return; }
  const key = {impact: r => r["pts_" + k], weight: r => r["w_" + k], ext: r => r.ext && r.ext.pct, spark: r => r.spark && r.spark.length > 1 ? r.spark[r.spark.length - 1] / r.spark[0] : null,
               earnings: r => r.earnings ? Date.parse(r.earnings.date) : null}[scrSort] || (r => r[scrSort]);
  rows = rows.slice().sort((a, b) => { let x = key(a), y = key(b);
    if(scrSort === "impact"){ x = x == null ? null : Math.abs(x); y = y == null ? null : Math.abs(y); }
    if(x == null) return 1; if(y == null) return -1;
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * (scrSort === "earnings" ? -scrDir : scrDir); });
  // summary: what the biggest names are doing to the future right now
  const pts = T.pts || 0, ext = T.ext_pts || 0, by = scr.stocks.filter(r => r["pts_" + k] != null).sort((a, b) => b["pts_" + k] - a["pts_" + k]);
  const top = by[0], bot = by[by.length - 1], up = T.up || 0, dn = T.down || 0;
  const sg = (x, d = 1) => `<b class="${x > 0 ? "good" : x < 0 ? "bad" : ""}">${signed(x, d)}</b>`;
  $("drvSum").innerHTML = `
    <div class="drv-fut"><div class="eyebrow">${market} future${scr.fetched ? ` · fetched ${etTime(scr.fetched)} ET` : ""}</div><div class="big">${F ? num(F.price, 2) : "-"}</div>
      <div class="drv-chg">${F ? sg(F.change, 2) + ` pts · ${signed(F.pct, 2)}%` : ""}</div></div>
    <div class="drv-kv"><span>Top ${T.names || 0} stocks' move</span>${sg(pts)} <em>pts of ${market}</em></div>
    <div class="drv-kv"><span>They make up</span><b>${num(T.weight, 1)}%</b> <em>of the ${market === "ES" ? "S&P 500" : "Nasdaq-100"}</em></div>
    ${ext ? `<div class="drv-kv"><span>Pre / after-hours moves imply</span>${sg(ext)} <em>pts</em></div>` : ""}
    <div class="drv-breadth" title="${up} up, ${dn} down"><i class="good" style="flex:${up}"></i><i class="bad" style="flex:${dn}"></i></div>
    <div class="drv-kv sm"><span>${up} up · ${dn} down</span>${top && top["pts_" + k] > 0 ? `<em>lifting most: <b>${esc(top.symbol)}</b> ${signed(top["pts_" + k], 1)}</em>` : ""}${bot && bot["pts_" + k] < 0 ? `<em>dragging most: <b>${esc(bot.symbol)}</b> ${signed(bot["pts_" + k], 1)}</em>` : ""}</div>`;
  // contribution bars, biggest push at the top
  const mx = Math.max(1e-9, ...by.map(r => Math.abs(r["pts_" + k])));
  $("drvBars").innerHTML = by.map(r => { const v = r["pts_" + k], w = (Math.abs(v) / mx * 50).toFixed(1);
    return `<div class="drv-bar" title="${esc(r.name)}: ${signed(r.pct, 2)}% × ${num(r["w_" + k], 2)}% weight"><span class="s">${esc(r.symbol)}</span>
      <span class="t"><i class="${v >= 0 ? "good" : "bad"}" style="${v >= 0 ? "left:50%" : "right:50%"};width:${w}%"></i></span><span class="v ${v >= 0 ? "good" : "bad"}">${signed(v, 1)}</span></div>`; }).join("");
  // earnings coming up among the drivers
  // reports still ahead (today or later, ET), plus last night's report until the session it moves opens
  const todayET = new Date().toLocaleDateString("en-CA", ET);
  const soon = scr.stocks.filter(r => r["w_" + k] && r.earnings && (r.earnings.date >= todayET || r.earn_move))
    .sort((a, b) => a.earnings.date.localeCompare(b.earnings.date)).slice(0, 8);
  $("drvEarn").innerHTML = soon.length ? soon.map(r => `<span class="drv-e${earnSoon(r.earnings) ? " hot" : ""}"${r.earn_move ? ` title="Options price ±${num(r.earn_move.pct, 1)}% through the ${esc(r.earn_move.expiry.slice(5))} expiry (at-the-money straddle)"` : ""}><b>${esc(r.symbol)}</b>${esc(earnTxt(r.earnings))}${r.earn_move ? `<i>±${num(r.earn_move.pct, 1)}% · ±${num(Math.abs(r["earn_pts_" + k] || 0), 0)} ${esc(market)} pts</i>` : ""}</span>`).join("")
    : `<span class="expl">No driver reports in the next 30 days.</span>`;
  // table
  $("drvHead").innerHTML = SCR_COLS.map(([c, t]) => `<th data-k="${c}" class="${scrSort === c ? "on" : ""}" aria-sort="${scrSort === c ? (scrDir > 0 ? "ascending" : "descending") : "none"}">${t}${scrSort === c ? (scrDir > 0 ? " ▲" : " ▼") : ""}</th>`).join("");
  [...$("drvHead").children].forEach(th => th.onclick = () => { const c = th.dataset.k;
    if(scrSort === c) scrDir = -scrDir; else { scrSort = c; scrDir = c === "symbol" ? 1 : -1; }
    store.set("gex.drvsort", scrSort); store.set("gex.drvdir", String(scrDir)); renderScreener(); });
  // the 15 biggest weights in this index open a chart when clicked; the rest link to TradingView
  const top15 = new Set(rows.slice().sort((a, b) => b["w_" + k] - a["w_" + k]).slice(0, 15).map(r => r.symbol));
  $("drvRows").innerHTML = rows.map(r => { const v = r["pts_" + k], cls = x => x > 0 ? "good" : x < 0 ? "bad" : "", ch = top15.has(r.symbol);
    const sym = ch ? `<span class="scr-sym">${esc(r.symbol)}</span>` : `<a class="scr-sym" href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent(r.symbol.replace("-", "."))}" target="_blank" rel="noopener" title="Open ${esc(r.symbol)} on TradingView">${esc(r.symbol)}</a>`;
    return `<tr class="${ch ? "clk" : ""}${r.stale ? " stale" : ""}"${ch ? ` data-sym="${esc(r.symbol)}" role="button" tabindex="0" title="Click for ${esc(r.symbol)}'s chart"` : r.stale ? ' title="Could not refresh: last known price"' : ""}><td title="${esc(r.name)}">${sym}${ch ? '<svg class="scr-ic" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 13h12M4 10l3-3 2 2 4-5"/></svg>' : ""}</td>
      <td>${spark(r.spark)}</td>
      <td class="m">${num(r.price, 2)}</td>
      <td class="m ${cls(r.pct)}">${signed(r.pct, 2)}%</td>
      <td class="m ${r.ext ? cls(r.ext.pct) : ""}">${r.ext ? `<span class="drv-tag">${r.ext.session === "pre" ? "PRE" : "AH"}</span>${signed(r.ext.pct, 2)}%` : "-"}</td>
      <td class="m">${num(r["w_" + k], 2)}%</td>
      <td class="m drv-imp ${cls(v)}">${v == null ? "-" : signed(v, 1)}</td>
      <td class="m${r.rel_volume >= 1.5 ? " hot" : ""}">${r.rel_volume == null ? "-" : num(r.rel_volume, 1) + "×"}</td>
      <td class="m${earnSoon(r.earnings) ? " hot" : ""}">${esc(earnTxt(r.earnings))}</td></tr>`; }).join("");
  const when = new Date(scr.fetched).toLocaleString("en-US", {...ET, hour: "numeric", minute: "2-digit"});
  const wd = scr.weights_asof ? new Date(scr.weights_asof).toLocaleDateString("en-US", {...ET, month: "short", day: "numeric"}) : "?";
  $("scrSub").textContent = `${rows.length} biggest ${market === "ES" ? "S&P 500" : "Nasdaq-100"} weights · prices ${when} ET · weights ${wd} · click a stock for its chart`;
  [...$("drvRows").querySelectorAll("tr[data-sym]")].forEach(tr => tr.onclick = () => openStockChart(tr.dataset.sym));
}

// ---------- screener: a chart for each of the top 15 drivers, from the bars the screener already downloads
let scCharts = null, scSym = "", scRange = store.get("gex.scrange", "intraday"), scChart = null, scSeries = null, scPrev = null;
// unix seconds -> the same wall-clock time in New York, as the chart's (UTC) time, so the axis reads ET
function chartTimeET(t){
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {...ET, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"})
    .formatToParts(new Date(t * 1000)).map(x => [x.type, x.value]));
  return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second) / 1000;
}
async function openStockChart(sym){
  scSym = sym; $("scChart").hidden = false; $("scMsg").hidden = false; $("scMsg").textContent = "…";
  let c = null;
  try {
    if(STATIC){ scCharts = scCharts || await (await fetchFresh("data/screener-charts.json")).json(); c = scCharts[sym]; }
    else c = await (await fetchFresh(`/api/screener/chart?symbol=${encodeURIComponent(sym)}`)).json();
  } catch(e){ if(sym === scSym) $("scMsg").textContent = offline(); return; }
  if(sym !== scSym) return;                              // another stock was clicked while this one loaded
  if(!c || !c.symbol){ $("scMsg").textContent = "No chart data for this stock yet."; return; }
  renderStockChart(c);
}
function renderStockChart(c){
  const LC = window.LightweightCharts, k = market === "ES" ? "es" : "nq", r = ((scr && scr.stocks) || []).find(x => x.symbol === c.symbol) || {};
  $("scTitle").textContent = `${c.symbol} · ${c.name}`;
  $("scTv").href = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(c.symbol.replace("-", "."))}`;
  const cls = x => x > 0 ? "good" : x < 0 ? "bad" : "";
  $("scInfo").innerHTML = `<b class="m">${num(r.price, 2)}</b><span class="m ${cls(r.pct)}">${r.pct == null ? "" : signed(r.pct, 2) + "%"}</span>`
    + (r.ext ? `<span class="m ${cls(r.ext.pct)}"><span class="drv-tag">${r.ext.session === "pre" ? "PRE" : "AH"}</span>${signed(r.ext.pct, 2)}%</span>` : "")
    + (r["w_" + k] ? `<span>${num(r["w_" + k], 2)}% of the ${market === "ES" ? "S&P 500" : "Nasdaq-100"}</span>` : "")
    + (r["pts_" + k] != null ? `<span class="m ${cls(r["pts_" + k])}">${signed(r["pts_" + k], 1)} ${market} pts</span>` : "")
    + (r.earnings ? `<span>earnings ${esc(earnTxt(r.earnings))}</span>` : "");
  $("scTf").innerHTML = [["intraday", "Last session · 5m"], ["daily", "3 months · daily"]].map(([v, t]) => `<button role="tab" aria-selected="${scRange === v}" data-k="${v}">${t}</button>`).join("");
  [...$("scTf").children].forEach(b => b.onclick = () => { scRange = b.dataset.k; store.set("gex.scrange", scRange); renderStockChart(c); });
  if(!LC){ $("scMsg").textContent = "The chart library could not load (it comes from unpkg.com)."; return; }
  const bars = (scRange === "daily" ? c.daily : c.intraday) || [];
  if(!bars.length){ $("scMsg").hidden = false; $("scMsg").textContent = scRange === "daily" ? "No daily bars yet." : "No bars today yet (they start with the pre-market)."; return; }
  $("scMsg").hidden = true;
  const tl = bars[bars.length - 1][0] * 1000;
  const tDay = new Date(tl).toLocaleDateString("en-US", {...ET, weekday: "short", month: "short", day: "numeric"});
  $("scInfo").insertAdjacentHTML("beforeend", `<span class="dim">as of ${esc(scRange === "daily" ? tDay : tDay + ", " + etTime(tl) + " ET")}</span>`);
  if(!scChart){
    scChart = LC.createChart($("scBox"), Object.assign({autoSize: true}, hmColors()));
    scSeries = scChart.addCandlestickSeries({borderVisible: false, priceLineVisible: true});
    $("scBox").appendChild($("scMsg"));
  } else scChart.applyOptions(hmColors());
  const up = lcVar("--good"), dn = lcVar("--bad"), ext = `rgba(${cssVar("--fg-rgb")},.35)`, [s0, s1] = c.session || [];
  scSeries.applyOptions({upColor: up, downColor: dn, wickUpColor: up, wickDownColor: dn});
  // pre-market and after-hours candles in grey, so the cash session stands out
  scSeries.setData(bars.map(([t, o, h, l, cl]) => {
    const out = scRange === "intraday" && s0 && s1 && (t < s0 || t >= s1);
    return Object.assign({time: scRange === "daily" ? chartTimeET(t) - chartTimeET(t) % 86400 : chartTimeET(t), open: o, high: h, low: l, close: cl}, out ? {color: ext, wickColor: ext} : {});
  }));
  if(scPrev){ scSeries.removePriceLine(scPrev); scPrev = null; }
  if(scRange === "intraday" && c.prev) scPrev = scSeries.createPriceLine({price: c.prev, color: lcVar("--ink3"), lineStyle: LC.LineStyle.Dashed, lineWidth: 1, title: "prev close"});
  scChart.timeScale().applyOptions({timeVisible: scRange === "intraday", secondsVisible: false});
  // dragging the price axis turns auto-fit off for good; every new stock or range starts fitted to its own prices
  scSeries.priceScale().applyOptions({autoScale: true});
  scChart.timeScale().fitContent();
  $("scFoot").textContent = scRange === "intraday" ? "5-minute candles in ET, Yahoo Finance (delayed). Grey candles: pre-market and after-hours. Dashed line: yesterday's close."
    : "Daily candles for the last 3 months, Yahoo Finance.";
}
function closeStockChart(){ $("scChart").hidden = true; }
$("scClose").onclick = closeStockChart;
$("scChart").onclick = e => { if(e.target === $("scChart")) closeStockChart(); };



// ---------- Levels page: today's plan and what changed since the session began
let planScr = null, planScrAt = 0;
function planEarnings(k){
  // drivers reporting before the next open, with the move their options price in (from the screener data)
  if(Date.now() - planScrAt > 5 * 60 * 1000){
    planScrAt = Date.now();
    fetchFresh(STATIC ? "data/screener.json" : "/api/screener").then(r => r.json()).then(d => { planScr = d; if(page === "levels" && data) renderPlan(curW()); }).catch(() => {});
  }
  return ((planScr && planScr.stocks) || []).filter(r => r["w_" + k] && r.earn_move && r.earnings)
    .sort((a, b) => Math.abs(b["earn_pts_" + k] || 0) - Math.abs(a["earn_pts_" + k] || 0)).slice(0, 4);
}
// ---------- level history (Levels page): each past session's levels from the last calculation before its 9:30 ET
// open, frozen by the track record, with how that day traded. Index levels are converted with today's basis, so
// they line up with a back-adjusted continuous chart (NQ1! / ES1!) the same way the indicator's past levels do
let lhAt = 0;
function loadLevelHistory(){
  if(trk && trk.sessions && Date.now() - lhAt < 10 * 60e3) return renderLevelHistory();
  lhAt = Date.now();
  fetchFresh(API.track).then(r => r.json()).then(d => { trk = d; renderLevelHistory(); if(page === "track") renderTrack(); }).catch(() => { lhAt = 0; });
}
function renderLevelHistory(){
  const w = curW(), mp = w && w.result && w.result.mapped && w.result.mapped.mapping;
  if(!trk || !trk.sessions){ $("lhTable").innerHTML = `<div class="expl"><span class="skeleton sk-line">Loading the saved sessions</span></div>`; return; }
  const f = (mp && mp.factor) || 1, o = (mp && mp.offset) || 0, fut = p => p == null ? null : Math.round((p * f + o) * 4) / 4;
  const ss = trk.sessions.filter(s => s.market === market && s.plan).sort((a, b) => b.session.localeCompare(a.session));
  $("lhSub").textContent = ss.length ? `${market} · ${ss.length} session${ss.length === 1 ? "" : "s"} since ${new Date(ss[ss.length - 1].session + "T12:00:00Z").toLocaleDateString("en-US", {month: "short", day: "numeric", timeZone: "UTC"})}` : "";
  $("lhNote").textContent = `Levels from the last calculation before each 9:30 ET open (the same plan the Track record grades), converted to ${market} with today's basis so they match a back-adjusted continuous chart (${market}1!). The TradingView indicator draws the last few sessions' closing levels on the chart ("Past sessions' levels" in its settings).`;
  if(!ss.length){ $("lhTable").innerHTML = `<div>${stateHtml("empty", `No ${market} sessions saved yet`, "The 9:30 ET paste of each session is saved here once that session has opened.")}</div>`; $("lhChart").innerHTML = ""; return; }
  const day = s => new Date(s + "T12:00:00Z").toLocaleDateString("en-US", {weekday: "short", month: "short", day: "numeric", timeZone: "UTC"});
  const wl = x => !x ? `<span class="dim">-</span>` : x.held ? `<span class="trk-tag good">held</span>` : x.closed_beyond ? `<span class="trk-tag bad">broke</span>` : `<span class="dim">not reached</span>`;
  const px = v => v == null ? "-" : num(fut(v), 2);
  $("lhTable").innerHTML = `<table class="trk-table"><tr><th>Session</th><th>Regime</th><th>Zero gamma</th><th>Call wall</th><th>Put wall</th><th>Abs gamma</th><th>±1σ band</th><th>Range</th><th>Close</th></tr>${ss.map(s => {
    const p = s.plan, oc = s.outcome, reg = (p.regime || "").toLowerCase(), col = p.regime === "POSITIVE" ? "var(--pos)" : p.regime === "NEGATIVE" ? "var(--neg)" : "var(--zg)";
    return `<tr><td>${esc(day(s.session))}</td><td><span style="color:${col}">${esc(reg || "-")}</span></td><td class="m">${px(p.zg)}</td>
      <td class="m">${px(p.cw)} ${oc ? wl(oc.cw) : ""}</td><td class="m">${px(p.pw)} ${oc ? wl(oc.pw) : ""}</td><td class="m">${px(p.ag)}</td>
      <td class="m">${p.ref && p.em ? `${px(p.ref - p.em)} – ${px(p.ref + p.em)}` : "-"}</td>
      <td class="m">${oc ? `${px(oc.low)} – ${px(oc.high)}` : `<span class="dim">${esc(s.status === "pending" ? "waiting for the close" : s.status)}</span>`}</td>
      <td class="m">${oc ? px(oc.close) : "-"}</td></tr>`; }).join("")}</table>`;
  renderLevelHistoryChart(ss.slice(0, 20).reverse(), fut);
}
// oldest left: a column per session with its ±1σ band, the day's range and close, and dashes at its levels
function renderLevelHistoryChart(ss, fut){
  const svg = $("lhChart"), W = Math.max(280, $("lhWrap").clientWidth || 600), H = 230, pl = 8, pr = 64, pt = 10, pb = 26;
  const done = ss.filter(s => s.outcome);
  const ranges = done.flatMap(s => [s.outcome.low, s.outcome.high]).concat(ss.flatMap(s => [s.plan.ref - s.plan.em, s.plan.ref + s.plan.em]));
  if(!ranges.length){ svg.innerHTML = ""; return; }
  // the y range covers every day's range and band; a level far outside it (a wall 9% away) is left off
  let lo = Math.min(...ranges), hi = Math.max(...ranges); const padY = (hi - lo) * 0.06; lo -= padY; hi += padY;
  const bw = (W - pl - pr) / ss.length, x = i => pl + bw * (i + 0.5), y = v => pt + (hi - v) / (hi - lo) * (H - pt - pb);
  const inside = v => v != null && v >= lo && v <= hi;
  const ticks = [0, 1, 2, 3, 4].map(k => lo + (hi - lo) * k / 4);
  let g = ticks.map(t => `<line x1="${pl}" x2="${W - pr}" y1="${y(t)}" y2="${y(t)}" stroke="rgba(var(--fg-rgb),.06)"/><text x="${W - pr + 6}" y="${y(t) + 4}" fill="var(--ink4)" font-size="10.5" font-family="var(--mono)">${num(fut(t), 0)}</text>`).join("");
  ss.forEach((s, i) => {
    const p = s.plan, oc = s.outcome, cx = x(i), half = Math.max(3, Math.min(14, bw * 0.32));
    const tip = `${day0(s.session)} · ZG ${num(fut(p.zg), 0)} · CW ${num(fut(p.cw), 0)} · PW ${num(fut(p.pw), 0)}` + (oc ? ` · range ${num(fut(oc.low), 0)}-${num(fut(oc.high), 0)} · close ${num(fut(oc.close), 0)}` : "");
    g += `<g><title>${esc(tip)}</title><rect x="${cx - half - 3}" y="${y(p.ref + p.em)}" width="${2 * half + 6}" height="${Math.max(1, y(p.ref - p.em) - y(p.ref + p.em))}" fill="rgba(var(--fg-rgb),.07)"/>`;
    if(oc) g += `<line x1="${cx}" x2="${cx}" y1="${y(oc.high)}" y2="${y(oc.low)}" stroke="var(--ink3)" stroke-width="2"/><line x1="${cx - 4}" x2="${cx + 4}" y1="${y(oc.close)}" y2="${y(oc.close)}" stroke="var(--ink)" stroke-width="2"/>`;
    for(const [k, c] of [["cw", "var(--pos)"], ["pw", "var(--neg)"], ["zg", "var(--zg)"]])
      if(inside(p[k])) g += `<line x1="${cx - half}" x2="${cx + half}" y1="${y(p[k])}" y2="${y(p[k])}" stroke="${c}" stroke-width="2.5"${k === "zg" ? ` stroke-dasharray="3 2"` : ""}/>`;
    g += `<rect x="${cx - bw / 2}" y="${pt}" width="${bw}" height="${H - pt - pb}" fill="transparent"/></g>`;
    if(i % Math.max(1, Math.ceil(ss.length / Math.max(2, Math.floor((W - pl - pr) / 70)))) === 0 || i === ss.length - 1)
      g += `<text x="${Math.max(cx, pl + 16)}" y="${H - 8}" text-anchor="middle" fill="var(--ink4)" font-size="10.5" font-family="var(--mono)">${esc(new Date(s.session + "T12:00:00Z").toLocaleDateString("en-US", {month: "numeric", day: "numeric", timeZone: "UTC"}))}</text>`;
  });
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("width", W); svg.setAttribute("height", H);
  svg.innerHTML = g;
}
// ---------- the level map: where price sits among today's levels, on one price scale (the price ± 3.3 expected moves).
// Above zero gamma is shaded blue, below orange; the grey band is the day's ±1σ; the bars behind are gamma by price.
// A level beyond the scale is pinned to the edge with an arrow, so the scale never lies about distance.
const MAP_SPAN = 3.3;
function niceStep(raw){ const e = 10 ** Math.floor(Math.log10(raw)); return [1, 2, 2.5, 5, 10].map(m => m * e).find(x => x >= raw); }
const PROBE_HINT = "Point at the field for the gamma at any price; tap or click to measure from the price.";
// the tape's words: the distance from the price in points, percent and expected moves (σ), signed (+ = above)
const tapeText = (name, v, ref, d) => `${name ? name + " " : ""}${num(v)} is ${signed(v - ref, 0) || "0"} pts · ${signed((v - ref) / ref * 100, 2) || "0.00"}% · ${d ? (signed((v - ref) / d, 1) || "0.0") + "σ" : "σ unavailable"} from the price ${num(ref)}`;
// the total curve at a price, straight between its two nearest points; off its range: null (never extrapolated)
function fieldAt(curve, at){
  for(let i = 1; i < curve.length; i++){ const [p0, n0] = curve[i - 1], [p1, n1] = curve[i];
    if(at >= Math.min(p0, p1) && at <= Math.max(p0, p1)) return p1 === p0 ? n0 : n0 + (n1 - n0) * (at - p0) / (p1 - p0); }
  return null;
}
function renderLevelMap(w, L, X, ref){
  const box = $("lvMap"), lv = (w.result.session || {}).levels || {}, em = X.expected_move || {};
  const d = em.daily_points_fut ?? em.daily_points, a = em.anchor_fut ?? em.anchor ?? ref, p = v => v && typeof v === "object" ? v.price : v;
  if(ref == null || !d){ box.innerHTML = `<div class="expl">No map in this update: it needs the price and the day's expected move.</div>`; $("lvMapSub").textContent = ""; return; }
  const lines = [];
  for(const [k, v, c] of [["CW", p(L.call_wall), "pos"], ["C1", lv.C1, "pos"], ["Flip", lv.flip, "zg"], ["ZG", p(L.zero_gamma), "zg"], ["Ab1", lv.Ab1, "ag"], ["P1", lv.P1, "neg"], ["PW", p(L.put_wall), "neg"]]){
    if(v == null || !isFinite(v)) continue;
    const same = lines.find(l => Math.abs(l.v - v) < 0.01);          // the same price twice is one line with both names
    same ? same.k += " · " + k : lines.push({k, v, c});
  }
  const W = Math.max(300, Math.round(box.clientWidth) || 560), H = W < 420 ? 290 : 300, top = 14, bot = H - 14, xr = W < 420 ? 112 : 168, xe = W - 2;
  const lo = ref - MAP_SPAN * d, hi = ref + MAP_SPAN * d, y = v => bot - (v - lo) / (hi - lo) * (bot - top);
  const zg = p(L.zero_gamma), yz = zg == null ? null : Math.max(top, Math.min(bot, y(zg)));
  let g = yz == null ? "" : `<rect x="${xr}" y="${top}" width="${xe - xr}" height="${yz - top}" class="m-posz"/><rect x="${xr}" y="${yz}" width="${xe - xr}" height="${bot - yz}" class="m-negz"/>`;
  g += `<rect x="${xr}" y="${y(a + d)}" width="${xe - xr}" height="${y(a - d) - y(a + d)}" class="m-band"/>`;
  // The field (Meridian). On the meridian, the strike tone: the model's net gamma at each strike bin, deepest where the
  // walls are. Across it, the total curve: the model's net gamma if the price were at each level (result.profile, index
  // prices times the frozen basis the other levels use), right of the axis positive and left negative, so it crosses
  // the axis at zero gamma. The price is the bead on the meridian.
  const xm = Math.round(xr + (xe - xr) / 2), half = (xe - xr) * 0.42;
  const pr = X.profile, base = pr && (pr.base_fut ?? pr.base), step = pr && (pr.width_fut ?? pr.width);
  const bins = pr && pr.values && base != null && step && pr.max_abs ? pr.values.map((v, i) => [base + i * step, v / 99 * pr.max_abs, v]) : [];
  for(const [pv, , v] of bins){ if(!v || pv - step / 2 > hi || pv + step / 2 < lo) continue;
    const y0 = Math.max(top, y(pv + step / 2)), y1 = Math.min(bot, y(pv - step / 2));
    g += `<rect x="${xm - 7}" y="${y0.toFixed(1)}" width="14" height="${Math.max(0.5, y1 - y0).toFixed(1)}" fill-opacity="${(0.15 + 0.85 * Math.abs(v) / 99).toFixed(2)}" class="m-tone ${v < 0 ? "neg" : "pos"}"/>`; }
  const f = w.result.mapped && w.result.mapped.mapping ? w.result.mapped.mapping.factor : 1;
  const curve = (w.result.profile || []).map(q => [q.price * f, q.net]).filter(([pp, n]) => pp >= lo && pp <= hi && isFinite(n));
  const cmax = Math.max(0, ...curve.map(c => Math.abs(c[1])));
  g += `<line x1="${xm}" x2="${xm}" y1="${top}" y2="${bot}" class="m-axis"/><text x="${xm - 5}" y="${top - 3}" text-anchor="end" class="m-t">− gamma</text><text x="${xm + 5}" y="${top - 3}" class="m-t">+ gamma</text>`;
  if(curve.length > 1 && cmax > 0) g += `<path d="${curve.map(([pp, n], i) => `${i ? "L" : "M"}${(xm + n / cmax * half).toFixed(1)} ${y(pp).toFixed(1)}`).join("")}" class="m-curve"/>`;
  const tk = niceStep(MAP_SPAN * d / 3), ticks = [];
  for(let t = Math.ceil(lo / tk) * tk; t <= hi; t += tk){ g += `<line x1="${xr}" x2="${xe}" y1="${y(t)}" y2="${y(t)}" class="m-grid"/>`; ticks.push(t); }
  const pins = lines.map(l => ({...l, yy: Math.max(top + 6, Math.min(bot - 6, y(l.v))), off: l.v > hi ? "↑ " : l.v < lo ? "↓ " : ""}));
  pins.push({k: market, v: ref, px: true, yy: y(ref)});
  pins.sort((u, v) => u.yy - v.yy);
  pins.forEach((l, i) => { l.ly = i ? Math.max(l.yy, pins[i - 1].ly + 28) : l.yy; });   // labels never overlap
  const shift = Math.max(0, pins.at(-1).ly - (bot - 4)); pins.forEach(l => { l.ly -= shift; });
  for(const l of pins){
    if(l.px){ g += `<line x1="${xr}" x2="${xe}" y1="${l.yy}" y2="${l.yy}" class="m-px"/><circle cx="${xm}" cy="${l.yy}" r="6" class="m-bead"/><path d="M${xr - 10} ${l.ly} L${xr} ${l.yy}" class="m-lead px"/>
      <rect x="0" y="${l.ly - 11}" width="${xr - 10}" height="22" rx="5" class="m-pill"/><text x="8" y="${l.ly + 4}" class="m-pillt">${W < 420 ? "" : esc(market) + (w.result.mapped ? " eq. " : " ")}${num(ref)}</text>`; continue; }
    g += `<line x1="${xr}" x2="${xe}" y1="${l.yy}" y2="${l.yy}" class="m-lv ${l.c}${l.off ? " off" : ""}${l.k.startsWith("ZG") || l.k.startsWith("Flip") ? " dash" : ""}"/>
      <path d="M${xr - 10} ${l.ly} L${xr} ${l.yy}" class="m-lead ${l.c}"/>
      <text x="0" y="${l.ly - 2}" class="m-k ${l.c}">${l.off}${esc(l.k)} <tspan class="m-v">${num(l.v)}</tspan></text>
      <text x="0" y="${l.ly + 11}" class="m-d">${signed(l.v - ref, 0)} pts · ${signed((l.v - ref) / d, 1)}σ</text>`;
  }
  for(const t of ticks) g += `<text x="${xe - 4}" y="${y(t) - 3}" text-anchor="end" class="m-t">${num(t, 0)}</text>`;
  if(yz != null){ g += `<text x="${xr + 6}" y="${top + 12}" class="m-z pos">POSITIVE GAMMA</text><text x="${xr + 6}" y="${bot - 5}" class="m-z neg">NEGATIVE GAMMA</text>`; }
  // the same picture in words, for screen readers
  const here = fieldAt(curve, ref), deep = bins.filter(b => b[0] >= lo && b[0] <= hi).sort((u, v) => Math.abs(v[2]) - Math.abs(u[2]))[0];
  const words = `${market} ${num(ref)}. ${here == null ? "Total modeled gamma at the price: unavailable." : `Total modeled gamma at the price: ${money(here)} per 1% move.`} `
    + `${zg == null ? "The model found no zero-gamma crossing in its range." : `It crosses zero at ${num(zg)}.`} `
    + `${deep ? `Deepest strike tone: ${num(deep[0], 0)}, ${deep[1] < 0 ? "negative" : "positive"}.` : ""} `
    + lines.map(l => `${l.k} ${num(l.v)}, ${signed(l.v - ref, 0)} pts.`).join(" ");
  g += `<line x1="${xr}" x2="${xe}" y1="0" y2="0" class="m-probe-ln" visibility="hidden"/><g class="m-tape" visibility="hidden"></g>`;
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(market)} price ${num(ref)} in the gamma field among today's levels">${g}</svg>
    <p class="vh">${esc(words)}</p>
    <div class="m-probe">${PROBE_HINT}</div><div class="m-tapeout" aria-live="polite"></div>
    <div class="legend"><span><i class="sw m-sw-band"></i>Day ±1σ ${num(a - d, 0)} – ${num(a + d, 0)}</span><span><i class="sw m-sw-tone"></i>Strike gamma</span><span><i class="sw m-sw-curve ln"></i>Total if price were there</span><span>↑ ↓ beyond ±${MAP_SPAN}σ</span></div>`;
  // the probe: point or tap anywhere on the field for the exact numbers at that price
  const svg = box.querySelector && box.querySelector("svg"), out = svg && box.querySelector(".m-probe"), ln = svg && svg.querySelector(".m-probe-ln");
  // the tape (from Signal): a tap or click measures from the price to a level (it snaps to one within 10 px) or to that
  // price, and stays drawn until the next tap
  const tape = svg && svg.querySelector(".m-tape"), xt = xm + 24;
  const at = yy => hi - (yy - top) / (bot - top) * (hi - lo);
  if(svg) svg.onpointermove = e => {
    const r = svg.getBoundingClientRect(), yy = (e.clientY - r.top) * H / r.height;
    if(yy < top || yy > bot){ ln.setAttribute("visibility", "hidden"); return; }
    const v = at(yy), b = bins.find(q => Math.abs(q[0] - v) <= step / 2), tot = fieldAt(curve, v);
    ln.setAttribute("y1", yy); ln.setAttribute("y2", yy); ln.setAttribute("visibility", "visible");
    out.textContent = `${num(v, 0)} · ${signed(v - ref, 0)} pts · strike gamma ${!b ? "none saved here" : b[2] ? "about " + money(b[1]) : "under 1% of the largest"} · total if price were here ${tot == null ? "unavailable" : money(tot)} (per 1% move)`;
  };
  if(svg) svg.onpointerdown = e => {
    const r = svg.getBoundingClientRect(), yy = (e.clientY - r.top) * H / r.height;
    if(yy < top || yy > bot) return;
    const near = lines.filter(l => l.v >= lo && l.v <= hi && Math.abs(y(l.v) - yy) <= 10).sort((u, v) => Math.abs(y(u.v) - yy) - Math.abs(y(v.v) - yy))[0];
    const v = near ? near.v : at(yy), y0 = y(ref), y1 = y(v);
    tape.innerHTML = `<line x1="${xt}" x2="${xt}" y1="${y0}" y2="${y1}"/><line x1="${xt - 5}" x2="${xt + 5}" y1="${y0}" y2="${y0}"/><line x1="${xt - 5}" x2="${xt + 5}" y1="${y1}" y2="${y1}"/>`;
    tape.setAttribute("visibility", "visible");
    box.querySelector(".m-tapeout").textContent = "Tape: " + tapeText(near ? near.k : "", v, ref, d);
  };
  $("lvMapSub").textContent = `${w.result.mapped ? market + " equiv. of " + w.source : w.source + " prices"} · ±${MAP_SPAN}σ around the price`;
}
// the two folded sections remember whether this viewer left them open; a chart drawn while folded is redrawn at its real width
const foldAuto = new Set();                                 // a fold opened by the page, not the viewer, is not remembered
for(const id of ["lvMore", "lvHist"]){
  const el = $(id); el.open = store.get("gex." + id, "0") === "1";
  el.addEventListener("toggle", () => { if(!foldAuto.delete(id)) store.set("gex." + id, el.open ? "1" : "0"); if(id === "lvHist" && el.open && data) loadLevelHistory(); });
}
const openFold = id => { if($(id).open) return; foldAuto.add(id); $(id).open = true; };     // toggle fires later, once
// ---------- Levels: density (Glance / Work / Study) and the order of the day
// Both are set once, at load, before anything is drawn, so nothing jumps. The phase comes from the market calendar the
// last visit saved (data.calendar, from marketcal); a first visit keeps the session order. The nav never changes.
const DENSITY = ["glance", "work", "study"];
function setDensity(d, save = true){
  if(!DENSITY.includes(d)) d = "work";
  if(save) store.set("gex.density", d);
  document.body.classList.remove(...DENSITY.map(x => "dens-" + x)); document.body.classList.add("dens-" + d);
  document.querySelectorAll("#density button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.d === d)));
  if(d === "study") ["lvMore", "lvHist"].forEach(openFold);
}
document.querySelectorAll("#density button").forEach(b => b.onclick = () => setDensity(b.dataset.d));
setDensity(store.get("gex.density", "work"), false);
const LV_LEAD = {"before the open": ["lvHead", "planRow"], "after the close": ["lvHead", "lvHist"], "no cash session today": ["lvHead", "lvHist"]};
const LV_PHASE = {"before the open": "Before the open: the plan leads", "cash session": "Cash session",
  "after the close": "After the close: how the levels held leads", "no cash session today": "No cash session today: how the levels held leads"};
let phaseBase = "";
function orderLevels(phase){
  const v = $("levelsView"), lead = LV_LEAD[phase] || [];
  [...lead].reverse().forEach(id => v.prepend($(id)));
  if(lead.includes("lvHist") && !document.body.classList.contains("dens-glance")) openFold("lvHist");
  $("phaseLab").textContent = phaseBase = LV_PHASE[phase] || "";
}
// today's session (or, with none today, the next one): an early close and the roll week, in words, from marketcal
function calNotes(d, cal){
  const sp = sessionPhase(d, cal), s = sp.session || sp.next, out = [];
  if(!s) return out;
  const t = new Date(s.close).toLocaleTimeString("en-US", {...ET, hour: "numeric", minute: "2-digit"});
  if(s.early) out.push(`${sp.session ? "Early close today" : "Next session closes early"}, ${t} ET`);
  if(s.roll_week) out.push("Futures roll week: levels use the frozen 9:30 basis");
  return out;
}
const cal0 = (() => { try { return JSON.parse(store.get("gex.cal", "null")); } catch(e){ return null; } })();
orderLevels(cal0 ? sessionPhase(new Date(), cal0).phase : null);        // a first visit: the usual order and no label
const day0 = s => new Date(s + "T12:00:00Z").toLocaleDateString("en-US", {weekday: "short", month: "short", day: "numeric", timeZone: "UTC"});
// the one plan zone price is in. The flip decides the side first: when C1 sits below the flip (or P1 above it) the
// zones would overlap, and price can only be in one ("above C1" also needs price above the flip, "below P1" below it)
function planHere(ref, C1, P1, F){
  if(ref == null) return null;
  if(F == null) return C1 != null && ref >= C1 ? "above" : P1 != null && ref < P1 ? "below" : null;
  if(ref >= F) return C1 != null && C1 > F && ref < C1 ? "upper" : C1 != null ? "above" : null;
  return P1 != null && P1 < F && ref >= P1 ? "lower" : P1 != null ? "below" : null;
}
// the outer zones' edges: C1 and P1, or the flip when C1 sits below it (P1 above it), so no two zones overlap
const planEdges = (C1, P1, F) => [F == null || C1 > F ? C1 : F, F == null || P1 < F ? P1 : F];
function renderPlan(w){
  const S = w && w.result && w.result.session;
  if(!S || !S.levels){ $("planCard").innerHTML = `<div class="eyebrow">Today's plan</div><div class="expl">The plan appears with the next refresh.</div>`; $("chgFeed").innerHTML = ""; return; }
  const lv = S.levels, s = w.result.summary, X = (w.result.mapped || s).extras || {}, em = X.expected_move || {};
  const ref = (w.result.mapped || {}).futures_equiv_of_ref ?? s.ref_price, k = market === "ES" ? "es" : "nq";
  const p = x => x == null ? "-" : num(x, 0), d = (em.daily_points_fut ?? em.daily_points), a = em.anchor_fut ?? em.anchor;
  const now = new Date(), phase = sessionPhase(now, data && data.calendar).phase;
  // where price sits, and what each side of it means
  const C1 = lv.C1, P1 = lv.P1, F = lv.flip ?? lv.ZG;
  // levels are numbered by strength, not price: only name a "next" level that lies beyond C1 / P1
  const C2 = lv.C2 != null && lv.C2 > C1 ? lv.C2 : null, P2 = lv.P2 != null && lv.P2 < P1 ? lv.P2 : null;
  const here = planHere(ref, C1, P1, F);
  // the zones use the first expiry's flip; the Regime row counts every expiry, so the zones name their own scope
  const fl = lv.flip != null ? "the flip" : "zero gamma", g0 = lv.flip != null ? "0DTE " : "";
  const [hi, lo] = planEdges(C1, P1, F), top = hi === C1 ? `C1 ${p(C1)}` : `${fl} ${p(F)}`, bot = lo === P1 ? `P1 ${p(P1)}` : `${fl} ${p(F)}`;
  const rows = [
    C1 != null && [`Above ${top}`, "positive-gamma extension: rallies tend to slow" + (C2 != null ? `; next call level ${p(C2)}` : ""), here === "above"],
    C1 != null && F != null && C1 > F && [`Between ${fl} ${p(F)} and C1 ${p(C1)}`, `positive ${g0}gamma: expect two-way trade and fades back toward the middle`, here === "upper"],
    P1 != null && F != null && P1 < F && [`Between P1 ${p(P1)} and ${fl} ${p(F)}`, `negative ${g0}gamma: moves can extend` + (P2 != null ? `; a break of P1 opens ${p(P2)}` : ""), here === "lower"],
    P1 != null && [`Below ${bot}`, "hedging adds to selling" + (P2 != null ? `; next put level ${p(P2)}` : ""), here === "below"],
  ].filter(Boolean);
  const day = now.toLocaleDateString("en-US", {...ET, weekday: "short", month: "short", day: "numeric"});
  const usd = ((news && news.events) || []).filter(e => e.country === "USD" && (e.impact === "High" || e.impact === "Medium")
    && new Date(e.time).toLocaleDateString("en-US", ET) === now.toLocaleDateString("en-US", ET) && Date.parse(e.time) > Date.now() - 3600e3);
  const earn = planEarnings(k);
  const R = {POSITIVE: ["positive", "var(--pos)"], NEGATIVE: ["negative", "var(--neg)"]}[lv.regime] || ["balanced", "var(--zg)"];
  $("planCard").innerHTML = `<div class="head"><h2>Today's plan</h2><span class="sub">${esc(day)} · ${esc(market)} · ${esc(phase)}</span></div>
    <div class="plan-kv"><span>Regime</span><b style="color:${R[1]}">${R[0]} gamma</b><span>Price${refAt(s.ref_time)}</span><b class="m">${num(ref, 2)}</b>
      <span>${em.anchor_label ? "Day ±1σ from " + esc(em.anchor_label) : "Day range ±1σ"}</span><b class="m">${d && a ? p(a - d) + " – " + p(a + d) : "-"}</b><span>Ab1 (magnet)</span><b class="m">${lv.Ab1 != null ? p(lv.Ab1) : s.backup ? "not in the backup" : "-"}</b></div>
    <div class="plan-sc">${rows.map(([when, what, here]) => `<div class="${here ? "here" : ""}"><b>${esc(when)}</b><span>${esc(what)}</span>${here ? '<em>price is here</em>' : ""}</div>`).join("")}</div>
    ${usd.length ? `<div class="plan-ev"><span class="eyebrow">Data today (ET)</span>${usd.map(e => `<span class="${e.impact === "High" ? "hi" : ""}">${esc(new Date(e.time).toLocaleTimeString("en-US", {...ET, hour: "numeric", minute: "2-digit"}))} ${esc(e.title)}</span>`).join("")}</div>` : ""}
    ${earn.length ? `<div class="plan-ev"><span class="eyebrow">Earnings ahead</span>${earn.map(r => `<span>${esc(r.symbol)} ${esc(earnTxt(r.earnings))}: ±${num(r.earn_move.pct, 1)}% ≈ ±${num(Math.abs(r["earn_pts_" + k]), 0)} ${esc(market)} pts</span>`).join("")}</div>` : ""}
    ${P1 != null && P1 > ref ? `<div class="expl">P1 ${p(P1)} is above the price: the first expiry's most negative-gamma strike is now above it.</div>` : ""}${C1 != null && C1 < ref ? `<div class="expl">C1 ${p(C1)} is below the price: the first expiry's most positive-gamma strike is now below it.</div>` : ""}
    <div class="expl">Levels and zones from the first expiry, the same as the indicator's C / P / Ab; the regime counts every expiry. A plan, not a prediction: news can override any level.</div>`;
  // the change feed
  const nm = {C1: "C1", C2: "C2", P1: "P1", P2: "P2", Ab1: "Ab1", flip: "0DTE flip", ZG: "Zero gamma", CW: "Call wall", PW: "Put wall", regime: "Regime"};
  const ch = S.changes || [];
  const at = x => new Date(x).toLocaleTimeString("en-US", {...ET, hour: "numeric", minute: "2-digit"});
  $("chgFeed").innerHTML = (S.open ? `<div class="chg-open"><span class="eyebrow">At the 9:30 open</span>${["C1", "P1", "Ab1", "flip"].filter(x => S.open[x] != null).map(x => `<span>${nm[x]} <b class="m">${p(S.open[x])}</b></span>`).join("")}</div>` : "")
    + (ch.length ? ch.map(c => { const reg = c.what === "regime", dv = reg ? 0 : c.to - c.frm;
        return `<div class="chg-row"><span class="m t">${esc(at(c.t))}</span><b>${esc(nm[c.what] || c.what)}</b>
          <span class="m">${reg ? esc(String(c.frm).toLowerCase()) + " → " + esc(String(c.to).toLowerCase()) : p(c.frm) + " → " + p(c.to)}</span>
          ${reg ? "" : `<span class="m ${dv > 0 ? "good" : "bad"}">${signed(dv, 0)}</span>`}</div>`; }).join("")
      : `<div class="expl">No level has moved since the 6 pm ET session start.</div>`);
  $("chgSub").textContent = ch.length ? `${ch.length} change${ch.length === 1 ? "" : "s"} since 6 pm ET` : "";
}

// ---------- glossary: every term the site and the indicator use, searchable, by topic or A to Z
let glTopic = "All", glFocus = "";
const glKey = t => t.replace(/^[^A-Za-z0-9]+/, "").toUpperCase();
function renderGlossary(){
  const G = LIB.glossary.slice().sort((a, b) => glKey(a[0]).localeCompare(glKey(b[0])));
  const topics = ["All", ...new Set(LIB.glossary.map(g => g[3]))];
  $("glTopics").innerHTML = topics.map(k => `<button role="tab" aria-selected="${glTopic === k}" data-k="${esc(k)}">${esc(k)}</button>`).join("");
  [...$("glTopics").children].forEach(b => b.onclick = () => { glTopic = b.dataset.k; renderGlossary(); });
  const q = $("glSearch").value.trim().toLowerCase();
  const rows = G.filter(g => (glTopic === "All" || g[3] === glTopic) && (!q || (g[0] + " " + g[1] + " " + g[4]).toLowerCase().includes(q)));
  const letters = [...new Set(rows.map(g => glKey(g[0])[0]))];
  $("glAz").innerHTML = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("").map(L => letters.includes(L) ? `<button data-l="${L}">${L}</button>` : `<span>${L}</span>`).join("")
    + (letters.some(L => /[0-9]/.test(L)) ? `<button data-l="0">#</button>` : "");
  [...$("glAz").querySelectorAll("button")].forEach(b => b.onclick = () => {
    const el = document.querySelector(`#glList [data-letter="${b.dataset.l === "0" ? letters.find(L => /[0-9]/.test(L)) : b.dataset.l}"]`);
    el && el.scrollIntoView({behavior: "auto", block: "start"}); });
  let last = "";
  $("glList").innerHTML = rows.map(([t, d, lesson, topic, where]) => {
    const L = glKey(t)[0], head = L !== last ? `<div class="gl-letter" data-letter="${L}">${/[0-9]/.test(L) ? "#" : L}</div>` : "";
    last = L;
    return head + `<div class="gl-row${t === glFocus ? " focus" : ""}" id="gl-${esc(glKey(t).replace(/[^A-Z0-9]+/g, "-"))}">
      <b>${esc(t)}</b><div><span>${esc(d)}</span><em>${esc(topic)} · seen in ${esc(where)}</em></div>
      ${lesson ? `<button class="linkbtn" data-l="${esc(lesson)}">Lesson →</button>` : "<i></i>"}</div>`;
  }).join("") || `<div class="expl">No term matches "${esc(q)}".</div>`;
  [...$("glList").querySelectorAll("[data-l]")].forEach(b => b.onclick = () => openLesson(b.dataset.l));
  $("glSub").textContent = `${rows.length} of ${G.length} terms`;
  if(glFocus){ const el = $("gl-" + glKey(glFocus).replace(/[^A-Z0-9]+/g, "-")); glFocus = ""; el && setTimeout(() => el.scrollIntoView({behavior: "auto", block: "center"}), 30); }
}
// open the glossary on one term (from the Explain drawer)
function openGlossary(term){ glTopic = "All"; $("glSearch").value = ""; glFocus = term; closeExplain(); if(page === "glossary") renderGlossary(); else setPage("glossary"); }
$("glSearch").addEventListener("input", renderGlossary);
// glossary terms named in a piece of help text (the part before " (" or " /", whole words), for the Explain drawer
function glTermsIn(text){
  const low = " " + text.toLowerCase().replace(/<[^>]+>/g, " ") + " ";
  return LIB.glossary.filter(([t]) => { const n = t.split(/ \(| \//)[0].toLowerCase(); return n.length > 2 && new RegExp("[^a-z0-9]" + n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "[^a-z0-9]").test(low); }).map(g => g[0]).slice(0, 10);
}

// installable app: the service worker (network first) lets phones add GEX PRO to the home screen
if("serviceWorker" in navigator && (location.protocol === "https:" || /^(127\.0\.0\.1|localhost)$/.test(location.hostname)))
  navigator.serviceWorker.register("sw.js").catch(() => {});

setPage(page);
load();
loadNews();
loadPosts();
loadQuotes();
// coming back to the tab (or waking the laptop) pulls everything at once instead of waiting for the timers
let lastPull = Date.now();
function refreshAll(){
  lastPull = Date.now();
  load(); loadQuotes(); loadNews(); loadPosts();
  if(page === "screener") loadScreener();
  if(page === "heatmap") loadHeatmap();
  if(page === "briefings") loadBriefings();
  if(page === "track") loadTrack();
}
document.addEventListener("visibilitychange", () => { if(!document.hidden && Date.now() - lastPull > 30000) refreshAll(); });
setInterval(loadQuotes, STATIC ? 5 * 60 * 1000 : 60 * 1000);   // the hosted copy refreshes with each site build
setInterval(load, STATIC ? 60000 : 20000);
{ const draw = render; render = function(){ draw(); showChanges(); settle(); }; }      // every render: what changed, then the heights
setInterval(loadPosts, 2 * 60 * 1000);                     // the service itself re-fetches at most every 5 min
setInterval(loadNews, 10 * 60 * 1000);                      // the service itself re-fetches at most every 30 min
loadSources(); setInterval(loadSources, 5 * 60 * 1000);   // keeps the red dot on Data health current
setInterval(() => { if(page === "news") renderNews(); }, 60000);   // keep countdowns current
setInterval(() => { if(page === "briefings") loadBriefings(); }, STATIC ? 5 * 60 * 1000 : 60000);
setInterval(() => { if(page === "indicator") loadIndicator(); }, STATIC ? 5 * 60 * 1000 : 15000);   // pick up code edits
window.addEventListener("resize", () => { if(data) render(); if(page === "track") renderTrack(); });
setInterval(() => { if(page === "track") loadTrack(); }, 5 * 60 * 1000);
setInterval(() => { if(page === "screener") loadScreener(); }, STATIC ? 5 * 60 * 1000 : 2 * 60 * 1000);
setInterval(() => { if(page === "heatmap") loadHeatmap(); }, STATIC ? 5 * 60 * 1000 : 60 * 1000);
