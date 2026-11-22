// Garde l'application disponible hors connexion. Les donnees du jour sont gerees par la page.
const VERSION = "brvm-v7";
const COQUILLE = ["./", "index.html", "app.js", "manifest.json", "icone-192.png", "icone-512.png", "celebration_fin.jpg"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(VERSION).then((c) => c.addAll(COQUILLE))); self.skipWaiting(); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== VERSION).map((k) => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.includes("/data/")) return;
  // reseau d'abord (pour recevoir les nouvelles versions), copie en cache si pas de reseau
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok) { const copie = r.clone(); caches.open(VERSION).then((c) => c.put(e.request, copie)); }
    return r;
  }).catch(() => caches.match(e.request).then((r) => r || caches.match("index.html"))));
});
