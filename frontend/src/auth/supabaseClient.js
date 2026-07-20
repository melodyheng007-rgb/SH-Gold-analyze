import { createClient } from '@supabase/supabase-js'
import { createAuthFetch } from './authRequest.js'

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
        fetch: createAuthFetch(),
      },
    })
  : null

export function authRedirectUrl(recovery = false) {
  if (typeof window === 'undefined') return ''
  const url = new URL(window.location.origin)
  if (recovery) url.searchParams.set('recovery', '1')
  return url.toString()
}
