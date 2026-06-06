// Minimal service worker — required for Android to treat the site as an
// installable PWA and use the manifest icon on the home screen.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
