import React from 'react'

const ROOT_RECOVERY_KEY = 'sh_root_recovery_attempt'
const ROOT_RECOVERY_WINDOW_MS = 60_000

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
    this.recoveryTimer = null
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('SH Market Analyzer recovered from an application error.', error, errorInfo)
    try {
      sessionStorage.setItem('sh_last_app_error', JSON.stringify({
        at: new Date().toISOString(),
        message: String(error?.message || 'Unknown application error').slice(0, 240),
      }))
    } catch (_) {
      // The recovery screen remains available when storage is restricted.
    }
    try {
      const previousAttempt = Number(sessionStorage.getItem(ROOT_RECOVERY_KEY) || 0)
      if (navigator.onLine !== false && (!previousAttempt || Date.now() - previousAttempt > ROOT_RECOVERY_WINDOW_MS)) {
        sessionStorage.setItem(ROOT_RECOVERY_KEY, String(Date.now()))
        this.recoveryTimer = window.setTimeout(() => window.location.reload(), 500)
      }
    } catch (_) {
      // Manual recovery remains available when session storage is restricted.
    }
  }

  componentWillUnmount() {
    if (this.recoveryTimer) window.clearTimeout(this.recoveryTimer)
  }

  resetWorkspace = async () => {
    try {
      Object.keys(localStorage)
        .filter(key => /^sh[_-]/i.test(key))
        .forEach(key => localStorage.removeItem(key))
    } catch (_) {
      // Reload remains available when browser storage is restricted.
    }
    try {
      if ('caches' in window) {
        const names = await window.caches.keys()
        await Promise.all(names.map(name => window.caches.delete(name)))
      }
    } catch (_) {
      // Cached files are optional; account storage is deliberately preserved.
    }
    window.location.reload()
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <main className="fatal-error-screen">
        <section>
          <strong>Something went wrong</strong>
          <p>The workspace could not be opened. Please refresh and try again.</p>
          <div className="fatal-error-actions">
            <button onClick={() => window.location.reload()}>Try again</button>
            <button onClick={this.resetWorkspace}>Reset workspace</button>
          </div>
        </section>
      </main>
    )
  }
}
