import React, { useEffect, useRef, useState } from 'react'
import { ShieldCheck } from 'lucide-react'

const SITE_KEY = String(import.meta.env.VITE_TURNSTILE_SITE_KEY || '').trim()
const SCRIPT_ID = 'cloudflare-turnstile-script'

function loadTurnstile() {
  if (window.turnstile) return Promise.resolve(window.turnstile)
  return new Promise((resolve, reject) => {
    const existing = document.getElementById(SCRIPT_ID)
    if (existing) {
      existing.addEventListener('load', () => resolve(window.turnstile), { once: true })
      existing.addEventListener('error', reject, { once: true })
      return
    }
    const script = document.createElement('script')
    script.id = SCRIPT_ID
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
    script.async = true
    script.defer = true
    script.onload = () => resolve(window.turnstile)
    script.onerror = reject
    document.head.appendChild(script)
  })
}

export const turnstileConfigured = Boolean(SITE_KEY)

export function TurnstileGate({ onToken, resetNonce = 0 }) {
  const hostRef = useRef(null)
  const widgetRef = useRef(null)
  const [state, setState] = useState('loading')

  useEffect(() => {
    if (!SITE_KEY || !hostRef.current) return undefined
    let active = true
    loadTurnstile()
      .then(turnstile => {
        if (!active || !turnstile || !hostRef.current || widgetRef.current !== null) return
        widgetRef.current = turnstile.render(hostRef.current, {
          sitekey: SITE_KEY,
          theme: 'dark',
          size: 'flexible',
          appearance: 'always',
          action: 'account_access',
          callback: token => {
            setState('verified')
            onToken(token)
          },
          'expired-callback': () => {
            setState('expired')
            onToken('')
          },
          'error-callback': () => {
            setState('error')
            onToken('')
          },
        })
        setState('ready')
      })
      .catch(() => {
        if (active) setState('error')
      })
    return () => {
      active = false
      if (window.turnstile && widgetRef.current !== null) {
        window.turnstile.remove(widgetRef.current)
        widgetRef.current = null
      }
    }
  }, [onToken])

  useEffect(() => {
    if (!window.turnstile || widgetRef.current === null || resetNonce === 0) return
    window.turnstile.reset(widgetRef.current)
    setState('ready')
    onToken('')
  }, [onToken, resetNonce])

  if (!SITE_KEY) return null
  return (
    <section className={`turnstile-gate ${state}`} aria-label="Human verification">
      <div><ShieldCheck size={14} /><span>{state === 'verified' ? 'Security check complete' : 'Verify you are human'}</span></div>
      <div ref={hostRef} className="turnstile-widget" />
      {state === 'error' && <small>Security check could not load. Check your connection and try again.</small>}
    </section>
  )
}
