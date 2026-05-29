import { afterEach, describe, expect, it } from 'bun:test'

const originalEnv = import.meta.env.VITE_API_BASE_URL

declare global {
  interface Window {
    __OAD_API_BASE_URL__?: string
  }
}

afterEach(() => {
  delete window.__OAD_API_BASE_URL__
  import.meta.env.VITE_API_BASE_URL = originalEnv
})

describe('apiBaseUrl', () => {
  it('defaults to same-origin /api when no desktop or env override exists', async () => {
    import.meta.env.VITE_API_BASE_URL = undefined
    const { apiBaseUrl, apiUrl } = await import('@/api/base-url')

    expect(apiBaseUrl()).toBe('/api')
    expect(apiUrl('/health/live')).toBe('/api/health/live')
  })

  it('normalizes desktop base URL and appends /api exactly once', async () => {
    window.__OAD_API_BASE_URL__ = 'http://127.0.0.1:4082///'
    const { apiBaseUrl, apiUrl } = await import('@/api/base-url')

    expect(apiBaseUrl()).toBe('http://127.0.0.1:4082/api')
    expect(apiUrl('team/status')).toBe('http://127.0.0.1:4082/api/team/status')
  })

  it('does not double-append /api when the injected URL already includes it', async () => {
    window.__OAD_API_BASE_URL__ = 'http://localhost:4082/api'
    const { apiBaseUrl, apiUrl } = await import('@/api/base-url')

    expect(apiBaseUrl()).toBe('http://localhost:4082/api')
    expect(apiUrl('/settings/sandbox')).toBe('http://localhost:4082/api/settings/sandbox')
  })
})
