import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, apiKey, clearApiKey, hasStoredApiKey, setApiKey, validateApiKey } from './api'

// This suite runs under vitest's `node` environment (see vitest.config.ts),
// so `window` doesn't exist by default. api.js only ever touches `window`
// behind a `typeof window !== 'undefined'` guard, so a minimal fake -- just
// enough localStorage + event target to exercise that guard -- is enough.
function fakeStorage() {
  const store = new Map<string, string>()
  return {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => store.set(k, String(v)),
    removeItem: (k: string) => store.delete(k),
  }
}

function installFakeWindow() {
  const listeners = new Map<string, Array<(e: unknown) => void>>()
  const win = {
    localStorage: fakeStorage(),
    __BRAIN_API_KEY__: undefined as string | undefined,
    addEventListener: (type: string, fn: (e: unknown) => void) => {
      const list = listeners.get(type) || []
      list.push(fn)
      listeners.set(type, list)
    },
    removeEventListener: (type: string, fn: (e: unknown) => void) => {
      listeners.set(type, (listeners.get(type) || []).filter((f) => f !== fn))
    },
    dispatchEvent: (evt: { type: string }) => {
      for (const fn of listeners.get(evt.type) || []) fn(evt)
      return true
    },
  }
  // @ts-expect-error -- test double, not a real Window
  global.window = win
  // @ts-expect-error -- node has no CustomEvent global
  global.CustomEvent = class CustomEvent {
    type: string
    detail: unknown
    constructor(type: string, opts: { detail?: unknown } = {}) {
      this.type = type
      this.detail = opts.detail
    }
  }
  return win
}

describe('apiKey', () => {
  beforeEach(() => {
    installFakeWindow()
  })
  afterEach(() => {
    // @ts-expect-error -- cleanup the test double
    delete global.window
    // @ts-expect-error -- cleanup the test double
    delete global.CustomEvent
  })

  it('falls back to the hardcoded dev key when nothing else is set', () => {
    expect(apiKey()).toBe('local-dev-key')
  })

  it('prefers window.__BRAIN_API_KEY__ over the fallback', () => {
    window.__BRAIN_API_KEY__ = 'injected-key'
    expect(apiKey()).toBe('injected-key')
  })

  it('prefers a stored key over window.__BRAIN_API_KEY__ and the fallback', () => {
    window.__BRAIN_API_KEY__ = 'injected-key'
    setApiKey('stored-key')
    expect(apiKey()).toBe('stored-key')
  })
})

describe('setApiKey / clearApiKey / hasStoredApiKey', () => {
  beforeEach(() => {
    installFakeWindow()
  })
  afterEach(() => {
    // @ts-expect-error -- cleanup the test double
    delete global.window
    // @ts-expect-error -- cleanup the test double
    delete global.CustomEvent
  })

  it('round-trips a key through storage', () => {
    expect(hasStoredApiKey()).toBe(false)
    setApiKey('my-key')
    expect(hasStoredApiKey()).toBe(true)
    expect(apiKey()).toBe('my-key')
    clearApiKey()
    expect(hasStoredApiKey()).toBe(false)
  })
})

describe('validateApiKey', () => {
  beforeEach(() => {
    installFakeWindow()
  })
  afterEach(() => {
    // @ts-expect-error -- cleanup the test double
    delete global.window
    // @ts-expect-error -- cleanup the test double
    delete global.CustomEvent
    vi.unstubAllGlobals()
  })

  it('reports ok for a key the server accepts', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => '' }))
    await expect(validateApiKey('good-key')).resolves.toEqual({ ok: true })
  })

  it('reports an error, without throwing, for a key the server rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 401, text: async () => 'Unauthorized' }),
    )
    const result = await validateApiKey('bad-key')
    expect(result.ok).toBe(false)
    expect(result.error).toContain('401')
  })
})

describe('api() on a 401', () => {
  beforeEach(() => {
    installFakeWindow()
  })
  afterEach(() => {
    // @ts-expect-error -- cleanup the test double
    delete global.window
    // @ts-expect-error -- cleanup the test double
    delete global.CustomEvent
    vi.unstubAllGlobals()
  })

  it('dispatches brain:unauthorized and still throws', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 401, text: async () => 'nope' }),
    )
    const handler = vi.fn()
    window.addEventListener('brain:unauthorized', handler)

    await expect(api('/stats')).rejects.toThrow('401')
    expect(handler).toHaveBeenCalledTimes(1)
  })
})
