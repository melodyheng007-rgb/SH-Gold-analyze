import { API_BASE_URL, API_FALLBACK_BASE_URL } from '../config/api.js'

const DEFAULT_TIMEOUT_MS = 8000
let apiAccessToken = ''

export function setApiAccessToken(value) {
  apiAccessToken = String(value || '')
}

function buildUrl(path, query = {}, baseUrl = API_BASE_URL) {
  const url = new URL(path, baseUrl)
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
  const requestHeaders = {
    ...headers,
    ...(apiAccessToken && !headers.Authorization ? { Authorization: `Bearer ${apiAccessToken}` } : {}),
  }
  let response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      body,
      headers: requestHeaders,
      signal: controller.signal,
    })
  } catch (err) {
    clearTimeout(timeout)
    if (API_FALLBACK_BASE_URL && err.name !== 'AbortError') {
      try {
        response = await fetch(buildUrl(path, query, API_FALLBACK_BASE_URL), {
          method,
          body,
          headers: requestHeaders,
          signal: AbortSignal.timeout(timeoutMs),
        })
      } catch (_) {
        throw apiError('Market service is temporarily unavailable.', {
          code: 'BACKEND_OFFLINE',
          status: 0,
          apiBaseUrl: `${API_BASE_URL} / ${API_FALLBACK_BASE_URL}`,
        })
      }
    } else if (err.name === 'AbortError') {
      throw apiError('The market service took too long to respond.', {
        code: 'TIMEOUT',
        status: 0,
        apiBaseUrl: API_BASE_URL,
      })
    } else {
      throw apiError('Market service is temporarily unavailable.', {
        code: 'BACKEND_OFFLINE',
        status: 0,
        apiBaseUrl: API_BASE_URL,
      })
    }
  }
  clearTimeout(timeout)

  let data
  try {
    data = await response.json()
  } catch (err) {
    throw apiError('The market service returned an unexpected response.', {
      code: 'INVALID_JSON',
      status: response.status,
      apiBaseUrl: API_BASE_URL,
    })
  }

  if (!response.ok) {
    const message = response.status === 401
      ? 'Your session has expired. Please sign in again.'
      : response.status === 403
        ? 'You do not have access to this action.'
        : response.status === 404
          ? 'This feature is temporarily unavailable.'
          : response.status >= 500
            ? 'Market service is temporarily unavailable.'
            : data.error || data.message || 'The request could not be completed.'
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
