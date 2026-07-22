import React, { lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { AuthGate } from './auth/AuthGate.jsx'
import { AuthProvider } from './auth/AuthProvider.jsx'
import { CLIENT_BUILD_ID, reportClientError } from './utils/clientDiagnostics.js'
import './styles.css'
import './styles-modern-2026.css'

const MODULE_RETRY_KEY = 'sh_app_module_retry_v385'
const RETRY_WINDOW_MS = 60_000
const BUILD_REFRESH_KEY = 'sh_client_build_refresh'

function isModuleLoadError(error) {
  return /chunkloaderror|loading chunk|failed to fetch dynamically imported module|importing a module script failed/i
    .test(String(error?.name || '') + String(error?.message || error || ''))
}

function readModuleRetry() {
  try {
    return Number(sessionStorage.getItem(MODULE_RETRY_KEY) || 0)
  } catch (_) {
    return 0
  }
}

function writeModuleRetry(value) {
  try {
    if (value) sessionStorage.setItem(MODULE_RETRY_KEY, String(value))
    else sessionStorage.removeItem(MODULE_RETRY_KEY)
  } catch (_) {
    // Module loading still works when private browsing restricts storage.
  }
}

async function loadApp() {
  try {
    const module = await import('./App.jsx')
    writeModuleRetry(0)
    return module
  } catch (error) {
    const previousRetry = readModuleRetry()
    if (isModuleLoadError(error) && (!previousRetry || Date.now() - previousRetry > RETRY_WINDOW_MS)) {
      writeModuleRetry(Date.now())
      window.location.reload()
      return new Promise(() => {})
    }
    throw error
  }
}

async function clearBrowserCaches() {
  try {
    if ('caches' in window) {
      const names = await window.caches.keys()
      await Promise.all(names.map(name => window.caches.delete(name)))
    }
  } catch (_) {
    // Cache storage may be unavailable in private browsing.
  }
}

async function verifyClientBuild() {
  try {
    const response = await fetch(`/app-version.json?check=${Date.now()}`, { cache: 'no-store' })
    if (!response.ok) return
    const current = await response.json()
    if (!current?.build_id || current.build_id === CLIENT_BUILD_ID) {
      sessionStorage.removeItem(BUILD_REFRESH_KEY)
      return
    }

    const previousRefresh = Number(sessionStorage.getItem(BUILD_REFRESH_KEY) || 0)
    if (previousRefresh && Date.now() - previousRefresh < RETRY_WINDOW_MS) return
    sessionStorage.setItem(BUILD_REFRESH_KEY, String(Date.now()))
    await clearBrowserCaches()
    const registrations = await navigator.serviceWorker?.getRegistrations?.() || []
    await Promise.all(registrations.map(registration => registration.update().catch(() => undefined)))
    const nextUrl = new URL(window.location.href)
    nextUrl.searchParams.set('app_update', current.build_id)
    window.location.replace(nextUrl.href)
  } catch (error) {
    reportClientError('build_check', error)
  }
}

const App = lazy(loadApp)

const rootElement = document.getElementById('root')

if (!rootElement) {
  document.body.innerHTML = '<main class="fatal-error-screen"><section><strong>Unable to open the app</strong><p>Please refresh and try again.</p></section></main>'
} else {
  createRoot(rootElement).render(
    <ErrorBoundary>
      <AuthProvider>
        <AuthGate>
          <Suspense fallback={<main className="auth-loading-screen"><strong>Opening market workspace</strong><span /></main>}>
            <App />
          </Suspense>
        </AuthGate>
      </AuthProvider>
    </ErrorBoundary>
  )
}

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' })
      .then(registration => registration.update())
      .catch(() => undefined)
    verifyClientBuild()
  })
  navigator.serviceWorker.addEventListener('message', event => {
    if (event.data?.type !== 'SH_APP_UPDATE') return
    clearBrowserCaches().finally(() => window.location.reload())
  })
  window.setInterval(verifyClientBuild, 120_000)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') verifyClientBuild()
  })
}
