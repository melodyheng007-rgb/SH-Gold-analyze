import React, { lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { AuthGate } from './auth/AuthGate.jsx'
import { AuthProvider } from './auth/AuthProvider.jsx'
import './styles.css'

const App = lazy(() => import('./App.jsx'))

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
    navigator.serviceWorker.register('/sw.js').catch(() => undefined)
  })
}
