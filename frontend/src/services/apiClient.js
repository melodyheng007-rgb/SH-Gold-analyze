import { API_BASE_URL } from '../config/api.js'

const DEFAULT_TIMEOUT_MS = 8000

function buildUrl(path, query = {}) {
  const url = new URL(path, API_BASE_URL)
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, value)
    }
  })
  return url.toString()
}

function apiError(message, details = {}) {
  const error = new Error(message)
  Object.assign(error, details)
  return error
}

export async function apiRequest(path, options = {}) {
  const {
    method = 'GET',
    query,
    body,
    headers = {},
    timeoutMs = DEFAULT_TIMEOUT_MS,
  } = options
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  let response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      body,
      headers,
      signal: controller.signal,
    })
  } catch (err) {
    clearTimeout(timeout)
    if (err.name === 'AbortError') {
      throw apiError('Backend request timed out. Please check the API server.', {
        code: 'TIMEOUT',
        status: 0,
        apiBaseUrl: API_BASE_URL,
      })
    }
    throw apiError('Backend server is not running. Please start backend on port 8001.', {
      code: 'BACKEND_OFFLINE',
      status: 0,
      apiBaseUrl: API_BASE_URL,
    })
  }
  clearTimeout(timeout)

  let data
  try {
    data = await response.json()
  } catch (err) {
    throw apiError('Backend returned invalid JSON. Please check backend logs.', {
      code: 'INVALID_JSON',
      status: response.status,
      apiBaseUrl: API_BASE_URL,
    })
  }

  if (!response.ok) {
    const message = response.status === 404
      ? 'API route not found. Frontend and backend route names may not match.'
      : data.error || data.message || `API error: ${response.status}`
    throw apiError(message, {
      code: response.status === 404 ? 'ROUTE_NOT_FOUND' : 'API_ERROR',
      status: response.status,
      payload: data,
      apiBaseUrl: API_BASE_URL,
    })
  }

  return data
}

export { API_BASE_URL }
