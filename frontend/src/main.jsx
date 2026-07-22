import React, { lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { AuthGate } from './auth/AuthGate.jsx'
import { AuthProvider } from './auth/AuthProvider.jsx'
import './styles.css'

const MODULE_RETRY_KEY = 'sh_app_module_retry_v385'
const RETRY_WINDOW_MS = 60_000

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
  })
}
