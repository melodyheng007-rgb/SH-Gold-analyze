import React, { useEffect, useState } from 'react'
import {
  ArrowLeft,
  CheckCircle2,
  Diamond,
  Eye,
  EyeOff,
  KeyRound,
  LockKeyhole,
  Mail,
  RotateCw,
  ShieldCheck,
  UserRound,
  X,
} from 'lucide-react'
import { normalizeEmail, validateAuthForm } from './authValidation.js'
import { AUTH_REQUEST_TIMEOUT_CODE } from './authRequest.js'
import { useAuth } from './AuthProvider.jsx'

const EMPTY_FORM = { fullName: '', email: '', password: '', confirmPassword: '', otp: '' }

function friendlyAuthError(error) {
  const value = String(error?.message || '').toLowerCase()
  const code = String(error?.code || '').toLowerCase()
  if (error?.code === AUTH_REQUEST_TIMEOUT_CODE || value.includes(AUTH_REQUEST_TIMEOUT_CODE.toLowerCase())) {
    return 'The account service took too long. Check your inbox before trying again.'
  }
  if (code === 'google_provider_disabled' || value.includes('unsupported provider')) {
    return 'Google sign-in is not available yet. Please use email sign-in.'
  }
  if (code === 'account_configuration_invalid' || value.includes('invalid api key')) {
    return 'Account access is not configured correctly. Please contact support.'
  }
  if (value.includes('error sending') || value.includes('smtp') || value.includes('confirmation email')) {
    return 'We could not send the confirmation email. Please try again shortly.'
  }
  if (value.includes('signup') && value.includes('disabled')) return 'New account registration is temporarily unavailable.'
  if (value.includes('password') && (value.includes('weak') || value.includes('characters'))) {
    return 'Choose a stronger password with at least 8 characters.'
  }
  if (value.includes('invalid login')) return 'Incorrect email or password.'
  if (value.includes('email not confirmed')) return 'Confirm your email before signing in.'
  if (value.includes('already registered')) return 'An account already exists for this email.'
  if (value.includes('expired') || value.includes('token') || value.includes('otp')) return 'The confirmation code is invalid or expired.'
  if (value.includes('rate') || value.includes('too many')) return 'Too many attempts. Please wait and try again.'
  if (value.includes('fetch') || value.includes('network') || value.includes('unavailable')) return 'Account service is temporarily unavailable.'
  return 'We could not complete that request. Please try again.'
}

function PasswordField({ label, name, value, onChange, autoComplete }) {
  const [visible, setVisible] = useState(false)
  return (
    <label className="auth-field">
      <span>{label}</span>
      <div>
        <LockKeyhole size={16} />
        <input
          type={visible ? 'text' : 'password'}
          name={name}
          value={value}
          onChange={onChange}
          autoComplete={autoComplete}
          minLength={8}
          required
        />
        <button type="button" onClick={() => setVisible(current => !current)} title={visible ? 'Hide password' : 'Show password'} aria-label={visible ? 'Hide password' : 'Show password'}>
          {visible ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      </div>
    </label>
  )
}

export function AuthScreen({ recovery = false, onClose = null }) {
  const auth = useAuth()
  const [mode, setMode] = useState(recovery ? 'reset' : 'login')
  const [form, setForm] = useState(EMPTY_FORM)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [resendSeconds, setResendSeconds] = useState(0)

  useEffect(() => {
    if (recovery) setMode('reset')
  }, [recovery])

  useEffect(() => {
    if (resendSeconds <= 0) return undefined
    const timer = window.setInterval(() => setResendSeconds(value => Math.max(0, value - 1)), 1000)
    return () => window.clearInterval(timer)
  }, [resendSeconds])

  function changeMode(nextMode) {
    setMode(nextMode)
    setError('')
    setMessage('')
    setResendSeconds(0)
    setForm(current => ({ ...EMPTY_FORM, email: current.email }))
  }

  function handleChange(event) {
    setForm(current => ({ ...current, [event.target.name]: event.target.value }))
  }

  function handleOtpChange(event) {
    const otp = event.target.value.replace(/\D/g, '').slice(0, 6)
    setForm(current => ({ ...current, otp }))
  }

  async function submit(event) {
    event.preventDefault()
    setError('')
    setMessage('')
    if (!auth.configured) {
      setError('Account service is temporarily unavailable. Please try again shortly.')
      return
    }
    const validationError = validateAuthForm(mode, form)
    if (validationError) {
      setError(validationError)
      return
    }

    const email = normalizeEmail(form.email)
    setBusy(true)
    try {
      if (mode === 'login') {
        await auth.signIn(email, form.password)
      } else if (mode === 'register') {
        const result = await auth.signUp(email, form.password, form.fullName.trim())
        if (result.needsEmailConfirmation) {
          setMode('verify-signup')
          setForm(current => ({ ...EMPTY_FORM, email: current.email }))
          setResendSeconds(30)
          setMessage('A 6-digit confirmation code was sent to your email.')
        }
      } else if (mode === 'forgot') {
        await auth.sendPasswordReset(email)
        setMode('verify-recovery')
        setForm(current => ({ ...EMPTY_FORM, email: current.email }))
        setResendSeconds(30)
        setMessage('A 6-digit recovery code was sent to your email.')
      } else if (mode === 'verify-signup') {
        const result = await auth.verifyEmailCode(email, form.otp, 'signup')
        if (!result?.session) {
          setMode('login')
          setMessage('Email confirmed. You can now sign in.')
        }
      } else if (mode === 'verify-recovery') {
        await auth.verifyEmailCode(email, form.otp, 'recovery')
        setMode('reset')
        setForm(current => ({ ...EMPTY_FORM, email: current.email }))
        setMessage('Code confirmed. Choose a new password.')
      } else if (mode === 'reset') {
        await auth.updatePassword(form.password)
      }
    } catch (requestError) {
      setError(friendlyAuthError(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function resendCode() {
    if (resendSeconds > 0 || busy || !auth.configured) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const purpose = mode === 'verify-recovery' ? 'recovery' : 'signup'
      await auth.resendEmailCode(normalizeEmail(form.email), purpose)
      setResendSeconds(30)
      setMessage('A new confirmation code was sent.')
    } catch (requestError) {
      setError(friendlyAuthError(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function continueWithGoogle() {
    if (!auth.configured) {
      setError('Account service is temporarily unavailable. Please try again shortly.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await auth.signInWithGoogle()
    } catch (requestError) {
      setError(friendlyAuthError(requestError))
      setBusy(false)
    }
  }

  const verificationMode = ['verify-signup', 'verify-recovery'].includes(mode)
  const busyLabel = mode === 'register'
    ? 'Creating account...'
    : mode === 'login'
      ? 'Signing in...'
      : verificationMode
        ? 'Checking code...'
        : mode === 'forgot'
          ? 'Sending code...'
          : 'Updating password...'
  const title = mode === 'register'
    ? 'Create your account'
    : mode === 'forgot'
      ? 'Reset your password'
      : verificationMode
        ? 'Check your email'
        : mode === 'reset'
          ? 'Choose a new password'
          : 'Welcome back'
  const subtitle = mode === 'register'
    ? 'One account for XAU and BTC intelligence.'
    : mode === 'forgot'
      ? 'We will email you a secure confirmation code.'
      : verificationMode
        ? `Enter the 6-digit code sent to ${form.email}.`
        : mode === 'reset'
          ? 'Use at least 8 characters for your new password.'
          : 'Sign in to open your market workspace.'

  return (
    <main className="auth-screen">
      <section className="auth-brand" aria-label="SH Market Analyzer">
        <div className="auth-brand-mark"><Diamond size={26} /></div>
        <div><span>SH MARKET ANALYZER</span><strong>Diamond Discovery</strong></div>
      </section>

      <section className="auth-panel">
        {onClose && (
          <button className="auth-close" type="button" onClick={onClose} title="Close account access" aria-label="Close account access">
            <X size={17} />
          </button>
        )}
        <header>
          <span><ShieldCheck size={15} /> Secure account</span>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </header>

        {!auth.configured && (
          <div className="auth-feedback config" role="status">
            Account access is temporarily unavailable. Please try again shortly.
          </div>
        )}

        {!['forgot', 'reset'].includes(mode) && !verificationMode && (
          <div className="auth-segmented" aria-label="Authentication mode">
            <button type="button" className={mode === 'login' ? 'active' : ''} onClick={() => changeMode('login')}>Sign in</button>
            <button type="button" className={mode === 'register' ? 'active' : ''} onClick={() => changeMode('register')}>Register</button>
          </div>
        )}

        {['login', 'register'].includes(mode) && (
          <button className="google-auth-button" type="button" onClick={continueWithGoogle} disabled={busy}>
            <span className="google-g">G</span>
            Continue with Google
          </button>
        )}

        {['login', 'register'].includes(mode) && <div className="auth-divider"><span>or use email</span></div>}

        <form onSubmit={submit}>
          {mode === 'register' && (
            <label className="auth-field">
              <span>Full name</span>
              <div><UserRound size={16} /><input name="fullName" value={form.fullName} onChange={handleChange} autoComplete="name" required /></div>
            </label>
          )}
          {['login', 'register', 'forgot'].includes(mode) && (
            <label className="auth-field">
              <span>Email</span>
              <div><Mail size={16} /><input type="email" name="email" value={form.email} onChange={handleChange} autoComplete="email" required /></div>
            </label>
          )}
          {['login', 'register', 'reset'].includes(mode) && (
            <PasswordField label={mode === 'reset' ? 'New password' : 'Password'} name="password" value={form.password} onChange={handleChange} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
          )}
          {['register', 'reset'].includes(mode) && (
            <PasswordField label="Confirm password" name="confirmPassword" value={form.confirmPassword} onChange={handleChange} autoComplete="new-password" />
          )}
          {verificationMode && (
            <label className="auth-field auth-otp-field">
              <span>Confirmation code</span>
              <div>
                <KeyRound size={17} />
                <input
                  type="text"
                  name="otp"
                  value={form.otp}
                  onChange={handleOtpChange}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  placeholder="000000"
                  aria-label="6-digit confirmation code"
                  required
                  autoFocus
                />
              </div>
            </label>
          )}

          {mode === 'login' && <button className="forgot-link" type="button" onClick={() => changeMode('forgot')}>Forgot password?</button>}

          {error && <div className="auth-feedback error" role="alert">{error}</div>}
          {message && <div className="auth-feedback success" role="status"><CheckCircle2 size={15} />{message}</div>}

          <button className="auth-submit" type="submit" disabled={busy}>
            {busy
              ? busyLabel
              : mode === 'login'
                ? 'Sign in'
                : mode === 'register'
                  ? 'Create account'
                  : mode === 'forgot'
                    ? 'Send confirmation code'
                    : verificationMode
                      ? 'Confirm code'
                      : 'Update password'}
          </button>
        </form>

        {verificationMode && (
          <div className="auth-resend-row">
            <button type="button" onClick={resendCode} disabled={busy || resendSeconds > 0 || !auth.configured}>
              <RotateCw size={14} />
              {resendSeconds > 0 ? `Resend in ${resendSeconds}s` : 'Resend code'}
            </button>
          </div>
        )}

        {['forgot', 'verify-signup', 'verify-recovery'].includes(mode) && (
          <button className="auth-back" type="button" onClick={() => changeMode(mode === 'verify-signup' ? 'register' : mode === 'verify-recovery' ? 'forgot' : 'login')}>
            <ArrowLeft size={15} /> {verificationMode ? 'Use another email' : 'Back to sign in'}
          </button>
        )}
      </section>

      <footer className="auth-footer">Protected access to live market analysis</footer>
    </main>
  )
}
