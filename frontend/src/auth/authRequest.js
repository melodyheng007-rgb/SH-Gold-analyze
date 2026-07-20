export const AUTH_REQUEST_TIMEOUT_CODE = 'ACCOUNT_REQUEST_TIMEOUT'
export const AUTH_REQUEST_TIMEOUT_MS = 20_000

export function createAuthFetch(fetchImpl = globalThis.fetch, timeoutMs = AUTH_REQUEST_TIMEOUT_MS) {
  if (typeof fetchImpl !== 'function') throw new Error('A fetch implementation is required.')

  return async function authFetch(input, init = {}) {
    const controller = new AbortController()
    const upstreamSignal = init.signal
    let timedOut = false

    const abortFromUpstream = () => controller.abort(upstreamSignal?.reason)
    if (upstreamSignal?.aborted) abortFromUpstream()
    else upstreamSignal?.addEventListener('abort', abortFromUpstream, { once: true })

    const timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeoutMs)

    try {
      return await fetchImpl(input, { ...init, signal: controller.signal })
    } catch (error) {
      if (!timedOut) throw error
      const timeoutError = new Error(AUTH_REQUEST_TIMEOUT_CODE)
      timeoutError.code = AUTH_REQUEST_TIMEOUT_CODE
      timeoutError.cause = error
      throw timeoutError
    } finally {
      clearTimeout(timer)
      upstreamSignal?.removeEventListener('abort', abortFromUpstream)
    }
  }
}
