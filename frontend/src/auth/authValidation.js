export function normalizeEmail(value) {
  return String(value || '').trim().toLowerCase()
}

export function validateEmail(value) {
  const email = normalizeEmail(value)
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
}

export function validateAuthForm(mode, values = {}) {
  const email = normalizeEmail(values.email)
  const password = String(values.password || '')
  const confirmPassword = String(values.confirmPassword || '')
  const fullName = String(values.fullName || '').trim()
  const otp = String(values.otp || '').replace(/\D/g, '')

  if (['verify-signup', 'verify-recovery'].includes(mode)) {
    return otp.length === 6 ? '' : 'Enter the 6-digit confirmation code.'
  }
  if (mode === 'register' && fullName.length < 2) return 'Enter your full name.'
  if (mode !== 'reset' && !validateEmail(email)) return 'Enter a valid email address.'
  if (mode === 'forgot') return ''
  if (password.length < 8) return 'Password must contain at least 8 characters.'
  if (['register', 'reset'].includes(mode) && password !== confirmPassword) return 'Passwords do not match.'
  return ''
}
