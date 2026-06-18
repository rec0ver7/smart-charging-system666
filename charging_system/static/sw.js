// 智能充电桩调度系统 — Service Worker (PWA)
const CACHE_NAME = 'charging-v1';
const URLS_TO_CACHE = [
    '/',
    '/dashboard/',
    '/static/manifest.json',
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(URLS_TO_CACHE))
    );
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', event => {
    // API 请求走网络，不缓存
    if (event.request.url.includes('/api/')) {
        return;
    }
    event.respondWith(
        caches.match(event.request).then(cached =>
            cached || fetch(event.request)
        )
    );
});
