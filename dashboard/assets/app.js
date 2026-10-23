const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const num = (x, d=2) => x == null || !isFinite(x) ? "-" : Number(x).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
const money = x => x == null || !isFinite(x) ? "-" : (x<0?"-":"+") + "$" + (Math.abs(x)>=1e9 ? num(Math.abs(x)/1e9,2)+"B" : num(Math.abs(x)/1e6,0)+"M");
const signed = (x, d=2) => x == null || !isFinite(x) ? "" : (x>=0?"+":"-") + num(Math.abs(x), d);
const store = { get(k, d){ try { return localStorage.getItem(k) ?? d; } catch(e){ return d; } }, set(k, v){ try { localStorage.setItem(k, v); } catch(e){} } };

// Static mode: the hosted copy (python -m gexsys build-site) reads files that a scheduled job rewrites,
// instead of the local service's /api endpoints.
const STATIC = !!window.GEX_STATIC;
const API = STATIC ? {all: "data/all.json", news: "data/news.json", posts: "data/posts.json", indicator: "data/indicator.json", briefings: "data/briefings.json", timeline: "data/timeline.json", track: "data/trackrecord.json"}
                   : {all: "/api/all", news: "/api/news", posts: "/api/posts", indicator: "/api/indicator", briefings: "/api/briefings", timeline: "/api/timeline", track: "/api/trackrecord"};
const pineUrl = m => STATIC ? `data/pine-published${m ? "-" + m : ""}.txt`
                            : `/api/pine/all?which=published${m ? "&market=" + encodeURIComponent(m) : ""}`;
const OFFLINE = STATIC ? "Can't load the latest data file. Check your connection; retrying."
                       : "Can't reach the GEX PRO service. Is START.bat still running? Retrying every 20 seconds.";

if (location.protocol === "file:" && !STATIC) {
  document.body.innerHTML = `<div class="wrap"><div class="banner bad" style="margin-top:40px;font-size:15px;line-height:1.7">
  This page only works while the GEX PRO service is running.<br>1. Double-click <b>START.bat</b> in your Options Indicator folder.<br>
  2. Your browser opens <b>http://127.0.0.1:8765</b> automatically.</div></div>`;
  throw new Error("opened as file");
}

let data = null, market = store.get("gex.market", "NQ");
// One view at a time ("show only"). The old on/off toggles could hide the key levels by accident.
try { localStorage.removeItem("gex.groups"); } catch(e) {}
let view = store.get("gex.view", "all");
let showTable = false;

const GROUPS = [["key","Key levels"],["odte","0DTE"],["flow","Volume & OI"],["mp","Max pain"],["range","Expected move"]];
const VIEWS = [["all","All"], ...GROUPS];
const KIND_COLOR = {ag:"var(--ag)", zg:"var(--zg)", call:"var(--pos)", put:"var(--neg)", vol:"var(--vol)", oi:"var(--oi)", mp:"var(--mp)", em:"var(--em)"};

function toast(msg){ const t=$("toast"); t.textContent=msg; t.classList.add("show"); clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("show"),3800); }
async function copyFrom(url, what){
  const text = (await (await fetch(url, {cache:"no-store"})).text()).trim();
  if(!text){ toast("Nothing to copy yet - the first scheduled update hasn't happened."); return; }
  try{ await navigator.clipboard.writeText(text); toast(`Copied ${what}. In TradingView: indicator settings > Levels payload > Ctrl+A, Ctrl+V > OK.`); }
  catch(e){ window.prompt("Copy this (Ctrl+C):", text); }
}
$("copyAll").onclick = () => copyFrom(pineUrl(""), "the scheduled update for NQ and ES");
$("copyMarket").onclick = () => copyFrom(pineUrl(market), `the scheduled update for ${market}`);
$("tableToggle").onclick = () => { showTable = !showTable; render(); };

// ---------- pages: Levels | News
let page = "levels";                                   // always open on Levels
try { localStorage.removeItem("gex.page"); } catch(e) {}
let impactF = store.get("gex.impact", "med");       // high | med | all
let curF = store.get("gex.cur", "USD");             // USD | all
let news = null;
const VIEW_IDS = ["levels", "gamma", "vol", "timeline", "bias", "track", "strategies", "briefings", "news", "indicator", "library"];
function setPage(p){
  if(!VIEW_IDS.includes(p)) p = "levels";
  page = p;
  document.querySelectorAll("#pages button[data-p]").forEach(b => b.setAttribute("aria-selected", String(b.dataset.p === p)));
  VIEW_IDS.forEach(v => { $(v + "View").hidden = v !== p; });
  $("pageTitle").textContent = (PAGES.find(x => x[0] === p) || ["", "Levels"])[1];
  $("tabs").style.display = NO_MARKET_PAGES.includes(p) ? "none" : "";
  $("status").style.display = NO_MARKET_PAGES.includes(p) ? "none" : "";
  $("explain").classList.contains("open") && openExplain(PAGE_HELP[p] || "regime");
  if(p === "briefings") loadBriefings();
  if(p === "news") renderNews();
  if(p === "indicator") loadIndicator();
  if(p === "timeline") loadTimeline();
  if(p === "library") renderLibrary();
  if(p === "track" || p === "strategies") loadTrack();
  if(!NO_MARKET_PAGES.includes(p) && data) render();
  $("explainTab").title = "Explain this page (X)";
}
document.querySelectorAll("#pages button[data-p]").forEach(b => b.onclick = () => setPage(b.dataset.p));
async function loadNews(){
  try { news = await (await fetch(API.news, {cache:"no-store"})).json(); }
  catch(e) { news = news || {events: [], error: OFFLINE}; }
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
  try { posts = await (await fetch(API.posts, {cache:"no-store"})).json(); }
  catch(e) { posts = posts || {posts: [], error: OFFLINE}; }
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
      <div class="meta"><b>${when(p.time)}</b>${kind}${counts}${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">open</a>` : ""}</div>
      ${p.text ? `<div class="txt" onclick="this.classList.toggle('open')" title="Click to expand">${esc(p.text)}</div>` : `<div class="txt" style="color:var(--ink3)">${media ? (media.type === "video" ? "Video post" : "Image post") : "Post without text"}</div>`}
      ${media && media.preview ? `<img loading="lazy" src="${esc(media.preview)}" alt="${media.type === "video" ? "video preview" : "image"} from the post" referrerpolicy="no-referrer">` : ""}
      ${p.link && p.link.url ? `<a href="${esc(p.link.url)}" target="_blank" rel="noopener" style="font-size:12.5px">${esc(p.link.title || p.link.url)}</a>` : ""}
      ${hot ? `<div class="tags">${p.tone ? `<span class="tone ${p.tone}" title="Keyword guess at what this post means for stocks, not a forecast">${p.tone}</span>` : ""}${p.market_words.map(w => `<span class="mw">${esc(w)}</span>`).join("")}</div>` : ""}
    </div>`; }).join("") || `<div class="expl">${postF === "market" ? "No recent posts mention market topics." : "No posts available."}</div>`;
  $("postsFoot").innerHTML = `Source: ${esc(posts.source || "-")}${posts.fetched_at ? `, updated ${ago(posts.fetched_at)}` : ""}; checked every 5 min. Yellow tags flag market topics (tariffs, the Fed, China, oil...); Bullish / Bearish is a keyword guess at the post's lean for stocks, shown only when it is clear. Posts can move futures quickly, and nothing here predicts how.${posts.error ? ` <span style="color:var(--warn)">${esc(posts.error)}</span>` : ""}`;
}

// ---------- Briefings page: NY AM and Asia session write-ups
let brief = null, briefPick = "";                          // "" = the newest briefing
async function loadBriefings(){
  try { brief = await (await fetch(API.briefings, {cache:"no-store"})).json(); }
  catch(e){ $("briefTitle").textContent = "Briefings unavailable"; $("briefLead").textContent = OFFLINE; return; }
  renderBriefings();
}
const BKIND = {nyam: "NY AM", asia: "Asia"};
function renderBriefings(){
  if(!brief) return;
  const latest = Object.values(brief.latest || {}).filter(Boolean).sort((a, b) => b.slot.localeCompare(a.slot));
  const b = briefPick ? (brief.by_id[briefPick] || brief.latest[briefPick]) : latest[0];
  const kindNow = b ? b.kind : null;
  $("briefKind").innerHTML = ["nyam", "asia"].map(k => `<button role="tab" aria-selected="${kindNow === k && !String(briefPick).includes("-")}" data-k="${k}"${brief.latest[k] ? "" : " disabled"}>${BKIND[k]}</button>`).join("");
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
  $("briefHead").style.setProperty("--accent", b.kind === "asia" ? "var(--oi)" : "var(--pos)");
  $("briefKicker").textContent = b.kind === "asia" ? "Night session · Asia open" : "Before the US open";
  $("briefTitle").textContent = `${b.title} · ${new Date(b.session + "T12:00:00Z").toLocaleDateString("en-US", {weekday:"long", month:"short", day:"numeric", timeZone:"UTC"})} session`;
  $("briefMeta").innerHTML = `<span class="chip">Written <b>${new Date(b.generated_at).toLocaleString("en-US", {...ET, weekday:"short", hour:"numeric", minute:"2-digit"})} ET</b></span>`
    + (b.late ? `<span class="chip" title="The app wasn't running at the scheduled time, so this was written when it started"><i class="dot warn"></i>Written late</span>` : "") + nxt;
  $("briefLead").textContent = b.headline;
  const col = r => r === "POSITIVE" ? "var(--pos)" : r === "NEGATIVE" ? "var(--neg)" : "var(--zg)";
  $("briefMarkets").innerHTML = (b.markets || []).map(m => `<section class="card bm accent" style="--accent:${col(m.regime)}">
    <div class="head" style="margin-bottom:0"><h2>${esc(m.market)}</h2><span class="chip" style="color:${col(m.regime)}">${esc((m.regime || "").toLowerCase())} gamma</span></div>
    <div class="hl">${esc(m.headline)}</div>
    <div class="blv">${(m.levels || []).map(l => `<div><span>${esc(l.name)}</span><b>${num(l.price)} <span style="color:var(--ink3);font-weight:500">${signed(l.price - m.price, 1)}</span></b></div>`).join("")}</div>
    ${m.range ? `<div class="bsec"><div class="eyebrow">Expected range</div><p>${esc(m.range.text)}</p></div>` : ""}
    ${m.odte ? `<div class="bsec"><div class="eyebrow">0DTE levels</div><p>${esc(m.odte)}</p></div>` : ""}
    ${m.bias ? `<div class="bsec"><div class="eyebrow">Bias</div><p>${esc(m.bias)}</p></div>` : ""}
    <div class="bsec"><div class="eyebrow">Game plan</div><p>${esc(m.plan)}</p></div>
    ${(m.changes || []).length ? `<div class="bsec"><div class="eyebrow">What changed</div>${m.changes.map(c => `<p>${esc(c)}</p>`).join("")}</div>` : ""}
    ${m.data ? `<div class="expl">${esc(m.data)}</div>` : ""}</section>`).join("");
  $("briefCal").innerHTML = (b.calendar || []).map(c => `<div class="head" style="margin:${c === b.calendar[0] ? 0 : 18}px 0 6px"><h2>${esc(c.title)}</h2></div>`
    + ((c.items || []).map(e => `<div class="bev"><span class="tm">${esc(e.day)} ${esc(e.clock)}</span><span class="imp ${esc(e.impact)}">${esc(e.impact === "Medium" ? "Med" : e.impact)}</span><span>${esc(e.title)} <span style="color:var(--ink3);font:12px var(--mono)">${esc(e.country)}</span></span><span class="fp">${esc(e.detail || "")}</span></div>`).join("")
       || `<div class="expl" style="margin-top:0">No high- or medium-impact events.</div>`)).join("");
  $("briefPostsTitle").textContent = (b.posts || {}).title || "Market-moving posts";
  $("briefPosts").innerHTML = ((b.posts || {}).items || []).map(x => `<div class="bpost"><div class="meta"><b style="color:var(--ink2)">${esc(x.clock)} ET</b>${x.tone ? `<span class="tone ${esc(x.tone)}">${esc(x.tone)}</span>` : ""}${(x.words || []).map(w => `<span class="mw">${esc(w)}</span>`).join("")}${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">open</a>` : ""}</div>${esc(x.text)}</div>`).join("")
    || `<div class="expl" style="margin-top:0">No market-related posts in this window.</div>`;
}

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
  try { d = await (await fetch(API.indicator, {cache:"no-store"})).json(); }
  catch(e){ $("indMeta").innerHTML = `<span class="chip"><i class="dot warn"></i>${OFFLINE}</span>`; return; }
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
    || `<div class="expl" style="margin-top:0">No change history available here.</div>`;
  const pub = data && data.workers.find(w => w.published);
  $("indPasteTime").textContent = pub ? `${pub.published.slot_et.slice(11)} ET paste` : "Waiting for the first paste";
}
async function copyCode(){
  if(!ind) return;
  try { await navigator.clipboard.writeText(ind.code); toast(`Copied ${num(ind.lines, 0)} lines of ${ind.name} (version ${ind.version}). Paste it into TradingView's Pine Editor and click Save.`); }
  catch(e){ window.prompt("Copy the code (Ctrl+C):", ind.code); }
}
$("indCopy").onclick = copyCode;
$("indCopy2").onclick = copyCode;
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
  $("newsFoot").innerHTML = `Source: <a href="https://www.forexfactory.com/calendar" target="_blank" rel="noopener" style="color:var(--ink2)">ForexFactory calendar</a> (weekly export feed), checked every 30 min${news.fetched_at ? `, last updated ${ago(news.fetched_at)}` : ""}. Times in ET. F = forecast, P = previous; the feed has no actual results - see ForexFactory for those.${news.error ? ` <span style="color:var(--warn)">${esc(news.error)}</span>` : ""}`;
}

async function load(){
  try{ data = await (await fetch(API.all, {cache:"no-store"})).json(); render(); if(page === "indicator") renderIndicator(); }
  catch(e){ $("banner").innerHTML = `<div class="banner bad">${OFFLINE}</div>`; }
}

function ago(iso){ const m = (Date.now() - Date.parse(iso))/60000; return m < 1 ? "just now" : m < 60 ? `${Math.round(m)} min ago` : `${Math.floor(m/60)} h ${Math.round(m%60)} min ago`; }

function render(){
  const ws = data.workers, markets = [...new Set(ws.map(w => w.market))];
  if(!markets.includes(market)) market = markets[0];
  $("tabs").innerHTML = markets.map(m => `<button role="tab" aria-selected="${m===market}" data-m="${m}">${m}</button>`).join("");
  [...$("tabs").children].forEach(b => b.onclick = () => setMarket(b.dataset.m));
  $("copyMarket").textContent = `Copy ${market} only`;
  const anyPub = ws.some(w => w.published);
  $("copyAll").disabled = !anyPub;
  $("copyAll").textContent = anyPub ? `Copy for TradingView · ${ws.find(w=>w.published).published.slot_et.slice(11)} ET` : "Copy for TradingView";

  const w = ws.find(x => x.market === market && x.result) || ws.find(x => x.market === market);
  const h = w.health;
  const s = w.result && w.result.summary;
  // hosted copy: health was taken when the site was built, so also judge how old the build is
  const built = STATIC ? (Date.now() - Date.parse(data.now)) / 60000 : 0;
  const svc = h.status === "ok" && built < 45 ? "ok" : h.status === "starting" ? "" : "warn";
  const used = (s && s.provider) || w.provider, rt = s && s.ref_quality === "RT";
  const opts = s ? esc(s.options_source || w.source) + (s.etf ? "+" + esc(s.etf) : "") : esc(w.source);
  $("status").innerHTML = `<span class="chip"><i class="dot ${svc}"></i>Data <b>${esc(used)}</b> · ${opts}</span>
    <span class="chip">Options <b>${rt ? "real time" : "15-min delayed"}</b></span>
    ${s ? `<span class="chip">Updated <b>${ago(s.asof)}</b></span>` : ""}
    ${STATIC ? `<span class="chip" title="The hosted site is rebuilt about every 15 minutes in market hours and every hour otherwise">Site rebuilt <b>${ago(data.now)}</b></span>` : ""}
    <span class="chip">Next paste <b>${h.next_publish_et ? esc(h.next_publish_et.slice(11)) + " ET" : "-"}</b></span>
    ${(() => { const e = nextHighUSD(); return e ? `<span class="chip" title="Next ${e.impact.toLowerCase()}-impact USD event (ForexFactory)"><i class="dot ${e.impact === "High" ? "bad" : "warn"}"></i>${esc(e.title)} <b>in ${dur(Date.parse(e.time) - Date.now())}</b></span>` : ""; })()}`;
  $("banner").innerHTML = !w.result ? `<div class="banner">${h.last_error ? "Data error: " + esc(h.last_error) : "First calculation in progress..."}</div>`
    : h.last_error ? `<div class="banner">${esc(h.last_error)}</div>` : "";
  if(!w.result) return;
  const L = w.result.mapped || s, X = L.extras || {};
  const ref = L.futures_equiv_of_ref ?? s.ref_price;
  renderHero(w, s, L, X, ref);
  renderLadder(L, X, ref, !!w.result.mapped);
  renderChart(w, s, L, ref);
  renderMaxPain(X);
  renderStats(w, s, L, X);
  renderExpiry(s);
  if(page === "bias") renderBias(w);
  renderTicker();
  if(page === "gamma") renderGamma();
  if(page === "vol") renderVol();
  $("foot").innerHTML = `Model estimates from ${esc(s.provider || w.provider)} ${opts} options (${s.ref_quality === "RT" ? "real-time quotes" : "15-minute-delayed quotes"}) and end-of-day open interest, assuming dealers are long calls and short puts.
    ${w.result.mapped ? "Futures prices use " + esc(w.result.mapped.mapping.futures_ref_mode) + "; TradingView re-maps with your live chart." : esc(s.mapping_note || "")}
    These are proxy levels from index and ETF options, not NQ/ES futures options, and not trading advice.`;
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
  const sigTxt = sig == null ? "" : `<div class="kv" style="margin-top:10px"><span>Price vs zero gamma</span><b>${num(Math.abs(sig), 1)}σ ${sig >= 0 ? "above" : "below"}</b></div>
    <div class="expl" style="margin-top:4px">${Math.abs(sig) < 0.3 ? "Right at the flip: the regime can change with a small move." : Math.abs(sig) < 1 ? "Within one expected move of the flip." : "More than a full expected move from the flip; the regime is well established."}</div>`;
  $("regimeCard").parentElement.classList.add("accent"); $("regimeCard").parentElement.style.setProperty("--accent", R[2]);
  $("regimeCard").innerHTML = `<div class="eyebrow">Gamma regime (model)</div>
    <div class="regime"><span class="tag" style="color:${R[2]};border-color:${R[2]}">${R[1]}</span><span style="color:${R[2]}">${R[0]}</span>${changed ? '<span class="chip">changed since last update</span>' : ""}</div>
    <div class="expl">${R[3]}</div>${sigTxt}`;
  const em = X.expected_move || {};
  const fop = /_FOP$/.test(w.source);                 // levels straight from CME options on the future
  $("priceCard").innerHTML = `<div class="eyebrow">Reference price</div>
    <div class="big">${num(ref)}</div>
    <div class="kv"><span>${fop ? esc(s.underlying || market) + " future, live" : esc(w.source) + " close / last"}</span><b>${num(s.ref_price)}</b></div>
    <div class="kv"><span>Expected move today (1 sd)</span><b>±${num(em.daily_points_fut ?? em.daily_points, 0)} pts</b></div>
    <div class="expl">${fop ? "Levels come from CME options on the " + market + " future itself, so they are already in futures prices; no conversion needed."
      : w.result.mapped ? market + " equivalent of the index price, from the carry model. Your TradingView chart uses the live price." : "Options-underlying price (no futures conversion available)."}</div>`;
  $("netCard").innerHTML = `<div class="eyebrow">Net gamma exposure</div>
    <div class="big sm" style="color:${s.net>=0?"var(--pos)":"var(--neg)"}">${money(s.net)}<span style="font-size:13px;color:var(--ink3)"> per 1% move</span></div>
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
  let html = "", placed = false;
  for(const [g, kind, name, price, desc] of rows){
    if(!placed && price < ref){ html += nowRow(ref); placed = true; }
    const isKey = g === "key";
    html += `<div class="row${isKey ? " key" : ""}"><div class="rule" style="background:${KIND_COLOR[kind]}"></div>
      <div><div class="name">${esc(name)} ${isKey ? '<span class="badge">KEY</span>' : `<span class="kind">${esc(GROUPS.find(x => x[0] === g)[1])}</span>`}</div><div class="desc">${desc}</div></div>
      <div class="px"><div class="p">${num(price)}</div><div class="d">${signed(price - ref)} pts</div></div></div>`;
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
  const pr0 = v => v && typeof v === "object" ? v.price : v;
  const keys = [pr0(L.zero_gamma), pr0(L.call_wall), pr0(L.put_wall)].filter(p => p != null && Math.abs(p / ref - 1) <= 0.08);
  const win = ref * 0.03, pad = ref * 0.004;
  const lo = Math.min(ref - win, ...keys.map(p => p - pad)), hi = Math.max(ref + win, ...keys.map(p => p + pad));
  const bars =w.result.by_strike.map(b => ({p:f(b.strike), k:b.strike, net:b.net})).filter(b => b.p >= lo && b.p <= hi);
  if(showTable){
    $("chartwrap").hidden = true; $("chartTable").hidden = false; $("tableToggle").textContent = "View as chart";
    $("chartTable").innerHTML = `<table><tr><th>Price</th><th>Strike (${esc(w.source)})</th><th>Net GEX per 1%</th></tr>${bars.slice().reverse().map(b => `<tr><td class="m">${num(b.p)}</td><td class="m">${num(b.k,0)}</td><td class="m" style="color:${b.net>=0?"var(--pos)":"var(--neg)"}">${money(b.net)}</td></tr>`).join("")}</table>`;
    return;
  }
  $("chartwrap").hidden = false; $("chartTable").hidden = true; $("tableToggle").textContent = "View as table";
  const svg = $("chart"), W = Math.max($("chartwrap").clientWidth, 320), H = 440, padL = 66, padR = 150, padT = 8, padB = 8;
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
  const pr = v => v && typeof v === "object" ? v.price : v;
  const marks = [[ref, "Price", "var(--ink)", ""], [pr(L.zero_gamma), "Zero gamma", "var(--zg)", "5 4"],
                 [pr(L.call_wall), "Call wall", "var(--pos)", "2 3"], [pr(L.put_wall), "Put wall", "var(--neg)", "2 3"],
                 [pr(L.abs_gamma), "Abs gamma", "var(--ag)", "1 3"]]
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
    tip.innerHTML = `${num(b.p)} <span style="color:var(--ink3)">(${esc(w.source)} ${num(b.k,0)})</span><br><span style="color:${b.net>=0?"var(--pos)":"var(--neg)"}">${money(b.net)}</span> per 1%`;
    tip.style.opacity = 1; tip.style.left = Math.min(e.clientX - r.left + 14, W - 190) + "px"; tip.style.top = (y(b.p) - 18) + "px";
  };
  svg.onmouseleave = () => { tip.style.opacity = 0; };
}

const POINT_VALUE = {NQ: 20, MNQ: 2, ES: 50, MES: 5};        // $ per index point per futures contract
function renderStats(w, s, L, X){
  const r = X.ratios || {}, em = X.expected_move || {}, g = X.greeks || {}, d = w.result.delta, f = w.result.mapped ? w.result.mapped.mapping.factor : 1;
  const nearExp = s.basket[0], near = (s.by_expiry || {})[nearExp], lab = (X.nearest && X.nearest.label) || "Nearest";
  const fut = L.futures_equiv_of_ref ?? s.ref_price, contract = fut * (POINT_VALUE[market] || 1);    // $ notional of one contract
  const ct = usd => usd == null || !isFinite(usd) ? null : usd / contract;
  const tile = (k, v, sub, color) => `<div class="stat"><div class="eyebrow">${k}</div><div class="v"${color ? ` style="color:${color}"` : ""}>${v}</div><div class="s">${sub}</div></div>`;
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

const BIAS_COLOR = {Bullish: "var(--pos)", Bearish: "var(--neg)", Neutral: "var(--zg)"};
function renderBias(w){
  const b = w.result.bias;
  if(!b){ $("biasCard").innerHTML = `<div class="eyebrow">Today's bias</div><div class="expl">Not available right now (needs levels and an expected move).</div>`; return; }
  const col = BIAS_COLOR[b.bias], ref = b.ref;
  const tm = iso => new Date(iso).toLocaleTimeString("en-US", {...ET, hour:"numeric", minute:"2-digit"});
  $("biasCard").parentElement.classList.add("accent"); $("biasCard").parentElement.style.setProperty("--accent", col);
  $("biasCard").innerHTML = `<div class="eyebrow">Today's bias (positioning model)</div>
    <div class="regime"><span class="tag" style="color:${col};border-color:${col}">${b.bias === "Bullish" ? "▲" : b.bias === "Bearish" ? "▼" : "◆"}</span><span style="color:${col}">${b.bias}</span><span class="chip">${b.confidence} confidence</span></div>
    <div class="kv"><span>Day type</span><b>${esc(b.day_type)}</b></div>
    <div class="kv"><span>Score</span><b>${b.score >= 0 ? "+" : ""}${num(b.score)}</b></div>`;
  $("targetCard").innerHTML = `<div class="eyebrow">Base case by the close</div>
    <div class="big" style="color:${col}">${num(b.target)}</div>
    <div class="kv"><span>From ${num(ref)}</span><b>${signed(b.target - ref)} pts</b></div>
    <div class="expl">Where the positioning factors point by 4 pm ET if nothing else intervenes.</div>`;
  $("rangeCard").innerHTML = `<div class="eyebrow">Expected range</div>
    <div class="big sm">${num(b.range[0])} – ${num(b.range[1])}</div>
    <div class="kv"><span>1σ expected move</span><b>±${num(b.expected_move, 0)} pts</b></div>
    <div class="expl">${b.side === "positive" ? "Tighter than the full expected move: positive gamma tends to cap the range, often at the walls." : b.side === "negative" ? "Wider on the side of the bias: negative gamma lets moves run." : "Full range: the day type depends on which side of zero gamma price holds."}</div>`;
  $("biasSummary").textContent = b.summary;
  $("biasWhen").textContent = b.session.live ? `Session in progress · calculated ${ago(w.result.summary.asof)}` : `Plan for the ${new Date(b.session.open).toLocaleDateString("en-US", {...ET, weekday:"long", month:"short", day:"numeric"})} session`;
  $("biasFactors").innerHTML = `<table><tr><th>Factor</th><th style="text-align:center">Lean</th><th style="text-align:left">Why</th></tr>${b.factors.map(f => {
    const c = f.score > 0 ? "var(--pos)" : f.score < 0 ? "var(--neg)" : "var(--ink3)";
    return `<tr><td style="white-space:nowrap">${esc(f.name)}</td><td class="m" style="text-align:center;color:${c};white-space:nowrap">${f.score > 0 ? "▲ +" + num(f.score) : f.score < 0 ? "▼ " + num(f.score) : "· day type"}</td><td style="text-align:left;white-space:normal;color:var(--ink2)">${esc(f.why)}</td></tr>`; }).join("")}</table>`;
  drawBias(b, col);
}

function drawBias(b, col){
  const svg = $("biasChart"), W = Math.max($("biasWrap").clientWidth, 320), H = 420, padL = 70, padR = 132, padT = 14, padB = 30;
  const lv = Object.entries(b.levels || {}).filter(([, p]) => Math.abs(p - b.ref) <= 1.6 * b.expected_move);
  const ys = [...b.cone.flatMap(c => [c[1], c[2]]), ...b.path.map(p => p[1]), ...b.range, ...lv.map(([, p]) => p)];
  const lo = Math.min(...ys) - b.expected_move * 0.08, hi = Math.max(...ys) + b.expected_move * 0.08, T = b.session.minutes;
  const x = m => padL + m / T * (W - padL - padR), y = p => padT + (hi - p) / (hi - lo) * (H - padT - padB);
  const open = new Date(b.session.open);
  const clock = m => new Date(open.getTime() + m * 60000).toLocaleTimeString("en-US", {...ET, hour:"numeric", minute:"2-digit"});
  let g = "";
  for(let i = 0; i <= 6; i++){ const p = lo + (hi - lo) * i / 6; g += `<line x1="${padL}" x2="${W-padR}" y1="${y(p)}" y2="${y(p)}" stroke="var(--line)"/><text x="${padL-8}" y="${y(p)+4}" text-anchor="end">${num(p,0)}</text>`; }
  for(let m = 30; m <= T; m += 60){ g += `<line x1="${x(m)}" x2="${x(m)}" y1="${padT}" y2="${H-padB}" stroke="var(--line)"/><text x="${x(m)}" y="${H-10}" text-anchor="middle">${clock(m)}</text>`; }
  // range band and cone
  g += `<rect x="${x(b.session.start_minute)}" y="${y(b.range[1])}" width="${x(T) - x(b.session.start_minute)}" height="${y(b.range[0]) - y(b.range[1])}" fill="${col}" opacity=".06"/>`;
  g += `<polygon points="${b.cone.map(c => `${x(c[0])},${y(c[2])}`).join(" ")} ${b.cone.slice().reverse().map(c => `${x(c[0])},${y(c[1])}`).join(" ")}" fill="rgba(139,149,165,.22)" stroke="rgba(139,149,165,.45)" stroke-width="1"/>`;
  // key levels with collision-free labels
  const LC = {"Call wall": "var(--pos)", "Put wall": "var(--neg)", "Zero gamma": "var(--zg)", "Abs gamma": "var(--ag)", "Max pain 0DTE": "var(--mp)"};
  lv.forEach(([n, p]) => { g += `<line x1="${padL}" x2="${W-padR}" y1="${y(p)}" y2="${y(p)}" stroke="${LC[n]}" stroke-width="1.3" stroke-dasharray="${n === "Zero gamma" ? "6 4" : "2 3"}"/>`; });
  const labels = [...lv.map(([n, p]) => [p, `${n} ${num(p,0)}`, LC[n]]), [b.target, `Base case ${num(b.target,0)}`, col]];
  let last = -1e9;
  labels.sort((a, c) => y(a[0]) - y(c[0])).forEach(([p, t, c]) => { const ly = Math.max(y(p) + 4, last + 14); last = ly; g += `<text x="${W-padR+8}" y="${ly}" style="fill:${c}">${esc(t)}</text>`; });
  // path, start and now markers
  g += `<polyline fill="none" stroke="${col}" stroke-width="2.5" stroke-linejoin="round" points="${b.path.map(p => `${x(p[0])},${y(p[1])}`).join(" ")}"/>`;
  const s0 = b.path[0];
  g += `<circle cx="${x(s0[0])}" cy="${y(s0[1])}" r="5" fill="${col}" stroke="var(--panel)" stroke-width="2"/>`;
  if(b.session.live) g += `<line x1="${x(s0[0])}" x2="${x(s0[0])}" y1="${padT}" y2="${H-padB}" stroke="var(--ink3)" stroke-dasharray="3 3"/><text x="${x(s0[0]) + 6}" y="${padT + 12}" style="fill:var(--ink2)">now</text>`;
  else g += `<text x="${x(0) + 6}" y="${padT + 12}" style="fill:var(--ink2)">open</text>`;
  const pe = b.path.at(-1);
  g += `<circle cx="${x(pe[0])}" cy="${y(pe[1])}" r="4" fill="var(--panel)" stroke="${col}" stroke-width="2"/>`;
  svg.setAttribute("width", W); svg.setAttribute("height", H); svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = g;
  $("pathSw").style.background = col;
  const tip = $("biasTip");
  svg.onmousemove = e => {
    const r = svg.getBoundingClientRect(), mx = (e.clientX - r.left - padL) / (W - padL - padR) * T;
    let i = 0; b.path.forEach((p, k) => { if(Math.abs(p[0] - mx) < Math.abs(b.path[i][0] - mx)) i = k; });
    const p = b.path[i], c = b.cone[i];
    tip.innerHTML = `${clock(p[0])} ET<br>Base case <b style="color:${col}">${num(p[1])}</b><br><span style="color:var(--ink3)">1σ ${num(c[1],0)} – ${num(c[2],0)}</span>`;
    tip.style.opacity = 1; tip.style.left = Math.min(x(p[0]) + 12, W - 170) + "px"; tip.style.top = (y(p[1]) - 30) + "px";
  };
  svg.onmouseleave = () => { tip.style.opacity = 0; };
}

function renderExpiry(s){
  const rows = Object.entries(s.by_expiry || {}).sort((a, b) => a[0].localeCompare(b[0])).slice(0, 8);
  const mx = Math.max(1, ...rows.map(([, v]) => v.abs));
  $("byExpiry").innerHTML = rows.length ? `<table><tr><th>Expiration</th><th>Net gamma</th><th style="width:38%">Share of total</th></tr>${rows.map(([e, v]) => {
    const dLbl = new Date(e + "T12:00:00Z").toLocaleDateString("en-US", {weekday:"short", month:"short", day:"numeric", timeZone:"UTC"});
    return `<tr><td>${esc(dLbl)}</td><td class="m" style="color:${v.net >= 0 ? "var(--pos)" : "var(--neg)"}">${money(v.net)}</td>
      <td><span class="xbar" style="width:${Math.max(2, 100 * v.abs / mx * 0.7)}%;background:${v.net >= 0 ? "var(--pos)" : "var(--neg)"}"></span> <span class="m" style="color:var(--ink3)">${s.gross ? num(100 * v.abs / s.gross, 0) : "-"}%</span></td></tr>`; }).join("")}</table>` : `<div class="expl">No data.</div>`;
}

function renderMaxPain(X){
  const mp = (X.max_pain || []).slice(0, 8);
  $("maxpain").innerHTML = mp.length ? `<table><tr><th>Expiration</th><th>Max pain</th><th>Open interest</th></tr>${mp.map(m => {
    const d = new Date(m.expiration + "T12:00:00Z").toLocaleDateString("en-US",{weekday:"short",month:"short",day:"numeric",timeZone:"UTC"});
    return `<tr><td>${esc(d)}</td><td class="m" style="color:var(--mp)">${num(m.price)}</td><td class="m">${num(m.oi,0)}</td></tr>`; }).join("")}</table>` : `<div class="expl">No data.</div>`;
}

// =====================================================================================================
// Terminal: pages, ticker, clock, command line, keyboard, explain drawer, and the pro modules
// (gamma curve, gamma by expiry bucket, positioning, volatility term structure and skew, timeline)
// =====================================================================================================
const PAGES = [
  ["levels", "Levels", "LVL"], ["gamma", "Gamma lab", "GEX"], ["vol", "Volatility", "VOL"], ["timeline", "Timeline", "TL"],
  ["bias", "Bias", "BIAS"], ["track", "Track record", "TRK"], ["strategies", "Strategies", "STR"], ["briefings", "Briefings", "BRF"], ["news", "News", "NEWS"], ["indicator", "Indicator", "IND"],
  ["library", "Library", "LIB"]];
const NO_MARKET_PAGES = ["news", "indicator", "briefings", "library", "track", "strategies"];
const pickP = v => v && typeof v === "object" ? v.price : v;
const curW = () => data && (data.workers.find(x => x.market === market && x.result) || data.workers.find(x => x.market === market));

// ---------- clock and session state (New York)
function sessionLabel(d){
  const t = new Date(d.toLocaleString("en-US", ET)), wd = t.getDay(), m = t.getHours() * 60 + t.getMinutes();
  if(wd === 6 || (wd === 0 && m < 18 * 60) || (wd === 5 && m >= 17 * 60)) return ["Futures closed", "bad"];
  if(wd >= 1 && wd <= 5 && m >= 570 && m < 960) return ["US cash open", "ok"];
  if(m >= 17 * 60 && m < 18 * 60) return ["Daily break", "warn"];
  return [m >= 960 || m < 240 ? "Globex · Asia" : "Globex · Europe", "warn"];
}
function tickClock(){
  const d = new Date(), [lab, cls] = sessionLabel(d);
  $("clock").innerHTML = `<i class="dot ${cls}" style="display:inline-block;margin-right:6px"></i>${d.toLocaleTimeString("en-US", {...ET, hour12:false})} ET · ${lab}`;
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
      <span><em>ZG</em> <b>${num(pickP(L.zero_gamma), 0)}</b></span><span><em>CW</em> <b style="color:var(--pos)">${num(pickP(L.call_wall), 0)}</b></span>
      <span><em>PW</em> <b style="color:var(--neg)">${num(pickP(L.put_wall), 0)}</b></span><span><em>EM</em> <b>±${num(emd, 0)}</b></span>
      <span><em>NET</em> <b style="color:${s.net >= 0 ? "var(--pos)" : "var(--neg)"}">${money(s.net)}</b></span></div>`;
  }).join("");
  const w = curW(), s = w && w.result && w.result.summary;
  const info = s ? `<div class="tk info"><span><em>DATA</em> <b>${esc(s.provider || w.provider)}</b></span><span><em>AS OF</em> <b>${ago(s.asof)}</b></span>
    <span><em>NEXT PASTE</em> <b>${w.health.next_publish_et ? esc(w.health.next_publish_et.slice(11)) + " ET" : "-"}</b></span></div>` : "";
  $("ticker").innerHTML = cells + info;
  [...$("ticker").querySelectorAll(".tk[data-m]")].forEach(el => el.onclick = () => setMarket(el.dataset.m));
}
function setMarket(m){ market = m; store.set("gex.market", m); render(); if(page === "timeline") renderTimeline(); }

// ---------- gamma curve (net dealer gamma if price moved), with flip zone and expected-move band
function renderGamma(){
  const w = curW();
  if(!w || !w.result) return;
  const s = w.result.summary, L = w.result.mapped || s, X = L.extras || {}, m = w.result.mapped;
  const f = m ? (p => p * m.mapping.factor + m.mapping.offset) : (p => p);
  const pts = (w.result.profile || []).map(r => ({p: f(r.price), v: r.net}));
  const ref = L.futures_equiv_of_ref ?? s.ref_price, zg = pickP(L.zero_gamma), em = X.expected_move || {}, emd = em.daily_points_fut ?? em.daily_points;
  const svg = $("curve"), W = Math.max($("curveWrap").clientWidth, 320), H = 360, pl = 70, pr = 16, pt = 14, pb = 28;
  if(!pts.length){ svg.innerHTML = ""; $("curveSub").textContent = "No profile available"; return; }
  const lo = pts[0].p, hi = pts.at(-1).p, mx = Math.max(1, ...pts.map(q => Math.abs(q.v)));
  const x = p => pl + (p - lo) / (hi - lo) * (W - pl - pr), y = v => pt + (mx - v) / (2 * mx) * (H - pt - pb);
  // flip zone: contiguous prices around zero gamma where |net| is within 10% of the curve's peak
  let zone = null;
  if(zg != null){
    let i = pts.findIndex(q => q.p >= zg); i = Math.max(0, Math.min(pts.length - 1, i));
    let a = i, b = i;
    while(a > 0 && Math.abs(pts[a - 1].v) <= 0.1 * mx) a--;
    while(b < pts.length - 1 && Math.abs(pts[b + 1].v) <= 0.1 * mx) b++;
    zone = [pts[a].p, pts[b].p];
  }
  let g = "";
  for(let i = 0; i <= 4; i++){ const v = -mx + 2 * mx * i / 4; g += `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(var(--fg-rgb),.05)"/><text x="${pl - 8}" y="${y(v) + 4}" text-anchor="end">${i === 2 ? "0" : money(v)}</text>`; }
  for(let i = 0; i <= 6; i++){ const p = lo + (hi - lo) * i / 6; g += `<text x="${x(p)}" y="${H - 8}" text-anchor="middle">${num(p, 0)}</text>`; }
  if(emd && ref) g += `<rect x="${x(Math.max(lo, ref - emd))}" y="${pt}" width="${Math.max(0, x(Math.min(hi, ref + emd)) - x(Math.max(lo, ref - emd)))}" height="${H - pt - pb}" fill="rgba(139,149,165,.07)"/>`;
  if(zone) g += `<rect x="${x(zone[0])}" y="${pt}" width="${Math.max(2, x(zone[1]) - x(zone[0]))}" height="${H - pt - pb}" fill="rgba(185,190,199,.13)"/>`;
  const path = pts.map((q, i) => `${i ? "L" : "M"}${x(q.p).toFixed(1)},${y(q.v).toFixed(1)}`).join("");
  const area = (sign) => `M${x(lo)},${y(0)} ` + pts.map(q => `L${x(q.p).toFixed(1)},${y(sign > 0 ? Math.max(0, q.v) : Math.min(0, q.v)).toFixed(1)}`).join(" ") + ` L${x(hi)},${y(0)} Z`;
  g += `<path d="${area(1)}" fill="rgba(57,135,229,.22)"/><path d="${area(-1)}" fill="rgba(217,89,38,.22)"/>`;
  g += `<line x1="${pl}" x2="${W - pr}" y1="${y(0)}" y2="${y(0)}" stroke="rgba(var(--fg-rgb),.22)"/>`;
  g += `<path d="${path}" fill="none" stroke="var(--ink)" stroke-width="1.6" stroke-opacity=".85"/>`;
  const vline = (p, col, dash, label, top) => p == null || p < lo || p > hi ? "" :
    `<line x1="${x(p)}" x2="${x(p)}" y1="${pt}" y2="${H - pb}" stroke="${col}" stroke-width="1.3" ${dash ? `stroke-dasharray="${dash}"` : ""}/><text x="${x(p) + 4}" y="${pt + 11 + (top || 0)}" style="fill:${col}">${label}</text>`;
  g += vline(pickP(L.put_wall), "var(--neg)", "2 3", "PW", 14) + vline(pickP(L.call_wall), "var(--pos)", "2 3", "CW", 14) + vline(zg, "var(--zg)", "5 4", "ZG", 28) + vline(ref, "var(--ink)", "", "PRICE", 0);
  if(emd && ref){ g += vline(ref - emd, "var(--em)", "1 3", "-1σ", 42) + vline(ref + emd, "var(--em)", "1 3", "+1σ", 42); }
  svg.setAttribute("width", W); svg.setAttribute("height", H); svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.innerHTML = g;
  const here = pts.reduce((b, q) => Math.abs(q.p - ref) < Math.abs(b.p - ref) ? q : b, pts[0]);
  $("curveSub").textContent = `At price: ${money(here.v)} per 1% · ` + (zone ? `flip zone ${num(zone[0], 0)}-${num(zone[1], 0)} (${num(zone[1] - zone[0], 0)} pts wide)` : "no flip inside ±5%");
  const tip = $("curveTip");
  svg.onmousemove = e => {
    const r = svg.getBoundingClientRect(), px = lo + (e.clientX - r.left - pl) / (W - pl - pr) * (hi - lo);
    const q = pts.reduce((b, c) => Math.abs(c.p - px) < Math.abs(b.p - px) ? c : b, pts[0]);
    tip.innerHTML = `If price were <b>${num(q.p)}</b><br><span style="color:${q.v >= 0 ? "var(--pos)" : "var(--neg)"}">${money(q.v)}</span> per 1% · ${signed(q.p - ref, 0)} pts`;
    tip.style.opacity = 1; tip.style.left = Math.min(x(q.p) + 12, W - 200) + "px"; tip.style.top = (y(q.v) - 34) + "px";
  };
  svg.onmouseleave = () => { tip.style.opacity = 0; };
  // gamma by time-to-expiry bucket
  const order = ["0DTE", "1D", "2-7D", "8-30D", "31D+"], bk = s.by_dte_bucket || {};
  const rows = order.filter(k => bk[k]), amax = Math.max(1, ...rows.map(k => Math.abs(bk[k].net)));
  $("dteBars").innerHTML = rows.length ? `<div class="bars">${rows.map(k => {
    const v = bk[k].net, wpc = Math.abs(v) / amax * 50;
    return `<div class="bar-row"><span class="lab">${k}</span><span class="track"><span class="mid"></span><i style="${v >= 0 ? "left:50%" : `left:${50 - wpc}%`};width:${wpc}%;background:${v >= 0 ? "var(--pos)" : "var(--neg)"}"></i></span>
      <span class="val" style="color:${v >= 0 ? "var(--pos)" : "var(--neg)"}">${money(v)} <span style="color:var(--ink3)">${s.gross ? num(100 * bk[k].abs / s.gross, 0) : "-"}%</span></span></div>`; }).join("")}</div>
    <div class="expl">Bars: net gamma per bucket (left = negative, right = positive). Percent: share of all gamma. Short-dated buckets move levels fastest.</div>` : `<div class="expl">No data.</div>`;
  // positioning metrics
  const fac = m ? m.mapping.factor : 1, ctr = ref * (POINT_VALUE[market] || 1);
  const cp = s.call_total && s.put_total ? Math.abs(s.call_total) / (Math.abs(s.call_total) + Math.abs(s.put_total)) : null;
  const sig = zg != null && emd ? (ref - zg) / emd : null;
  const met = (k, v, sub, col) => `<div class="metric"><div class="eyebrow">${k}</div><div class="v"${col ? ` style="color:${col}"` : ""}>${v}</div><div class="s">${sub}</div></div>`;
  $("posMetrics").innerHTML = `<div class="metrics">
    ${met("Call gamma", money(s.call_total), "dealers modeled long: hedging calms moves", "var(--pos)")}
    ${met("Put gamma", money(s.put_total), "dealers modeled short: hedging adds to moves", "var(--neg)")}
    ${met("Call share of gross", cp == null ? "-" : num(100 * cp, 0) + "%", "above 50% leans calm, below leans volatile")}
    ${met("Gross gamma", money(s.gross), "all gamma, sign ignored: total hedging firepower")}
    ${met("Near-price concentration", s.near_spot_concentration == null ? "-" : num(100 * s.near_spot_concentration, 0) + "%", "share of gamma within 1% of price: high = strong pinning")}
    ${met("Gamma-weighted distance", s.gamma_weighted_distance == null ? "-" : num(s.gamma_weighted_distance * fac, 0) + " pts", "average distance of gamma from price")}
    ${met("Distance to zero gamma", zg == null ? "-" : `${signed(ref - zg, 0)} pts`, sig == null ? "" : `${num(Math.abs(sig), 1)}σ ${sig >= 0 ? "above" : "below"}: ${Math.abs(sig) < 0.3 ? "at the flip" : Math.abs(sig) < 1 ? "near the flip" : "regime well set"}`)}
    ${met("Hedge per 1% move", num(Math.abs(s.net / ctr), 0) + " " + market, s.net >= 0 ? "contracts dealers trade against a 1% move" : "contracts dealers trade with a 1% move")}
  </div>`;
}

// ---------- volatility: term structure and skew
function renderVol(){
  const w = curW();
  if(!w || !w.result) return;
  const s = w.result.summary, L = w.result.mapped || s, rows = ((L.extras || {}).term || []).filter(r => r.atm_iv);
  const tbl = $("termTable");
  if(!rows.length){ tbl.innerHTML = `<div class="expl">No term-structure data.</div>`; $("termChart").innerHTML = ""; $("skewChart").innerHTML = ""; return; }
  const lab = r => `${r.expiration.slice(5)}${r.settle !== "16:00" ? " AM" : ""}`;
  // term chart: categorical x (each expiration), IV % on y
  const draw = (svg, wrap, series, yfmt, zeroLine) => {
    const W = Math.max(wrap.clientWidth, 320), H = 280, pl = 52, pr = 12, pt = 12, pb = 30, n = rows.length;
    const vals = series.flatMap(sr => rows.map(sr.get)).filter(v => v != null);
    let lo = Math.min(...vals), hi = Math.max(...vals); if(zeroLine){ lo = Math.min(0, lo); hi = Math.max(0, hi); }
    const padv = (hi - lo) * 0.12 || 1; lo -= padv; hi += padv;
    const x = i => pl + (n === 1 ? 0.5 : i / (n - 1)) * (W - pl - pr), y = v => pt + (hi - v) / (hi - lo) * (H - pt - pb);
    let g = "";
    for(let i = 0; i <= 4; i++){ const v = lo + (hi - lo) * i / 4; g += `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(var(--fg-rgb),.05)"/><text x="${pl - 8}" y="${y(v) + 4}" text-anchor="end">${yfmt(v)}</text>`; }
    rows.forEach((r, i) => { if(n < 9 || i % Math.ceil(n / 8) === 0) g += `<text x="${x(i)}" y="${H - 9}" text-anchor="middle">${lab(r)}</text>`; });
    if(zeroLine) g += `<line x1="${pl}" x2="${W - pr}" y1="${y(0)}" y2="${y(0)}" stroke="rgba(var(--fg-rgb),.2)"/>`;
    series.forEach(sr => {
      if(sr.bars){ const bw = Math.max(4, (W - pl - pr) / n * 0.55);
        rows.forEach((r, i) => { const v = sr.get(r); if(v == null) return; g += `<rect x="${x(i) - bw / 2}" y="${Math.min(y(v), y(0))}" width="${bw}" height="${Math.abs(y(v) - y(0))}" rx="2" fill="${v >= 0 ? "var(--neg)" : "var(--pos)"}" fill-opacity=".85"/>`; });
        return; }
      const p = rows.map((r, i) => sr.get(r) == null ? null : `${x(i).toFixed(1)},${y(sr.get(r)).toFixed(1)}`).filter(Boolean);
      g += `<polyline fill="none" stroke="${sr.col}" stroke-width="${sr.w || 1.8}" points="${p.join(" ")}"/>`;
      rows.forEach((r, i) => { const v = sr.get(r); if(v != null) g += `<circle cx="${x(i)}" cy="${y(v)}" r="2.6" fill="${sr.col}"/>`; });
    });
    svg.setAttribute("width", W); svg.setAttribute("height", H); svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.innerHTML = g;
    return {x, y, W};
  };
  const pc = v => v == null ? null : v * 100;
  const geo = draw($("termChart"), $("termWrap"), [
    {get: r => pc(r.put25_iv), col: "var(--neg)", w: 1.4}, {get: r => pc(r.call25_iv), col: "var(--pos)", w: 1.4}, {get: r => pc(r.atm_iv), col: "var(--ink)", w: 2.2}],
    v => num(v, 0) + "%");
  draw($("skewChart"), $("skewWrap"), [{get: r => r.skew_pts, bars: true}], v => num(v, 1), true);
  const tip = $("termTip"), svg = $("termChart");
  svg.onmousemove = e => {
    const r = svg.getBoundingClientRect(), mx = e.clientX - r.left;
    let i = 0; rows.forEach((_, k) => { if(Math.abs(geo.x(k) - mx) < Math.abs(geo.x(i) - mx)) i = k; });
    const q = rows[i];
    tip.innerHTML = `${esc(q.expiration)} · ${num(q.dte, 1)} days<br>ATM <b>${num(q.atm_iv * 100, 1)}%</b> · 25Δ put ${q.put25_iv ? num(q.put25_iv * 100, 1) + "%" : "-"} · 25Δ call ${q.call25_iv ? num(q.call25_iv * 100, 1) + "%" : "-"}`;
    tip.style.opacity = 1; tip.style.left = Math.min(geo.x(i) + 12, geo.W - 260) + "px"; tip.style.top = "20px";
  };
  svg.onmouseleave = () => { tip.style.opacity = 0; };
  // shape of the curve: front (1+ day) vs about a month out
  const front = rows.find(r => r.dte >= 1) || rows[0], month = rows.reduce((b, r) => Math.abs(r.dte - 30) < Math.abs(b.dte - 30) ? r : b, rows[0]);
  const slope = (month.atm_iv - front.atm_iv) * 100;
  $("termSub").textContent = front === month ? "" : `${slope >= 0 ? "Upward sloping (normal, calm)" : "Inverted (near-term stress)"}: ${num(front.atm_iv * 100, 1)}% (${lab(front)}) → ${num(month.atm_iv * 100, 1)}% (${lab(month)})`;
  const sk = rows.filter(r => r.skew_pts != null);
  $("skewSub").textContent = sk.length ? `Average ${num(sk.reduce((a, r) => a + r.skew_pts, 0) / sk.length, 1)} vol pts: puts ${sk[0].skew_pts >= 0 ? "richer" : "cheaper"} than calls` : "";
  const src = (s.options_source || w.source);
  tbl.innerHTML = `<table><tr><th>Expiration</th><th>Days</th><th>ATM IV</th><th>25Δ put IV</th><th>Put strike (${esc(src)})</th><th>25Δ call IV</th><th>Call strike (${esc(src)})</th><th>Skew</th></tr>${rows.map(r =>
    `<tr><td>${esc(r.expiration)} <span style="color:var(--ink3)">${esc(r.settle)}</span></td><td class="m">${num(r.dte, 1)}</td><td class="m">${num(r.atm_iv * 100, 1)}%</td>
     <td class="m" style="color:var(--neg)">${r.put25_iv ? num(r.put25_iv * 100, 1) + "%" : "-"}</td><td class="m">${r.put25_strike ? num(r.put25_strike, 0) : "-"}</td>
     <td class="m" style="color:var(--pos)">${r.call25_iv ? num(r.call25_iv * 100, 1) + "%" : "-"}</td><td class="m">${r.call25_strike ? num(r.call25_strike, 0) : "-"}</td>
     <td class="m">${r.skew_pts == null ? "-" : signed(r.skew_pts, 1)}</td></tr>`).join("")}</table>`;
}

// ---------- timeline: zero gamma and walls over time
let tl = null, tlHours = Number(store.get("gex.tlh", "72"));
async function loadTimeline(){
  try { tl = await (await fetch(STATIC ? API.timeline : API.timeline + "?hours=120", {cache:"no-store"})).json(); }
  catch(e){ tl = tl || {}; }
  renderTimeline();
}
function renderTimeline(){
  $("tlRange").innerHTML = [[24, "1D"], [72, "3D"], [120, "5D"]].map(([h, t]) => `<button role="tab" aria-selected="${tlHours === h}" data-h="${h}">${t}</button>`).join("");
  [...$("tlRange").children].forEach(b => b.onclick = () => { tlHours = Number(b.dataset.h); store.set("gex.tlh", String(tlHours)); renderTimeline(); });
  const all = (tl || {})[market] || [], cut = Date.now() - tlHours * 3600e3;
  const rows = all.filter(r => Date.parse(r.t) >= cut && r.ref);
  const svg = $("tlChart"), net = $("tlNet");
  if(rows.length < 2){
    svg.innerHTML = `<text x="16" y="30">History builds up as the app runs (one point per refresh). ${rows.length} point${rows.length === 1 ? "" : "s"} so far.</text>`;
    svg.setAttribute("width", Math.max($("tlWrap").clientWidth, 320)); svg.setAttribute("height", 60); svg.removeAttribute("viewBox");
    net.innerHTML = ""; net.setAttribute("height", 0); return;
  }
  const W = Math.max($("tlWrap").clientWidth, 320), H = 380, pl = 66, pr = 14, pt = 12, pb = 28;
  const t0 = Date.parse(rows[0].t), t1 = Date.parse(rows.at(-1).t);
  const vals = rows.flatMap(r => [r.ref, r.zg, r.cw, r.pw]).filter(v => v != null);
  let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.06 || 10; lo -= pad; hi += pad;
  const x = t => pl + (t - t0) / Math.max(1, t1 - t0) * (W - pl - pr), y = v => pt + (hi - v) / (hi - lo) * (H - pt - pb);
  let g = "";
  // negative-gamma periods shaded
  rows.forEach((r, i) => { if(r.regime === "NEGATIVE" && i < rows.length - 1){ const a = x(Date.parse(r.t)), b = x(Date.parse(rows[i + 1].t)); if(b - a < (W - pl) / 6) g += `<rect x="${a}" y="${pt}" width="${b - a + 0.5}" height="${H - pt - pb}" fill="rgba(217,89,38,.08)"/>`; } });
  for(let i = 0; i <= 5; i++){ const v = lo + (hi - lo) * i / 5; g += `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(var(--fg-rgb),.05)"/><text x="${pl - 8}" y="${y(v) + 4}" text-anchor="end">${num(v, 0)}</text>`; }
  for(let i = 0; i <= 4; i++){ const t = t0 + (t1 - t0) * i / 4; g += `<text x="${x(t)}" y="${H - 8}" text-anchor="middle">${new Date(t).toLocaleString("en-US", {...ET, weekday:"short", hour:"numeric"})}</text>`; }
  const line = (k, col, w, dash) => {
    const p = rows.filter(r => r[k] != null).map(r => `${x(Date.parse(r.t)).toFixed(1)},${y(r[k]).toFixed(1)}`);
    return p.length ? `<polyline fill="none" stroke="${col}" stroke-width="${w}" ${dash ? `stroke-dasharray="${dash}"` : ""} stroke-linejoin="round" points="${p.join(" ")}"/>` : "";
  };
  g += line("cw", "var(--pos)", 1.4, "") + line("pw", "var(--neg)", 1.4, "") + line("zg", "var(--zg)", 1.6, "5 3") + line("ref", "var(--ink)", 2, "");
  svg.setAttribute("width", W); svg.setAttribute("height", H); svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.innerHTML = g;
  const tip = $("tlTip");
  svg.onmousemove = e => {
    const r = svg.getBoundingClientRect(), tt = t0 + (e.clientX - r.left - pl) / (W - pl - pr) * (t1 - t0);
    const q = rows.reduce((b, c) => Math.abs(Date.parse(c.t) - tt) < Math.abs(Date.parse(b.t) - tt) ? c : b, rows[0]);
    tip.innerHTML = `${new Date(q.t).toLocaleString("en-US", {...ET, weekday:"short", hour:"numeric", minute:"2-digit"})} ET<br>Price <b>${num(q.ref)}</b> · ZG ${num(q.zg, 0)}<br><span style="color:var(--pos)">CW ${num(q.cw, 0)}</span> · <span style="color:var(--neg)">PW ${num(q.pw, 0)}</span> · ${esc((q.regime || "").toLowerCase())}`;
    tip.style.opacity = 1; tip.style.left = Math.min(x(Date.parse(q.t)) + 12, W - 220) + "px"; tip.style.top = "16px";
  };
  svg.onmouseleave = () => { tip.style.opacity = 0; };
  // net GEX
  const NW = Math.max($("tlNetWrap").clientWidth, 320), NH = 160, nmx = Math.max(1, ...rows.map(r => Math.abs(r.net || 0)));
  const nx = t => pl + (t - t0) / Math.max(1, t1 - t0) * (NW - pl - pr), ny = v => 10 + (nmx - v) / (2 * nmx) * (NH - 30);
  let h = `<line x1="${pl}" x2="${NW - pr}" y1="${ny(0)}" y2="${ny(0)}" stroke="rgba(var(--fg-rgb),.2)"/><text x="${pl - 8}" y="${ny(nmx) + 8}" text-anchor="end">${money(nmx)}</text><text x="${pl - 8}" y="${ny(-nmx)}" text-anchor="end">${money(-nmx)}</text>`;
  const bw = Math.max(1, (NW - pl - pr) / rows.length - 0.5);
  rows.forEach(r => { const v = r.net || 0; h += `<rect x="${nx(Date.parse(r.t)) - bw / 2}" y="${Math.min(ny(v), ny(0))}" width="${bw}" height="${Math.abs(ny(v) - ny(0))}" fill="${v >= 0 ? "var(--pos)" : "var(--neg)"}" fill-opacity=".8"/>`; });
  net.setAttribute("width", NW); net.setAttribute("height", NH); net.setAttribute("viewBox", `0 0 ${NW} ${NH}`); net.innerHTML = h;
}

// ---------- explain drawer: plain-English help for every module
const HELP = {
  regime: {title: "Gamma regime", tldr: "Are dealers likely to calm the market down, or push it further?",
    body: `<p>Options dealers hedge what they sell. When they hold <b>positive gamma</b>, their hedging buys dips and sells rips, which <b>dampens moves</b>: tighter ranges, more mean reversion.</p><p>With <b>negative gamma</b> they must sell into drops and buy into rallies, which <b>amplifies moves</b>: wider ranges, trend days, faster breaks.</p><p>The <b>σ distance</b> says how many of today's expected moves price sits from the flip (zero gamma). Under 0.3σ means the regime could change with a small move.</p>`,
    watch: ["Negative gamma + a level break = moves can accelerate", "Positive gamma = fade extremes toward the walls"],
    live: (w, s, L) => `Regime: ${s.regime}\nZero gamma: ${num(pickP(L.zero_gamma))}\nPrice: ${num(L.futures_equiv_of_ref ?? s.ref_price)}`},
  reference: {title: "Reference price", tldr: "The price every level here is measured against.",
    body: `<p>Levels are computed from <b>index and ETF options</b> (SPX + SPY for ES, NDX + QQQ for NQ). The big number is the <b>futures-equivalent</b> price, estimated with a cost-of-carry model, so the levels sit in futures prices.</p><p>The data is <b>15 minutes delayed</b> (Cboe's free feed). TradingView re-maps every level to your live chart, so the indicator lines stay aligned in real time.</p><p>The <b>expected move</b> is the 1-standard-deviation range implied by option prices for the session: about 2 days in 3 stay inside it.</p>`},
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
  gamma_curve: {title: "Gamma curve", tldr: "How dealer gamma would change if price moved, the clearest picture of the flip.",
    body: `<p>The engine re-prices every option at hypothetical prices (±5%) and sums dealer gamma at each. Where the curve is <b>above zero (blue)</b>, hedging calms moves; <b>below (orange)</b>, it amplifies them.</p><p>The <b>flip zone</b> is the band around zero gamma where gamma is near zero: the market there has little hedging support either way, so expect choppy, two-sided trade until it picks a side.</p><p>The shaded grey band is today's <b>1σ expected move</b>: the part of the curve price is likely to visit.</p>`,
    watch: ["A steep curve near price = regime can change fast", "Price inside the flip zone = no strong hedging bias"]},
  dte_buckets: {title: "Gamma by time to expiry", tldr: "Splits gamma into same-day, this-week, this-month and longer options.",
    body: `<p><b>0DTE</b> gamma is huge but short-lived: it controls intraday swings and disappears at 4 pm. <b>2-7 day</b> gamma shapes the week. <b>8-30 day</b> and longer gamma is the slower structural backdrop.</p><p>If 0DTE dominates, expect sharp intraday reactions at levels; if longer-dated gamma dominates, levels are sturdier day to day.</p>`},
  positioning: {title: "Positioning metrics", tldr: "The shape of dealer positioning in eight numbers.",
    body: `<p><b>Call vs put gamma</b>: the two sides of the book. <b>Call share</b> above 50% leans calm. <b>Gross gamma</b> is total hedging firepower. <b>Near-price concentration</b>: how much gamma sits within 1% of price (high = pinning). <b>Gamma-weighted distance</b>: how far, on average, the gamma sits from price. <b>Distance to zero gamma</b> in points and expected moves.</p>`},
  term: {title: "IV term structure", tldr: "The market's volatility forecast for each expiration.",
    body: `<p>Each point is the implied volatility of options expiring on that date. Normally the curve <b>slopes up</b> (more uncertainty further out): calm market. When near-term IV is <b>above</b> longer-term IV, the curve is <b>inverted</b>: the market is paying up for protection right now, a stress signal that pairs badly with negative gamma.</p><p>Bumps on single dates usually mark scheduled events (CPI, Fed, big earnings). The red and blue lines are the 25-delta put and call IVs: the gap between them is the skew.</p>`},
  skew: {title: "Put skew", tldr: "How much more downside protection costs than upside.",
    body: `<p>Skew = 25-delta put IV minus 25-delta call IV, in volatility points. Index options almost always have positive skew (puts richer). <b>Rising skew</b> = traders are buying crash protection; <b>falling or flat skew</b> = complacency or a squeeze higher.</p>`},
  term_table: {title: "By expiration", tldr: "The numbers behind the volatility charts.",
    body: `<p>For every expiration: days left, at-the-money IV, and the strike and IV of the roughly 25-delta put and call (strikes in index points). Skew is put IV minus call IV.</p>`},
  timeline: {title: "Levels over time", tldr: "How zero gamma and the walls moved, refresh by refresh.",
    body: `<p>Each point is one refresh of the model. Walls that <b>hold still</b> for days are sturdier; walls that <b>migrate</b> with price follow new positioning. Zero gamma rising toward price is a sign the market is moving into positive gamma (calmer); falling away below it is the opposite.</p><p>Orange shading marks periods of negative gamma.</p>`},
  timeline_net: {title: "Net GEX over time", tldr: "Whether total dealer gamma is building or draining.",
    body: `<p>Bars above zero are positive-gamma periods, below zero negative. A steady slide toward negative often precedes larger moves; a jump back to positive often follows a volatility event as positions reset.</p>`},
  bias: {title: "Daily bias", tldr: "A transparent, rule-based read of direction and day type.",
    body: `<p>Adds up a few positioning factors (magnet strike, charm flow, walls, vanna, 0DTE max pain) into a score. The gamma side decides the <b>day type</b> (range, trend or pivot), not the direction. It's a starting scenario, not a forecast.</p>`},
  base_case: {title: "Base case", tldr: "Where the factors point by the close if nothing else intervenes.",
    body: `<p>In positive gamma it's usually the magnet strike; in negative gamma it's a move in the direction of the bias; near the flip it's zero gamma itself. News and flows can override it.</p>`},
  bias_range: {title: "Expected range", tldr: "The likely range for the session given the gamma side.",
    body: `<p>Positive gamma tightens the range, often to the walls. Negative gamma widens it on the side of the bias.</p>`},
  bias_chart: {title: "Session path", tldr: "An illustration of how the day could unfold.",
    body: `<p>The line is the base-case path; the cone is the ±1σ expected move growing through the session. About one day in three, price leaves the cone.</p>`},
  factors: {title: "Factors", tldr: "Each ingredient of the bias, with its score and reason.", body: `<p>Positive scores lean bullish, negative bearish. "Day type" rows set the character of the session rather than the direction.</p>`},
  briefings: {title: "Briefings", tldr: "A written summary before the US open and before the Asia session.",
    body: `<p><b>NY AM</b> at 9:00 AM ET: levels, regime, expected range, 0DTE levels, today's US data and market-moving posts. <b>Asia</b> at 7:00 PM ET: where we closed, what changed since the morning, the overnight Asia/Europe calendar and tomorrow's US data.</p>`},
  calendar: {title: "Economic calendar", tldr: "Scheduled data releases that can override any level.",
    body: `<p>From ForexFactory. High-impact USD releases (CPI, payrolls, Fed) move NQ and ES the most. Levels often break on these releases, then rebuild as options reposition.</p>`},
  posts: {title: "Trump posts", tldr: "Posts that have moved futures, tagged when they mention market topics.",
    body: `<p>Yellow tags flag market words (tariffs, the Fed, China, oil). Bullish/bearish is a keyword guess, shown only when clear: read the post before acting.</p>`},
  indicator: {title: "GEX PRO indicator", tldr: "The TradingView script that draws these levels on your chart.",
    body: `<p>Copy the code into TradingView's Pine Editor once (and again whenever the version changes). Then paste the hourly levels payload into its settings: the indicator maps index levels to your live futures chart.</p>`},
  library: {title: "The Library", tldr: "A short course that explains everything on this site from zero.",
    body: `<p>Start with <b>What is an option?</b> and follow the lessons in order, or search for any term. Each lesson ends with a quick check; answer it correctly and the lesson is marked as read. Your progress is saved in this browser.</p><p>Every Explain panel links to the matching lesson, so you can jump from a number on the screen straight to the idea behind it.</p>`},
  track: {title: "Live track record", tldr: "What GEX PRO said before each open, graded against what the market did.",
    body: `<p>At every session, the levels from the <b>last calculation timestamped before 09:30 ET</b> are frozen as that day's plan: expected move, regime, walls, zero gamma, bias. Nothing can be changed afterwards. After the close, the plan is graded against the index's open, high, low and close.</p><p>Everything is in index points (NDX for NQ, SPX for ES), so the futures basis can't flatter or hurt the result. Missed sessions are listed, not hidden.</p><p>Small samples lie. Until about 20 sessions are graded, read the numbers as a diary, not as proof. The 95% range shows how uncertain each rate still is.</p>`,
    watch: ["The 95% range narrows as sessions add up", "\"rebuilt\" = frozen later from saved snapshots, using only data from before the open"]},
  track_scorecard: {title: "Scorecard", tldr: "Each claim the model makes, and how often it came true.",
    body: `<p><b>Expected move:</b> a fair one-sigma band should contain the close about 68% of the time. Much more means the band is too wide; much less, too narrow.</p><p><b>Regime:</b> the model says negative-gamma sessions should range wider than positive-gamma ones, measured in expected moves.</p><p><b>Walls:</b> a wall is <i>touched</i> when price trades within 5% of an expected move of it, and <i>held</i> when the close stays on the near side.</p><p><b>Bias:</b> only Bullish and Bearish calls are graded, against the close vs the plan's price. Compare it with the baseline, which always picks the more common direction.</p>`},
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
  strategies: {title: "Futures strategy lab", tldr: "Futures rules built on options data, listed only when they pass every test.",
    body: `<p>Each rule turns an options signal into a futures trade on ES or NQ: the expected move, the VIX term structure, intraday VIX, or GEX PRO's gamma levels. Every rule is fixed before it is tested.</p><p>It must make money after costs over the last 3 years on both ES and NQ, in both halves of that period. Swing rules must also hold up on 2010-2023 data that was never used to choose them. Only rules that pass everything are listed as strategies.</p><p><b>R</b> is profit per trade in expected moves, and the $ figure is per full-size contract ($50 per ES point, $20 per NQ point).</p>`,
    watch: ["Zero passed so far: there is no proven futures strategy here yet", "The forward test grows with every graded session"]},
  strat_proven: {title: "Proven strategies", tldr: "Rules that passed every test. Empty until one does.",
    body: `<p>A strategy appears here automatically once it passes: as the 3-year window rolls forward, or when a GEX-level rule collects 30+ trades with a significant profit. Nothing unproven is shown as a strategy.</p>`},
  strat_log: {title: "Research log", tldr: "Every rule tested, with its numbers and the reason it failed.",
    body: `<p>Each cell shows trades, the average profit per trade in expected moves (R), and the average in dollars per contract after costs. <b>Out of sample</b> is 2010 up to the 3-year window: data the rule never saw. A rule can be profitable and still fail when its profit is too small to rule out luck (t below the bar), or when one half of the period lost money.</p>`},
  strat_gex: {title: "Forward test on GEX levels", tldr: "Rules on GEX PRO's real walls, zero gamma and regime, tested as sessions are graded.",
    body: `<p>History has no free gamma data, so these rules can only be tested on the sessions the track record has frozen since it started. Each is run on that day's hourly bars with the plan made before the open. Results are shown once a rule has 30 trades.</p>`},
  paste: {title: "The hourly paste", tldr: "One text block that carries all levels to TradingView.",
    body: `<p>Published every hour on the hour (ET). One paste holds NQ and ES; each chart draws only its own market. The indicator marks levels stale after 90 minutes.</p>`},
};
const PAGE_HELP = {levels: "regime", gamma: "gamma_curve", vol: "term", timeline: "timeline", bias: "bias", briefings: "briefings", news: "calendar", indicator: "indicator", library: "library", track: "track", strategies: "strategies"};
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
    + (rel.length ? `<span class="eyebrow" style="width:100%">Also on this page</span>` + rel.map(k => `<button data-k="${k}">${esc(HELP[k].title)}</button>`).join("") : "");
  [...$("exMore").querySelectorAll("button[data-k]")].forEach(b => b.onclick = () => openExplain(b.dataset.k));
  const lb = $("exMore").querySelector("[data-lesson]");
  if(lb) lb.onclick = () => { closeExplain(); openLesson(lb.dataset.lesson); };
  document.querySelectorAll(".ex").forEach(b => b.classList.toggle("on", b.dataset.help === key));
  $("explain").classList.add("open"); $("explain").setAttribute("aria-hidden", "false"); document.body.classList.add("ex-open");
}
function closeExplain(){
  $("explain").classList.remove("open"); $("explain").setAttribute("aria-hidden", "true"); document.body.classList.remove("ex-open");
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
  {code: "REFRESH", desc: "Reload all data now", run: () => { load(); loadNews(); loadPosts(); if(page === "timeline") loadTimeline(); toast("Refreshing data..."); }},
  {code: "HELP", desc: "Keyboard shortcuts", run: () => showKeys(true)},
  {code: "LIGHT", desc: "Light mode", run: () => setTheme("light")}, {code: "DARK", desc: "Dark (night) mode", run: () => setTheme("dark")},
  {code: "LEARN", desc: "Start the beginner course", run: () => openLesson(LIB.lessons[0].id)},
  {code: "GLOSSARY", desc: "Open the A-Z glossary", run: () => { libTab = "glossary"; setPage("library"); }},
];
let cmdSel = 0;
function cmdMatches(q){ q = q.trim().toUpperCase(); return q ? COMMANDS.filter(c => c.code.startsWith(q) || c.desc.toUpperCase().includes(q)) : COMMANDS; }
function renderCmdList(){
  const ms = cmdMatches($("cmd").value), list = $("cmdList");
  if(document.activeElement !== $("cmd")){ list.hidden = true; return; }
  cmdSel = Math.min(cmdSel, Math.max(0, ms.length - 1));
  list.innerHTML = ms.map((c, i) => `<div class="${i === cmdSel ? "on" : ""}" data-i="${i}" role="option"><b>${esc(c.code)}</b><span>${esc(c.desc)}</span><span>↵</span></div>`).join("") || `<div><b>?</b><span>No command. Try GEX, VOL, NQ, COPY</span><span></span></div>`;
  list.hidden = false;
  [...list.querySelectorAll("[data-i]")].forEach(el => el.onmousedown = e => { e.preventDefault(); runCmd(ms[Number(el.dataset.i)]); });
}
function runCmd(c){ if(!c) return; $("cmd").value = ""; $("cmd").blur(); $("cmdList").hidden = true; c.run(); }
$("cmd").addEventListener("input", () => { cmdSel = 0; renderCmdList(); });
$("cmd").addEventListener("focus", renderCmdList);
$("cmd").addEventListener("blur", () => setTimeout(() => { $("cmdList").hidden = true; }, 120));
$("cmd").addEventListener("keydown", e => {
  const ms = cmdMatches($("cmd").value);
  if(e.key === "ArrowDown"){ cmdSel = Math.min(ms.length - 1, cmdSel + 1); renderCmdList(); e.preventDefault(); }
  else if(e.key === "ArrowUp"){ cmdSel = Math.max(0, cmdSel - 1); renderCmdList(); e.preventDefault(); }
  else if(e.key === "Enter"){ const exact = COMMANDS.find(c => c.code === $("cmd").value.trim().toUpperCase()); runCmd(exact || ms[cmdSel]); e.preventDefault(); }
  else if(e.key === "Escape"){ $("cmd").value = ""; $("cmd").blur(); }
});

// ---------- keyboard
const KEYS = [["/  or  Ctrl+K", "Command line"], ["1 - 9, 0", "Pages (Levels, Gamma lab, Volatility, Timeline, Bias, Track record, Strategies, Briefings, News, Indicator); type LIB for the Library"],
  ["N  /  E", "Switch to NQ / ES"], ["X", "Explain this page"], ["T", "Light / dark mode"], ["C", "Copy the TradingView paste"], ["?", "This list"], ["Esc", "Close panels"]];
function showKeys(on){ $("keys").hidden = !on; if(on) $("keysGrid").innerHTML = KEYS.map(([k, d]) => `<kbd>${esc(k)}</kbd><span>${esc(d)}</span>`).join(""); }
$("keysBtn").onclick = () => showKeys(true);
$("keysClose").onclick = () => showKeys(false);
$("keys").onclick = e => { if(e.target === $("keys")) showKeys(false); };
document.addEventListener("keydown", e => {
  const typing = /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || "");
  if((e.key === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing)){ e.preventDefault(); $("cmd").focus(); return; }
  if(e.key === "Escape"){ showKeys(false); closeExplain(); return; }
  if(typing || e.ctrlKey || e.metaKey || e.altKey) return;
  const n = e.key === "0" ? 10 : Number(e.key);
  if(n >= 1 && n <= PAGES.length) setPage(PAGES[n - 1][0]);
  else if(e.key === "n" || e.key === "N") setMarket("NQ");
  else if(e.key === "e" || e.key === "E") setMarket("ES");
  else if(e.key === "x" || e.key === "X") $("explainTab").click();
  else if(e.key === "t" || e.key === "T") $("themeBtn").click();
  else if(e.key === "c" || e.key === "C") $("copyAll").click();
  else if(e.key === "?") showKeys(true);
});


// ---------- Library: the beginner course (content in assets/library.js)
const LIB = window.GEX_LIBRARY || {chapters: [], lessons: [], glossary: [], diagrams: {}, forHelp: {}};
let libLesson = store.get("gex.lib", LIB.lessons[0] ? LIB.lessons[0].id : ""), libTab = "course";
const libRead = (() => { try { return new Set(JSON.parse(store.get("gex.libread", "[]"))); } catch(e){ return new Set(); } })();
const saveRead = () => store.set("gex.libread", JSON.stringify([...libRead]));
function openLesson(id){ libLesson = id; store.set("gex.lib", id); libTab = "course"; if(page !== "library") setPage("library"); else renderLibrary(); document.querySelector(".area").scrollTo({top: 0, behavior: "smooth"}); }
function renderLibrary(){
  const q = ($("libSearch").value || "").trim().toLowerCase();
  const hit = s => !q || s.toLowerCase().includes(q);
  $("libTabs").innerHTML = [["course", "Course"], ["glossary", "Glossary"]].map(([k, t]) => `<button role="tab" aria-selected="${libTab === k}" data-k="${k}">${t}</button>`).join("");
  [...$("libTabs").children].forEach(b => b.onclick = () => { libTab = b.dataset.k; renderLibrary(); });
  const n = LIB.lessons.length, done = LIB.lessons.filter(l => libRead.has(l.id)).length;
  $("libBar").style.width = (n ? 100 * done / n : 0) + "%";
  $("libCount").textContent = `${done} of ${n} lessons read`;
  $("libCourse").hidden = libTab !== "course"; $("libGlossary").hidden = libTab !== "glossary";
  if(libTab === "glossary"){
    const rows = LIB.glossary.filter(([t, d]) => hit(t + " " + d));
    $("libGloss").innerHTML = rows.map(([t, d, id]) => `<div class="gterm"><b>${esc(t)}</b><span>${esc(d)}</span>${id ? `<button class="linkbtn" data-l="${esc(id)}">Lesson →</button>` : ""}</div>`).join("")
      || `<div class="expl">No term matches "${esc(q)}".</div>`;
    [...$("libGloss").querySelectorAll("[data-l]")].forEach(b => b.onclick = () => openLesson(b.dataset.l));
    return;
  }
  const visible = LIB.lessons.filter(l => hit(l.title + " " + l.oneLiner + " " + l.body.replace(/<[^>]+>/g, " ")));
  $("libToc").innerHTML = LIB.chapters.map(([ck, ct]) => {
    const ls = visible.filter(l => l.chapter === ck);
    return ls.length ? `<div class="toc-ch">${esc(ct)}</div>` + ls.map(l => `<button class="toc-l${l.id === libLesson ? " on" : ""}" data-l="${esc(l.id)}"><i class="${libRead.has(l.id) ? "rd" : ""}"></i><span>${esc(l.title)}</span><em>${l.minutes}m</em></button>`).join("") : "";
  }).join("") || `<div class="expl" style="margin:8px">No lesson matches "${esc(q)}".</div>`;
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
  try { trk = await (await fetch(API.track, {cache: "no-store"})).json(); }
  catch(e){ trk = trk || {error: OFFLINE}; }
  if(page === "strategies") renderStrategies(); else renderTrack();
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
    + kpi("Walls held when touched", pct(wh.rate), wh.n ? `${wh.k} of ${wh.n} touches` : "no wall touched yet")
    + kpi("Bias direction right", pct(bi.rate), bi.n ? `${bi.k} of ${bi.n} calls · baseline ${pct(bi.baseline)}` : "no directional calls graded yet");
  const proof = trk.proof_url ? ` Every plan and grade is committed to a public git branch as it happens: <a href="${esc(trk.proof_url)}" target="_blank" rel="noopener">see the history</a>.` : "";
  $("trkNote").innerHTML = (S.early ? `Early days: ${n} graded session${n === 1 ? "" : "s"}. The numbers need about ${trk.rules.min_sample} sessions before they mean much, and 100+ to be convincing. ` : "")
    + `Each plan uses the last GEX PRO calculation timestamped before the 09:30 ET open, frozen once and graded after the close against the index's open, high, low and close. Missed sessions stay in the list.` + proof;
  // scorecard
  const row = (name, st, meaning) => st ? `<tr><td>${name}</td><td class="m"><b>${pct(st.rate)}</b></td><td class="m">${st.n ? `${st.k}/${st.n}` : "-"}</td><td class="m">${ciTxt(st)}</td><td class="trk-mean">${meaning}</td></tr>` : "";
  const rp = (S.range_em || {}).positive || {}, rn = (S.range_em || {}).negative || {};
  const regimeVerdict = rp.n && rn.n ? (rn.mean > rp.mean ? `<span class="trk-tag good">as modeled</span>` : `<span class="trk-tag bad">not as modeled</span>`) : "";
  $("trkScoreSub").textContent = n ? `${n} session${n === 1 ? "" : "s"} · ${trkM === "ALL" ? "NQ and ES together" : trkM}` : "";
  $("trkScore").innerHTML = n ? `<table class="trk-table"><tr><th>Test</th><th>Result</th><th>Count</th><th>95% range</th><th>What it means</th></tr>
    ${row("Close inside the expected move", S.em_close, "A fair 1σ band holds about 68%. Far above = band too wide; far below = too narrow.")}
    ${row("Whole session inside the band", S.em_range, "Both the high and the low stayed inside the band.")}
    ${row("Broke above the band", S.em_up_break, "The high went past the upper edge.")}
    ${row("Broke below the band", S.em_down_break, "The low went past the lower edge.")}
    <tr><td>Range: positive vs negative gamma</td><td class="m"><b>${rp.mean == null ? "-" : num(rp.mean, 2) + "×"}</b> vs <b>${rn.mean == null ? "-" : num(rn.mean, 2) + "×"}</b></td><td class="m">${rp.n || 0} / ${rn.n || 0}</td><td class="m">-</td>
      <td class="trk-mean">Session range in expected moves. The model says negative gamma runs wider. ${regimeVerdict}</td></tr>
    ${row("Call wall held when touched", S.call_wall.held, `Reached on ${S.call_wall.touched.k} of ${S.call_wall.touched.n} sessions with a wall above.`)}
    ${row("Put wall held when touched", S.put_wall.held, `Reached on ${S.put_wall.touched.k} of ${S.put_wall.touched.n} sessions with a wall below.`)}
    ${row("Traded through zero gamma", S.zg_crossed, "How often the flip level was crossed during the session.")}
    ${row("Bias direction right", S.bias, `Neutral days are not graded. Baseline: always picking the more common direction = ${pct(bi.baseline)}.`)}
    ${row("Base case beat \"no change\"", S.target_beat, "The close was nearer the base-case target than to the price the plan was made at.")}
    ${row("Closed nearer the magnet strike", S.magnet, "Positive gamma only: the close ended nearer the absolute gamma strike than the open.")}
  </table>` : `<div class="expl">Nothing graded yet. The first plan is graded after its session closes.</div>`;
  // every session
  const ss = (trk.sessions || []).filter(s => trkM === "ALL" || s.market === trkM);
  $("trkLogSub").textContent = `${ss.length} session${ss.length === 1 ? "" : "s"} · newest first`;
  const wall = w => !w ? `<span class="dim">-</span>` : !w.touched ? `<span class="dim" title="${num(w.level, 2)}">not reached</span>`
    : w.held ? `<span class="good" title="${num(w.level, 2)}">held</span>` : `<span class="bad" title="${num(w.level, 2)}">broke</span>`;
  const yes = (v, a = "yes", b = "no") => v == null ? `<span class="dim">-</span>` : v ? `<span class="good">${a}</span>` : `<span class="bad">${b}</span>`;
  const rebuilt = s => s.plan && s.plan.frozen_at && Date.parse(s.plan.frozen_at) - Date.parse(s.session + "T13:30:00Z") > 4 * 3600e3;
  $("trkLog").innerHTML = ss.length ? `<table class="trk-table"><tr><th>Session</th><th>Mkt</th><th>Plan</th><th>Ref</th><th>±EM</th><th>Close</th><th>In band</th><th>Call wall</th><th>Put wall</th><th>Bias</th><th></th></tr>${ss.map(s => {
    const p = s.plan, o = s.outcome, day = new Date(s.session + "T12:00:00Z").toLocaleDateString("en-US", {weekday: "short", month: "short", day: "numeric", timeZone: "UTC"});
    if(!p) return `<tr><td>${esc(day)}</td><td>${esc(s.market)}</td><td colspan="9" class="dim">${esc(s.why || s.status)}</td></tr>`;
    const reg = (p.regime || "").toLowerCase(), regCol = p.regime === "POSITIVE" ? "var(--pos)" : p.regime === "NEGATIVE" ? "var(--neg)" : "var(--zg)";
    const tail = s.status === "pending" ? `<span class="trk-tag">waiting for the close</span>` : s.status === "no_prices" ? `<span class="trk-tag bad">no price data</span>` : "";
    const rb = rebuilt(s) ? `<span class="trk-tag" title="Frozen later from saved snapshots; the data is timestamped ${esc(new Date(p.asof).toLocaleString("en-US", {...ET, month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}))} ET, before the open">rebuilt</span>` : "";
    return `<tr><td>${esc(day)}</td><td>${esc(s.market)}</td><td><span style="color:${regCol}">${esc(reg)}</span> · ${esc(p.bias || "-")}</td><td class="m">${num(p.ref, 2)}</td><td class="m">${num(p.em, 0)}</td>
      <td class="m">${o ? `${num(o.close, 2)} <span style="color:${o.move >= 0 ? "var(--good)" : "var(--bad)"}">${signed(o.move_em, 2)}σ</span>` : "-"}</td>
      <td>${o ? yes(o.em_close) : "-"}</td><td>${o ? wall(o.cw) : "-"}</td><td>${o ? wall(o.pw) : "-"}</td><td>${o ? yes(o.bias_hit, "right", "wrong") : "-"}</td><td>${tail}${rb}</td></tr>`;
  }).join("")}</table>` : `<div class="expl">No sessions yet.</div>`;
  renderBacktest();
}
function renderBacktest(){
  const B = (((trk || {}).backtest || {}).markets || {})[btM];
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
  const W = Math.max(wrap.clientWidth, 320), H = 260, pl = 44, pr = 10, pt = 12, pb = 26, lo = 0.4, hi = 1.0;
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
    tip.style.opacity = 1; tip.style.left = Math.min(pl + i * bw + 12, W - 250) + "px"; tip.style.top = "14px";
  };
  svg.onmouseleave = () => { tip.style.opacity = 0; };
  // distribution of moves vs the normal curve
  const hst = B.hist, dw = $("btDistWrap"), ds = $("btDist"), DW = Math.max(dw.clientWidth, 320), DH = 260, nb = hst.counts.length;
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
    dt.style.opacity = 1; dt.style.left = Math.min(bx(i) + 12, DW - 190) + "px"; dt.style.top = "14px";
  };
  ds.onmouseleave = () => { dt.style.opacity = 0; };
  // by vol level
  $("btVolSub").textContent = `${B.vol_index} the evening before, in five equal groups`;
  $("btVol").innerHTML = `<table class="trk-table"><tr><th>${esc(B.vol_index)} level</th><th>Sessions</th><th>Close inside</th><th>Whole range inside</th><th>Broke above</th><th>Broke below</th><th>Avg |move|</th></tr>${B.by_vol.map(r =>
    `<tr><td class="m">${num(r.lo, 1)} to ${num(r.hi, 1)}</td><td class="m">${r.n.toLocaleString("en-US")}</td><td class="m"><b>${pct(r.close_in.rate)}</b></td><td class="m">${pct(r.range_in.rate)}</td><td class="m">${pct(r.up_break.rate)}</td><td class="m">${pct(r.down_break.rate)}</td><td class="m">${num(r.mean_abs_move_em, 2)}σ</td></tr>`).join("")}</table>
    ${B.by_vol.length > 1 && B.by_vol[0].close_in.rate > B.by_vol.at(-1).close_in.rate ? `<div class="expl">When implied vol is low the band is generous; in high-vol regimes realized moves catch up with it and breaks become more common.</div>` : ""}`;
}

// ---------- Strategy lab: futures rules on options data; only rules that pass every test are listed
const FUT = {SPX: "ES", NDX: "NQ"};
function renderStrategies(){
  const L = ((trk || {}).backtest || {}).strategy_lab;
  if(!L || !L.rules){ $("stTitle").textContent = trk && trk.error ? trk.error : "The strategy lab is not built yet"; return; }
  const rules = L.rules, passed = rules.filter(r => r.passed), pv = L.point_value || {SPX: 50, NDX: 20};
  const ym = s => s.slice(0, 7);
  $("stTitle").textContent = `${rules.length} futures strategies tested, ${passed.length} passed`;
  $("stKpis").innerHTML = kpi("Tested", String(rules.length), "rules fixed before testing")
    + kpi("Passed", String(passed.length), passed.length ? "listed below" : "none is shown as a strategy", passed.length ? "var(--good)" : "var(--ink2)")
    + kpi("3-year test", `${ym(L.window[0])} to ${ym(L.window[1])}`, "hourly bars, ES and NQ")
    + kpi("Out of sample", `${L.oos[0].slice(0, 4)} to ${ym(L.oos[1])}`, "swing rules, never used to choose them");
  $("stNote").innerHTML = passed.length
    ? `Only strategies that passed every test are listed as strategies. The research log shows the ones that didn't, and why.`
    : `<b>No strategy has passed every test, so none is listed.</b> Rules built on the expected move and the VIX term structure didn't show an edge after costs that was large and consistent enough on both ES and NQ. A strategy is listed here automatically if it passes, either as the 3-year window rolls forward or once the forward test on GEX PRO's own levels has enough trades. Until then, use the levels as context: the Track record page shows how they've behaved.`;
  // proven strategies
  const r2 = v => v == null ? "-" : signed(v, 3);
  const usd = (s, und) => (s.avg_pts >= 0 ? "+$" : "-$") + num(Math.abs(s.avg_pts * pv[und]), 0);
  const cell = (s, und) => s && s.n ? `<b style="color:${s.avg_pts > 0 ? "var(--good)" : "var(--bad)"}">${usd(s, und)}</b> <span class="dim">/ trade</span><div class="st-kind">${s.n.toLocaleString("en-US")} trades · ${r2(s.avg_r)} R · t ${s.t == null ? "-" : num(s.t, 1)}</div>` : "-";
  $("stProvenSub").textContent = passed.length ? `${passed.length} of ${rules.length}` : "";
  $("stProven").innerHTML = passed.length ? passed.map(r => {
    const a = r.results.SPX, b = r.results.NDX;
    const m = (label, v, sub) => `<div class="metric"><div class="eyebrow">${label}</div><div class="v">${v}</div><div class="s">${sub}</div></div>`;
    return `<div class="st-card"><div class="head"><h2>${esc(r.name)}</h2><span class="trk-tag good">passed</span><span class="sub">${esc(r.kind === "swing" ? `swing, ${r.hold} session${r.hold === 1 ? "" : "s"}` : "intraday")} · uses ${esc(r.uses)}</span></div>
      <div class="st-grid"><div><p class="st-idea">${esc(r.idea)}</p></div>
      <div class="metrics">${[["SPX", a], ["NDX", b]].map(([u, x]) => m(`${FUT[u]} · 3 years`, `${x.window.stats.n} trades · ${pct(x.window.stats.win)}`, `${usd(x.window.stats, u)} per contract per trade, ${r2(x.window.stats.avg_r)} R, t ${num(x.window.stats.t, 1)}`)
        + (x.oos ? m(`${FUT[u]} · out of sample`, `${x.oos.stats.n} trades · ${pct(x.oos.stats.win)}`, `avg ${r2(x.oos.stats.avg_r)} R, t ${num(x.oos.stats.t, 1)}`) : "")).join("")}</div></div></div>`;
  }).join("") : `<div class="st-empty"><b>None yet.</b> Every rule tested so far failed at least one test. The research log below shows each one and why.</div>`;
  // research log
  $("stLogSub").textContent = `every rule tested · average profit per trade after costs, per full-size contract · R = the same in expected moves`;
  $("stLog").innerHTML = `<table class="trk-table"><tr><th>Strategy</th><th>Type</th><th>Options data</th><th>ES · 3 yrs</th><th>NQ · 3 yrs</th><th>ES · out of sample</th><th>NQ · out of sample</th><th>Result</th></tr>${rules.map(r => {
    const a = r.results.SPX, b = r.results.NDX;
    return `<tr><td><b>${esc(r.name)}</b><div class="st-kind">${esc(r.idea)}</div></td><td>${r.kind === "swing" ? `swing · ${r.hold}d` : "intraday"}</td><td>${esc(r.uses)}</td>
      <td class="m">${cell(a.window.stats, "SPX")}</td><td class="m">${cell(b.window.stats, "NDX")}</td>
      <td class="m">${a.oos ? cell(a.oos.stats, "SPX") : `<span class="dim">n/a</span>`}</td><td class="m">${b.oos ? cell(b.oos.stats, "NDX") : `<span class="dim">n/a</span>`}</td>
      <td><span class="trk-tag ${r.passed ? "good" : "bad"}">${r.passed ? "passed" : "failed"}</span><div class="st-kind">${esc(r.why)}</div></td></tr>`; }).join("")}</table>
    <div class="expl">Out-of-sample tests apply to swing rules only, because free hourly history doesn't reach back before ${ym(L.window[0])}.</div>`;
  // forward test on GEX PRO's own levels
  const G = L.gex || {rules: [], sessions: 0};
  $("stGexSub").textContent = `${G.sessions} graded session${G.sessions === 1 ? "" : "s"} with hourly bars so far`;
  $("stGex").innerHTML = `<table class="trk-table"><tr><th>Rule</th><th>GEX PRO levels used</th><th>Trades so far</th><th>Status</th></tr>${G.rules.map(r =>
    `<tr><td><b>${esc(r.name)}</b><div class="st-kind">${esc(r.doc)}</div></td><td>${esc(r.uses)}</td><td class="m">${r.stats.n || 0}</td>
     <td><span class="trk-tag ${r.passed ? "good" : ""}">${r.passed ? "passed" : "not proven"}</span><div class="st-kind">${esc(r.why)}</div></td></tr>`).join("")}</table>
    <div class="expl">These rules need the real gamma levels, which exist only from the first saved session on, so they can only be tested going forward. Results are hidden until a rule has 30 trades: with fewer, a profit or a loss says nothing. A rule that then passes the same bar moves up to Proven strategies.</div>`;
}

setPage(page);
load();
loadNews();
loadPosts();
setInterval(load, STATIC ? 60000 : 20000);
setInterval(loadPosts, 2 * 60 * 1000);                     // the service itself re-fetches at most every 5 min
setInterval(loadNews, 10 * 60 * 1000);                      // the service itself re-fetches at most every 30 min
setInterval(() => { if(page === "news") renderNews(); }, 60000);   // keep countdowns current
setInterval(() => { if(page === "briefings") loadBriefings(); }, STATIC ? 5 * 60 * 1000 : 60000);
setInterval(() => { if(page === "indicator") loadIndicator(); }, STATIC ? 5 * 60 * 1000 : 15000);   // pick up code edits
window.addEventListener("resize", () => { if(data) render(); if(page === "timeline") renderTimeline(); if(page === "track") renderTrack(); if(page === "strategies") renderStrategies(); });
setInterval(() => { if(page === "track" || page === "strategies") loadTrack(); }, 5 * 60 * 1000);
setInterval(() => { if(page === "timeline") loadTimeline(); }, STATIC ? 5 * 60 * 1000 : 60000);
