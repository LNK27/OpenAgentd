declare global {
  interface Window {
    __OAD_API_BASE_URL__?: string
  }
}

function normalizeBaseUrl(value: string | undefined): string {
  const trimmed = value?.trim()
  if (!trimmed) return '/api'
  const withoutTrailingSlash = trimmed.replace(/\/+$/, '')
  return withoutTrailingSlash.endsWith('/api')
    ? withoutTrailingSlash
    : `${withoutTrailingSlash}/api`
}

export function apiBaseUrl(): string {
  if (typeof window !== 'undefined' && window.__OAD_API_BASE_URL__) {
    return normalizeBaseUrl(window.__OAD_API_BASE_URL__)
  }
  return normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL)
}

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${apiBaseUrl()}${normalizedPath}`
}
