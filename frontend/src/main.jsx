import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { AuthGate } from './auth/AuthGate.jsx'
import { AuthProvider } from './auth/AuthProvider.jsx'
import './styles.css'

const rootElement = document.getElementById('root')

if (!rootElement) {
  document.body.innerHTML = '<main class="fatal-error-screen"><section><strong>Unable to open the app</strong><p>Please refresh and try again.</p></section></main>'
} else {
  createRoot(rootElement).render(
    <ErrorBoundary>
      <AuthProvider>
        <AuthGate>
          <App />
        </AuthGate>
      </AuthProvider>
    </ErrorBoundary>
  )
}
