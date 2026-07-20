import { createClient } from '@supabase/supabase-js'
import { createAuthFetch } from './authRequest.js'

const authFetch = createAuthFetch()

const supabaseUrl = String(import.meta.env.VITE_SUPABASE_URL || '').trim().replace(/\/$/, '')
const supabasePublishableKey = String(
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY
    || import.meta.env.VITE_SUPABASE_ANON_KEY
    || '',
).trim()

export const authConfigured = Boolean(supabaseUrl && supabasePublishableKey)
export const authRequired = import.meta.env.VITE_AUTH_REQUIRED !== 'false'

export const supabase = authConfigured
  ? createClient(supabaseUrl, supabasePublishableKey, {
      auth: {
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: true,
        flowType: 'pkce',
      },
      global: {
        fetch: authFetch,
      },
    })
  : null

export async function requireAuthProvider(provider) {
  if (!authConfigured) {
    const error = new Error('ACCOUNT_CONFIGURATION_INVALID')
    error.code = 'ACCOUNT_CONFIGURATION_INVALID'
    throw error
  }

  const response = await authFetch(`${supabaseUrl}/auth/v1/settings`, {
    headers: { apikey: supabasePublishableKey },
  })
  if (!response.ok) {
    const error = new Error('ACCOUNT_CONFIGURATION_INVALID')
    error.code = 'ACCOUNT_CONFIGURATION_INVALID'
    throw error
  }

  const settings = await response.json()
  if (!settings?.external?.[provider]) {
    const error = new Error(`${String(provider).toUpperCase()}_PROVIDER_DISABLED`)
    error.code = `${String(provider).toUpperCase()}_PROVIDER_DISABLED`
    throw error
  }
}

export function authRedirectUrl(recovery = false) {
  if (typeof window === 'undefined') return ''
  const url = new URL(window.location.origin)
  if (recovery) url.searchParams.set('recovery', '1')
  return url.toString()
}
