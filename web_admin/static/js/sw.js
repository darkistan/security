// Service Worker для Системи ведення змін охоронців PWA
const CACHE_NAME = 'shifts-guards-v1';
const SW_VERSION = '1.0.0';

// Подія install - виконується при встановленні service worker
self.addEventListener('install', function(event) {
    console.log('[Service Worker] Installing service worker version', SW_VERSION);
    self.skipWaiting();
});

// Подія activate - виконується при активації service worker
self.addEventListener('activate', function(event) {
    console.log('[Service Worker] Activating service worker version', SW_VERSION);
    event.waitUntil(clients.claim());
});

// Обробка повідомлень від клієнта
self.addEventListener('message', function(event) {
    console.log('[Service Worker] Received message:', event.data);
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});
