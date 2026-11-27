// GEX PRO v2: the Levels numbers, built only from the definitions table (docs/v2-definitions.md). Pure: no DOM,
// no fetch, so node can test it. Every number carries its as-of time or a "missing" text that says why.
(function(root){
"use strict";
const STATIC = !!(root && root.GEX_STATIC);
const URLS = {
  all: STATIC ? "../data/all.json" : "/api/all",
  paste: STATIC ? "../data/pine-published.txt" : "/api/pine/all?which=published",
  stamp: STATIC ? "../data/stamp.txt" : null,
};
const val = o => o && typeof o === "object" ? o.price : o;
const fin = x => typeof x === "number" && isFinite(x);
const LEVELS = [            // [key, name, colour token: the Pine input.color defaults and their themed() light shades]
  ["CW", "Call wall", "pos"], ["C1", "C1", "pos"], ["Ab1", "Ab1", "ag"], ["ZG", "Zero gamma", "zg"],
  ["P1", "P1", "neg"], ["PW", "Put wall", "neg"],
];

// "YYYY-MM-DD HH:MM" in New York time, the format of the engine's next_publish_et
function etStamp(ms){
  const p = {};
  for(const x of new Intl.DateTimeFormat("en-US", {timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23"}).formatToParts(ms)) p[x.type] = x.value;
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;
}

function worker(all, market){
  return ((all && all.workers) || []).find(w => w.market === market) || null;
}

// one Levels reading for a market: the rows of the definitions table, each {v, at} or {missing}
function levelsModel(all, market, nowMs){
  const w = worker(all, market);
  if(!w || !w.result) return {market, missing: `no reading for ${market} in this update`};
  const r = w.result, m = r.mapped || null, s = r.summary || {}, mp = (m && m.mapping) || {};
  const lv = (r.session && r.session.levels) || {};
  const asof = (m || s).asof || null;
  const out = {market, asof, built: all.now || null};
  const no = why => ({missing: why});
  // 1 price (futures points)
  out.price = !m ? no(r.mapping_note || s.mapping_note || "no futures mapping in this reading")
    : fin(mp.futures_ref) ? {v: mp.futures_ref, at: mp.futures_time || s.ref_time} : no("no futures quote");
  // a price from an earlier New York day than now is shown with its date and flagged, never as today's
  if(fin(out.price.v)) out.price.notToday = !out.price.at || !fin(nowMs)
    || etStamp(Date.parse(out.price.at)).slice(0, 10) !== etStamp(nowMs).slice(0, 10);
  // 3 zero gamma, 4-5 walls, 7-9 C1 P1 Ab1
  const lvl = {
    ZG: m && fin(val(m.zero_gamma)) ? {v: val(m.zero_gamma), modelled: m.zero_gamma_status === "ESTIMATE"} : no("no zero gamma in this reading"),
    CW: m && fin(val(m.call_wall)) ? {v: val(m.call_wall)} : no("unavailable"),
    PW: m && fin(val(m.put_wall)) ? {v: val(m.put_wall)} : no("unavailable"),
    C1: fin(lv.C1) ? {v: lv.C1} : no("not in this reading"),
    P1: fin(lv.P1) ? {v: lv.P1} : no("not in this reading"),
    Ab1: m && fin(val(m.abs_gamma)) ? {v: val(m.abs_gamma)} : no("not in this reading"),
  };
  out.levels = lvl;
  const P = out.price.v;
  // 2 distance to zero gamma: unsigned, with the side in words
  out.zgDistance = !fin(P) ? no(out.price.missing) : lvl.ZG.missing ? no(lvl.ZG.missing)
    : {v: Math.abs(P - lvl.ZG.v), side: P >= lvl.ZG.v ? "above" : "below"};
  // 6 nearer wall
  const walls = [["Call wall", lvl.CW], ["Put wall", lvl.PW]].filter(([, x]) => fin(x.v));
  if(!fin(P)) out.nearerWall = no(out.price.missing);
  else if(!walls.length) out.nearerWall = no("unavailable: no wall in this reading");
  else {
    const [name, x] = walls.sort((a, b) => Math.abs(a[1].v - P) - Math.abs(b[1].v - P))[0];
    out.nearerWall = {name, v: x.v, d: Math.abs(x.v - P), side: x.v >= P ? "above" : "below", only: walls.length === 1};
  }
  // 10 regime
  out.regime = m && m.regime ? {v: m.regime} : no("unavailable");
  // 12 minutes since the levels
  out.ageMin = asof && fin(nowMs) ? Math.max(0, Math.round((nowMs - Date.parse(asof)) / 60000)) : null;
  // 13 the 1-sigma move to the nearest expiry, around price
  const em = (m && m.expected_move) || {};
  out.sigma = fin(P) && fin(em.one_sigma_points_fut) ? {v: em.one_sigma_points_fut, exp: em.expiration || null,
    hi: P + em.one_sigma_points_fut, lo: P - em.one_sigma_points_fut} : no("1σ move unavailable");
  // 14-15 the source and whether it is the backup estimate
  out.source = {provider: (m || s).provider || w.provider || null, kind: (m || s).source || null,
    backup: !!((m || s).backup) || ((m || s).provider && (m || s).provider !== "CBOE"),
    note: (m || s).backup || null, warnings: (m || s).warnings || []};
  // 16-19 the paste
  const pub = w.published || null, h = w.health || {};
  out.paste = !pub ? no("No paste published yet") : {
    at: pub.published_at, slot: pub.slot_et, zg: fin(pub.zero_gamma) ? pub.zero_gamma : null, provider: pub.provider,
    ageMin: fin(nowMs) && pub.published_at ? Math.max(0, Math.round((nowMs - Date.parse(pub.published_at)) / 60000)) : null,
    onHold: out.source.backup,                     // backup estimates are not pasted: the last Cboe slot stays
    // a next-attempt time already past is old news, never shown as upcoming
    next: h.next_publish_et && (!fin(nowMs) || h.next_publish_et > etStamp(nowMs)) ? h.next_publish_et : null};
  // the ladder: every level and the 1-sigma rows, high to low, with the price row placed by value
  const rows = LEVELS.filter(([k]) => fin(lvl[k].v)).map(([k, name, tone]) => ({k, name, tone, v: lvl[k].v}));
  if(fin(out.sigma.v)) rows.push({k: "SH", name: "1σ high", tone: "em", v: out.sigma.hi}, {k: "SL", name: "1σ low", tone: "em", v: out.sigma.lo});
  rows.sort((a, b) => b.v - a.v);
  out.ladder = rows;
  out.notCovered = LEVELS.filter(([k]) => !fin(lvl[k].v)).map(([k, name]) => ({k, name, why: lvl[k].missing}));
  return out;
}

// "N d N h" / "N h N min" / "N min": an age in plain words, never rounded up a unit
function age(min){
  if(!fin(min)) return "";
  if(min >= 1440) return `${Math.floor(min / 1440)} d ${Math.floor(min % 1440 / 60)} h`;
  if(min >= 60) return `${Math.floor(min / 60)} h ${min % 60} min`;
  return `${min} min`;
}

const api = {URLS, LEVELS, worker, levelsModel, age, etStamp};
if(typeof module !== "undefined" && module.exports) module.exports = api;
else root.GEX2 = api;
})(typeof window !== "undefined" ? window : globalThis);
