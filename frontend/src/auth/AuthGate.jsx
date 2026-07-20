import React from 'react'
import { Diamond } from 'lucide-react'
import { AuthScreen } from './AuthScreen.jsx'
import { useAuth } from './AuthProvider.jsx'

export function AuthGate({ children }) {
  const auth = useAuth()

  if (auth.loading) {
    return (
      <main className="auth-loading-screen">
        <Diamond size={24} />
        <strong>Securing your workspace</strong>
        <span />
      </main>
    )
  }

  if (!auth.required && auth.authDialogOpen) {
    return <AuthScreen recovery={auth.passwordRecovery} onClose={auth.closeAuth} />
  }

  if (auth.required && (auth.passwordRecovery || !auth.session)) {
    return <AuthScreen recovery={auth.passwordRecovery} />
  }

  return children
}
