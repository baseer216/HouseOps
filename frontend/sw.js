const CACHE_NAME = 'houseops-v3';
const STATIC_ASSETS = [
  '/',
  '/network',
  '/switches',
  '/manifest.json',
  '/sw.js'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  if (e.request.url.includes('/api/')) {
    e.respondWith(fetch(e.request).then(resp => {
      if (resp.status === 200) {
        const clone = resp.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
      }
      return resp;
    }).catch(() => caches.match(e.request).then(r => r || new Response(JSON.stringify({}), { headers: { 'Content-Type': 'application/json' } }))));
    return;
  }
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).then(resp => {
    if (resp.status === 200) {
      const clone = resp.clone();
      caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
    }
    return resp;
  }).catch(() => {
    if (e.request.headers.get('accept').includes('text/html')) return caches.match('/');
    return caches.match(e.request);
  })));
});
