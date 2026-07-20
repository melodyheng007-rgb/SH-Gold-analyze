import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, errorInfo) {
    if (import.meta.env.DEV) {
      console.group('SH Market Analyzer Render Error')
      console.error(error)
      console.log(errorInfo)
      console.groupEnd()
    }
  }

  resetApp = () => {
    try {
      localStorage.clear()
    } catch (_) {
      // Reload remains available when browser storage is restricted.
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
            <button onClick={this.resetApp}>Reset app</button>
          </div>
        </section>
      </main>
    )
  }
}
