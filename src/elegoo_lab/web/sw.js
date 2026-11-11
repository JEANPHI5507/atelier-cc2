// Atelier CC2 service worker: the app shell loads instantly and says so clearly when the PC is off.
// Printer data and the workshop API are never cached: they must always be live.
const SHELL = 'cc2-shell-v1';
const STATIC = ['/lab/', '/lab/offline.html', '/lab/vendor/three.module.js', '/lab/icons/icon-192.png', '/lab/manifest.webmanifest'];

self.addEventListener('install', e => { e.waitUntil(caches.open(SHELL).then(c => c.addAll(STATIC)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== SHELL).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || !url.pathname.startsWith('/lab/') || url.pathname.startsWith('/lab/api/')) return;
  if (e.request.mode === 'navigate') {            // pages: always fresh, cached copy only to explain an outage
    e.respondWith(fetch(e.request).then(r => {
      if (r.ok && !r.redirected) caches.open(SHELL).then(c => c.put(e.request, r.clone()));
      return r;
    }).catch(() => caches.match('/lab/offline.html')));
    return;
  }
  if (url.pathname.startsWith('/lab/vendor/') || url.pathname.startsWith('/lab/icons/')) {   // big, rarely changing
    e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request).then(r => {
      if (r.ok) caches.open(SHELL).then(c => c.put(e.request, r.clone()));
      return r;
    })));
  }
});
