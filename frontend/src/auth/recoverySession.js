export const RECOVERY_SESSION_MISSING = 'PASSWORD_RECOVERY_SESSION_MISSING'
export const RECOVERY_LINK_INVALID = 'PASSWORD_RECOVERY_LINK_INVALID'

function codedError(code, message) {
  const error = new Error(message || code)
  error.code = code
  return error
}

export function readRecoveryUrl(href = '') {
  if (!href) return { requested: false }

  const url = new URL(href)
  const query = url.searchParams
  const hash = new URLSearchParams(url.hash.replace(/^#/, ''))
  const errorCode = hash.get('error_code') || query.get('error_code') || ''
  const errorDescription = hash.get('error_description') || query.get('error_description') || ''

  return {
    requested: query.get('recovery') === '1'
      || query.get('type') === 'recovery'
      || hash.get('type') === 'recovery'
      || Boolean(errorCode),
    code: query.get('code') || '',
    accessToken: hash.get('access_token') || '',
    refreshToken: hash.get('refresh_token') || '',
    errorCode,
    errorDescription: errorDescription.replace(/\+/g, ' '),
  }
}

export async function ensureRecoverySession(client, href = '') {
  if (!client?.auth) throw codedError(RECOVERY_SESSION_MISSING)

  const callback = readRecoveryUrl(href)
  if (callback.errorCode) {
    throw codedError(
      RECOVERY_LINK_INVALID,
      callback.errorDescription || 'The recovery link is invalid or expired.',
    )
  }

  const current = await client.auth.getSession()
  if (current.error) throw current.error
  if (current.data?.session) return current.data.session

  if (callback.code) {
    const exchanged = await client.auth.exchangeCodeForSession(callback.code)
    if (exchanged.error) throw exchanged.error
    if (exchanged.data?.session) return exchanged.data.session
  }

  if (callback.accessToken && callback.refreshToken) {
    const restored = await client.auth.setSession({
      access_token: callback.accessToken,
      refresh_token: callback.refreshToken,
    })
    if (restored.error) throw restored.error
    if (restored.data?.session) return restored.data.session
  }

  throw codedError(
    RECOVERY_SESSION_MISSING,
    'The recovery session is missing or has expired.',
  )
}

export function clearRecoveryUrl() {
  if (typeof window === 'undefined') return
  window.history.replaceState({}, document.title, window.location.pathname)
}
