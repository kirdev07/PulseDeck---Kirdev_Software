// PulseDeck Panel service worker: notifications only (no caching — the page always comes from the PC).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

// Web Push from the PC (pulse_pc/services/web_panel/push.py): arrives even when the panel is closed.
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || 'PulseDeck', {
    body: data.body || '', tag: `pulsedeck-${data.tag || 'notice'}`, icon: 'icon.png', badge: 'icon.png', renotify: true,
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
    for (const client of windows) if ('focus' in client) return client.focus();
    return self.clients.openWindow('./');
  }));
});
