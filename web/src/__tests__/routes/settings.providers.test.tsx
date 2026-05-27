import { afterEach, beforeEach, describe, expect, it } from 'bun:test'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

  it('shows GitHub device-code copy for Copilot OAuth', async () => {
    server.use(
      http.get('http://localhost/api/settings/providers', () => HttpResponse.json({
        has_any_configured: true,
        providers: [
          {
            id: 'copilot',
            label: 'Copilot',
            description: 'Copilot OAuth provider',
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
      http.get('http://localhost/api/auth/copilot/login', () => new HttpResponse(
        'event: device_code\ndata: {"user_code":"ABCD-1234"}\n\n',
        { headers: { 'Content-Type': 'text/event-stream' } },
      )),
    )

    renderPage()

    expect(await screen.findByText('Copilot')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Connect/i }))

    expect(await screen.findByText('ABCD-1234')).toBeTruthy()
    expect(screen.getByText('Use this code on GitHub to authorize Copilot. Keep this dialog open while GitHub approves access.')).toBeTruthy()
    expect(screen.queryByText(/personal ChatGPT accounts/)).toBeNull()
  })

  it('shows active usage for any connected OAuth provider', async () => {
    server.use(
      http.get('http://localhost/api/settings/providers', () => HttpResponse.json({
        has_any_configured: true,
        providers: [
          {
            id: 'plugin-oauth',
            label: 'Plugin OAuth',
            description: 'OAuth provider plugin',
            kind: 'oauth',
            credentials: [],
            env_var: '',
            env_vars: [],
            fallback_models: [],
            oauth_command: '',
            docs_url: '',
            is_configured: true,
            is_saved: true,
            is_reachable: true,
          },
        ],
      })),
      http.post('http://localhost/api/settings/providers/plugin-oauth/models', () => HttpResponse.json({
        provider: 'plugin-oauth',
        models: ['model-a'],
        source: 'provider',
      })),
      http.get('http://localhost/api/settings/providers/plugin-oauth/usage', () => HttpResponse.json({
        provider: 'plugin-oauth',
        limits: [
          {
            limit_id: 'model-a',
            limit_name: 'Model A',
            plan_type: 'Live',
            primary: { used_percent: 42, resets_at: null, window_minutes: null },
          },
        ],
      })),
    )

    renderPage()

    expect(await screen.findByText('Plugin OAuth')).toBeTruthy()
    await waitFor(() => expect(screen.getByText('Active usage')).toBeTruthy())
    expect(screen.getByText('Model A · window')).toBeTruthy()
    expect(screen.getByText(/42% used/)).toBeTruthy()
  })
})
