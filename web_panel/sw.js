// PulseDeck Panel service worker: only for notifications (no caching — the page always comes from the PC).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
    for (const client of windows) if ('focus' in client) return client.focus();
    return self.clients.openWindow('./');
  }));
});
