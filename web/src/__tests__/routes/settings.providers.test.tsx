import { afterEach, beforeEach, describe, expect, it } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import { ToastStack } from '@/components/ToastStack'
import { ProvidersSettingsPage } from '@/routes/settings.providers'
import { useToastStore } from '@/stores/useToastStore'

const server = setupServer()
let originalFetch: typeof fetch | undefined

beforeEach(() => {
  useToastStore.setState({ toasts: [] })
  server.listen()
  originalFetch = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    if (typeof input === 'string' && input.startsWith('/')) {
      return originalFetch?.(`http://localhost${input}`, init) ?? Promise.reject(new Error('fetch unavailable'))
    }
    return originalFetch?.(input, init) ?? Promise.reject(new Error('fetch unavailable'))
  }) as typeof fetch
})

afterEach(() => {
  server.resetHandlers()
  useToastStore.setState({ toasts: [] })
  if (originalFetch) globalThis.fetch = originalFetch
  originalFetch = undefined
  server.close()
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ProvidersSettingsPage />
      <ToastStack />
    </QueryClientProvider>,
  )
}

describe('ProvidersSettingsPage', () => {
  it('shows Failed instead of Connected when Codex OAuth model listing falls back', async () => {
    server.use(
      http.get('http://localhost/api/settings/providers', () => HttpResponse.json({
        has_any_configured: true,
        providers: [
          {
            id: 'codex',
            label: 'Codex',
            description: 'Codex OAuth provider',
            kind: 'oauth',
            credentials: [],
            env_var: '',
            env_vars: [],
            fallback_models: [],
            oauth_command: '',
            docs_url: '',
            is_configured: false,
            is_saved: true,
            is_reachable: false,
          },
        ],
      })),
      http.post('http://localhost/api/settings/providers/codex/models', () => HttpResponse.json({
        provider: 'codex',
        models: ['gpt-5'],
        source: 'fallback',
      })),
    )

    renderPage()

    expect(await screen.findByText('Codex')).toBeTruthy()
    expect(screen.getByText('Failed')).toBeTruthy()
    expect(screen.queryByText('Connected')).toBeNull()

    expect(screen.getAllByText('Failed').length).toBeGreaterThan(0)
    expect(screen.queryByText('Connected')).toBeNull()
  })
})
