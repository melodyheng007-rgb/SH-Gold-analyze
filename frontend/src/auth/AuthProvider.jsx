import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { setApiAccessToken } from '../services/apiClient.js'
import {
  authConfigured,
  authRedirectUrl,
  authRequired,
  requireAuthProvider,
  supabase,
} from './supabaseClient.js'

const AuthContext = createContext(null)

function recoveryRequested() {
  if (typeof window === 'undefined') return false
  const query = new URLSearchParams(window.location.search)
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  return query.get('recovery') === '1' || query.get('type') === 'recovery' || hash.get('type') === 'recovery'
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(authConfigured)
  const [passwordRecovery, setPasswordRecovery] = useState(recoveryRequested)
  const [authDialogOpen, setAuthDialogOpen] = useState(false)

  useEffect(() => {
    if (!supabase) {
      setApiAccessToken('')
      setLoading(false)
      return undefined
    }

    let active = true
    supabase.auth.getSession().then(({ data, error }) => {
      if (!active) return
      setSession(error ? null : data.session)
      setApiAccessToken(error ? '' : data.session?.access_token)
      setLoading(false)
    })

    const { data: listener } = supabase.auth.onAuthStateChange((event, nextSession) => {
      if (!active) return
      setSession(nextSession)
      setApiAccessToken(nextSession?.access_token)
      if (nextSession) setAuthDialogOpen(false)
      if (event === 'PASSWORD_RECOVERY') setPasswordRecovery(true)
      if (event === 'SIGNED_OUT') setPasswordRecovery(false)
      setLoading(false)
    })

    return () => {
      active = false
      listener.subscription.unsubscribe()
      setApiAccessToken('')
    }
  }, [])

  const actions = useMemo(() => ({
    openAuth() {
      setAuthDialogOpen(true)
    },
    closeAuth() {
      setAuthDialogOpen(false)
    },
    async signIn(email, password) {
      if (!supabase) throw new Error('Account service is unavailable.')
      const { data, error } = await supabase.auth.signInWithPassword({ email, password })
      if (error) throw error
      return data
    },
    async signUp(email, password, fullName) {
      if (!supabase) throw new Error('Account service is unavailable.')
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: {
          data: { full_name: fullName },
          emailRedirectTo: authRedirectUrl(),
        },
      })
      if (error) throw error
      return { ...data, needsEmailConfirmation: !data.session }
    },
    async signInWithGoogle() {
      if (!supabase) throw new Error('Account service is unavailable.')
      await requireAuthProvider('google')
      const { data, error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: authRedirectUrl() },
      })
      if (error) throw error
      return data
    },
    async sendPasswordReset(email) {
      if (!supabase) throw new Error('Account service is unavailable.')
      const { data, error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: authRedirectUrl(true),
      })
      if (error) throw error
      return data
    },
    async verifyEmailCode(email, token, purpose = 'signup') {
      if (!supabase) throw new Error('Account service is unavailable.')
      const type = purpose === 'recovery' ? 'recovery' : 'email'
      const { data, error } = await supabase.auth.verifyOtp({ email, token, type })
      if (error) throw error
      if (purpose === 'recovery') setPasswordRecovery(true)
      return data
    },
    async resendEmailCode(email, purpose = 'signup') {
      if (!supabase) throw new Error('Account service is unavailable.')
      if (purpose === 'recovery') {
        const { data, error } = await supabase.auth.resetPasswordForEmail(email, {
          redirectTo: authRedirectUrl(true),
        })
        if (error) throw error
        return data
      }
      const { data, error } = await supabase.auth.resend({
        type: 'signup',
        email,
        options: { emailRedirectTo: authRedirectUrl() },
      })
      if (error) throw error
      return data
    },
    async updatePassword(password) {
      if (!supabase) throw new Error('Account service is unavailable.')
      const { data, error } = await supabase.auth.updateUser({ password })
      if (error) throw error
      setPasswordRecovery(false)
      if (typeof window !== 'undefined') window.history.replaceState({}, document.title, window.location.pathname)
      return data
    },
    async signOut() {
      if (!supabase) return
      setApiAccessToken('')
      const { error } = await supabase.auth.signOut()
      if (error) throw error
    },
  }), [])

  const value = useMemo(() => ({
    configured: authConfigured,
    required: authRequired,
    enabled: authConfigured,
    loading,
    session,
    user: session?.user || null,
    passwordRecovery,
    authDialogOpen,
    ...actions,
  }), [actions, authDialogOpen, loading, passwordRecovery, session])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider.')
  return context
}
