import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import './styles.css'

const rootElement = document.getElementById('root')

if (!rootElement) {
  document.body.innerHTML = '<main class="fatal-error-screen"><section><strong>Frontend Render Error</strong><p>Root element #root was not found.</p></section></main>'
} else {
  createRoot(rootElement).render(
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  )
}
