// App-shell cache so the UI opens instantly and works offline. API calls are never cached (always network).
const V = 'hb-v2', SHELL = ['/', '/static/css/app.css', '/static/js/app.js', '/static/js/api.js', '/static/js/i18n.js', '/static/js/recorder.js', '/manifest.webmanifest', '/static/icons/icon-192.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.pathname.startsWith('/api/') || u.origin !== location.origin) return;
  e.respondWith(fetch(e.request).then(r => { const c = r.clone(); caches.open(V).then(x => x.put(e.request, c)); return r; }).catch(() => caches.match(e.request).then(m => m || caches.match('/'))));
});
