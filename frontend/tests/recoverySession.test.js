import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ensureRecoverySession,
  readRecoveryUrl,
  RECOVERY_LINK_INVALID,
  RECOVERY_SESSION_MISSING,
} from '../src/auth/recoverySession.js'

test('reads PKCE and implicit recovery callbacks', () => {
  const pkce = readRecoveryUrl('http://localhost:3000/?recovery=1&code=abc')
  assert.equal(pkce.requested, true)
  assert.equal(pkce.code, 'abc')

  const implicit = readRecoveryUrl('http://localhost:3000/#access_token=a&refresh_token=r&type=recovery')
  assert.equal(implicit.requested, true)
  assert.equal(implicit.accessToken, 'a')
  assert.equal(implicit.refreshToken, 'r')
})

test('exchanges a PKCE callback when no session is cached', async () => {
  const expected = { access_token: 'fresh' }
  const client = {
    auth: {
      getSession: async () => ({ data: { session: null }, error: null }),
      exchangeCodeForSession: async code => ({
        data: { session: code === 'abc' ? expected : null },
        error: null,
      }),
    },
  }

  assert.equal(
    await ensureRecoverySession(client, 'http://localhost:3000/?recovery=1&code=abc'),
    expected,
  )
})

test('restores an implicit callback and rejects expired or empty links', async () => {
  const expected = { access_token: 'fresh' }
  const client = {
    auth: {
      getSession: async () => ({ data: { session: null }, error: null }),
      setSession: async tokens => ({
        data: { session: tokens.refresh_token === 'r' ? expected : null },
        error: null,
      }),
    },
  }

  assert.equal(
    await ensureRecoverySession(client, 'http://localhost:3000/#access_token=a&refresh_token=r&type=recovery'),
    expected,
  )
  await assert.rejects(
    ensureRecoverySession(client, 'http://localhost:3000/#error=access_denied&error_code=otp_expired'),
    error => error.code === RECOVERY_LINK_INVALID,
  )
  await assert.rejects(
    ensureRecoverySession(client, 'http://localhost:3000/?recovery=1'),
    error => error.code === RECOVERY_SESSION_MISSING,
  )
})
