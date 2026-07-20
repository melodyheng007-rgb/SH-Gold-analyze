function lanApiBaseUrl() {
  if (typeof window === 'undefined') return null
  const { protocol, hostname } = window.location
  const localHostnames = new Set(['localhost', '127.0.0.1', '0.0.0.0'])
  if (localHostnames.has(hostname)) return null
  return `${protocol}//${hostname}:8001`
}

const detectedLanApiUrl = lanApiBaseUrl()

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || detectedLanApiUrl || 'http://127.0.0.1:8001'

export const API_FALLBACK_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || !detectedLanApiUrl ? null : 'http://127.0.0.1:8001'
