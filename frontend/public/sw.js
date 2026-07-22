const WORKER_BUILD_ID = '3.8.6.1'
let replacingExistingWorker = false

self.addEventListener('install', event => {
  replacingExistingWorker = Boolean(self.registration.active)
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const cacheNames = await self.caches.keys()
    await Promise.all(cacheNames.map(name => self.caches.delete(name)))
    await self.clients.claim()

    if (!replacingExistingWorker) return
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    await Promise.all(windows.map(async client => {
      try {
        const url = new URL(client.url)
        url.searchParams.set('app_update', WORKER_BUILD_ID)
        await client.navigate(url.href)
      } catch (_) {
        client.postMessage({ type: 'SH_APP_UPDATE', buildId: WORKER_BUILD_ID })
      }
    }))
  })())
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
