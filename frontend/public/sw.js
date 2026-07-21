self.addEventListener('install', () => self.skipWaiting())

self.addEventListener('activate', event => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('push', event => {
  const payload = event.data?.json?.() || {}
  event.waitUntil(self.registration.showNotification(payload.title || 'SH Diamond Update', {
    body: payload.body || 'A completed-candle Diamond update is ready.',
    icon: '/favicon.svg',
    badge: '/favicon.svg',
    data: { url: payload.url || '/' },
    tag: payload.tag || 'sh-diamond-update',
  }))
})

self.addEventListener('notificationclick', event => {
  event.notification.close()
  event.waitUntil(self.clients.openWindow(event.notification.data?.url || '/'))
})
