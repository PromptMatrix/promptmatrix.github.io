const CACHE_NAME = 'promptmatrix-v1';
const ASSETS = [
    '/dashboard',
    '/manifest.json',
    'https://cdn.jsdelivr.net/npm/inter-ui@3.19.3/inter.css',
    'https://cdn.jsdelivr.net/npm/lucide@0.344.0/dist/umd/lucide.min.js'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS);
        })
    );
});

self.addEventListener('fetch', (event) => {
    // Basic network-first strategy for dynamic content
    event.respondWith(
        fetch(event.request).catch(() => {
            return caches.match(event.request);
        })
    );
});
