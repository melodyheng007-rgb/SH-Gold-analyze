import { API_BASE_URL } from '../config/api.js'

export const CLIENT_BUILD_ID = '3.8.7.0'

export function reportClientError(scope, error) {
  const message = String(error?.message || error || 'Unknown client error').slice(0, 300)
  const payload = JSON.stringify({
    scope: String(scope || 'unknown').slice(0, 40),
    message,
    build_id: CLIENT_BUILD_ID,
    path: String(window.location.pathname || '/').slice(0, 160),
  })

  try {
    fetch(`${API_BASE_URL}/api/client-errors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload,
      keepalive: true,
    }).catch(() => undefined)
  } catch (_) {
    // Diagnostics must never cause another application error.
  }
}
