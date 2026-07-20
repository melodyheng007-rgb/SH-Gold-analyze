import assert from 'node:assert/strict'
import test from 'node:test'

import {
  AUTH_REQUEST_TIMEOUT_CODE,
  createAuthFetch,
} from '../src/auth/authRequest.js'

test('createAuthFetch returns successful responses before the deadline', async () => {
  const response = { ok: true }
  const authFetch = createAuthFetch(async () => response, 25)

  assert.equal(await authFetch('/auth'), response)
})

test('createAuthFetch rejects stalled requests with a stable timeout code', async () => {
  const stalledFetch = (_input, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true })
  })
  const authFetch = createAuthFetch(stalledFetch, 5)

  await assert.rejects(
    authFetch('/auth'),
    error => error.code === AUTH_REQUEST_TIMEOUT_CODE,
  )
})

test('createAuthFetch preserves upstream cancellation', async () => {
  const controller = new AbortController()
  const abortedFetch = (_input, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new Error('upstream aborted')), { once: true })
  })
  const authFetch = createAuthFetch(abortedFetch, 100)
  const request = authFetch('/auth', { signal: controller.signal })
  controller.abort()

  await assert.rejects(request, /upstream aborted/)
})
