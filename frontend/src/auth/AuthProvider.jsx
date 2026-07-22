import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { apiRequest, setApiAccessToken } from '../services/apiClient.js'
import {
  authConfigured,
  authRedirectUrl,
  authRequired,
  requireAuthProvider,
  supabase,
} from './supabaseClient.js'
import { clearRecoveryUrl, ensureRecoverySession, readRecoveryUrl } from './recoverySession.js'

const AuthContext = createContext(null)

function recoveryRequested() {
  if (typeof window === 'undefined') return false
  return readRecoveryUrl(window.location.href).requested
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null)
  const [accountProfile, setAccountProfile] = useState(null)
  const [loading, setLoading] = useState(authConfigured)
  const [passwordRecovery, setPasswordRecovery] = useState(recoveryRequested)
  const [recoveryError, setRecoveryError] = useState(null)
  const [authDialogOpen, setAuthDialogOpen] = useState(false)

  useEffect(() => {
    if (!supabase) {
      setApiAccessToken('')
      setLoading(false)
      return undefined
    }

    let active = true
    const applySession = async nextSession => {
      if (!active) return
      setSession(nextSession)
      setApiAccessToken(nextSession?.access_token)
      setLoading(false)
      if (!nextSession) {
        setAccountProfile(null)
        return
      }
      const metadataRole = String(nextSession.user?.app_metadata?.role || 'user').toLowerCase()
      setAccountProfile({
        app_role: metadataRole,
        is_admin: metadataRole === 'admin',
      })
      try {
        const profile = await apiRequest('/api/auth/me', { timeoutMs: 6000 })
        if (active) setAccountProfile(profile)
      } catch (_) {
        if (active) {
          setAccountProfile({
            app_role: metadataRole,
            is_admin: metadataRole === 'admin',
          })
        }
      }
    }

    const initializeSession = async () => {
      try {
        if (recoveryRequested()) {
          const recoveredSession = await ensureRecoverySession(supabase, window.location.href)
          if (active) {
            setPasswordRecovery(true)
            setRecoveryError(null)
          }
          await applySession(recoveredSession)
          return
        }
        const { data, error } = await supabase.auth.getSession()
        await applySession(error ? null : data.session)
      } catch (error) {
        if (active) {
          setRecoveryError(error)
          setPasswordRecovery(true)
        }
        await applySession(null)
      }
    }

    initializeSession()

    const { data: listener } = supabase.auth.onAuthStateChange((event, nextSession) => {
      if (!active) return
      applySession(nextSession)
      if (nextSession) setAuthDialogOpen(false)
      if (event === 'PASSWORD_RECOVERY') setPasswordRecovery(true)
      if (event === 'PASSWORD_RECOVERY') setRecoveryError(null)
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
      await ensureRecoverySession(
        supabase,
        typeof window === 'undefined' ? '' : window.location.href,
      )
      const { data, error } = await supabase.auth.updateUser({ password })
      if (error) throw error
      setPasswordRecovery(false)
      setRecoveryError(null)
      clearRecoveryUrl()
      return data
    },
    async signOut() {
      if (!supabase) return
      setApiAccessToken('')
      const { error } = await supabase.auth.signOut()
      if (error) throw error
    },
  }), [])

  const value = useMemo(() => {
    const appRole = String(
      accountProfile?.app_role
      || session?.user?.app_metadata?.role
      || 'user'
    ).toLowerCase()
    return {
      configured: authConfigured,
      required: authRequired,
      enabled: authConfigured,
      loading,
      session,
      user: session?.user || null,
      appRole,
      isAdmin: appRole === 'admin',
      passwordRecovery,
      recoveryError,
      authDialogOpen,
      ...actions,
    }
  }, [accountProfile, actions, authDialogOpen, loading, passwordRecovery, recoveryError, session])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider.')
  return context
}
