import React from 'react'
import { BarChart3, RefreshCw } from 'lucide-react'
import { reportClientError } from '../utils/clientDiagnostics.js'

export default class WorkspaceErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null, retries: 0 }
    this.retryTimer = null
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('Market chart recovered from an error.', error, errorInfo)
    reportClientError('signal_chart', error)
    if (this.state.retries < 1) {
      this.retryTimer = window.setTimeout(this.retry, 700)
    }
  }

  componentDidUpdate(previousProps) {
    if (this.state.error && previousProps.resetToken !== this.props.resetToken) {
      this.retry()
    }
  }

  componentWillUnmount() {
    if (this.retryTimer) window.clearTimeout(this.retryTimer)
  }

  retry = () => {
    if (this.retryTimer) window.clearTimeout(this.retryTimer)
    this.retryTimer = null
    this.setState(state => ({ error: null, retries: state.retries + 1 }))
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <section className="workspace-chart-recovery" role="alert">
        <BarChart3 size={24} />
        <strong>Reconnecting chart</strong>
        <p>Live analysis is still available while the chart refreshes.</p>
        <button type="button" onClick={this.retry}>
          <RefreshCw size={15} />
          Retry chart
        </button>
      </section>
    )
  }
}
