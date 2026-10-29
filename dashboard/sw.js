// GEX PRO service worker: makes the site installable as an app. Network first for everything, so prices and
// levels are always fresh; the last copy of the page and its files is kept only for when there is no
// connection at all.
const CACHE = "gexpro-v1";
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if(req.method !== "GET" || url.origin !== location.origin) return;          // other sites: untouched
  e.respondWith(fetch(req).then(res => {
    const live = /\/(api|data)\//.test(url.pathname);                          // live data is never stored
    if(res.ok && !live){ const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
    return res;
  }).catch(() => caches.match(req, {ignoreSearch: true})));
});
