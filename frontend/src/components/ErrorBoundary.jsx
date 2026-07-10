import React from 'react'
import { API_BASE_URL } from '../config/api.js'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null, errorInfo: null, debugOpen: false }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo })
    if (import.meta.env.DEV) {
      console.group('SH Gold Analyzer Render Error')
      console.error(error)
      console.log(errorInfo)
      console.groupEnd()
    }
  }

  clearLocalStorage = () => {
    try {
      localStorage.clear()
    } catch (_) {
      // The visible error screen is still usable if storage is blocked.
    }
    window.location.reload()
  }

  render() {
    if (!this.state.error) return this.props.children
    const stack = this.state.errorInfo?.componentStack || ''
    return (
      <main className="fatal-error-screen">
        <section>
          <strong>Frontend Render Error</strong>
          <p>{this.state.error.message || String(this.state.error)}</p>
          {stack && <pre>{stack}</pre>}
          <div className="fatal-error-actions">
            <button onClick={() => window.location.reload()}>Reload App</button>
            <button onClick={this.clearLocalStorage}>Clear Local Storage</button>
            <button onClick={() => this.setState(state => ({ debugOpen: !state.debugOpen }))}>Open Debug Mode</button>
          </div>
          {this.state.debugOpen && (
            <div className="fatal-debug-panel">
              <span>API Base URL <strong>{API_BASE_URL}</strong></span>
              <span>Current Route <strong>{window.location.href}</strong></span>
              <span>App Version <strong>V1.8.3</strong></span>
              <span>Console Hint <strong>Open browser DevTools Console for full stack trace.</strong></span>
            </div>
          )}
        </section>
      </main>
    )
  }
}
