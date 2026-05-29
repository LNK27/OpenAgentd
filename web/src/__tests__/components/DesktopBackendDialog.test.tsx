import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DesktopBackendDialog } from '@/components/DesktopBackendDialog'

const originalFetch = globalThis.fetch
const invokeCalls: Array<{ command: string; args: unknown }> = []
let statusPayload = {
  base_url: 'http://127.0.0.1:5999',
  sidecar_running: false,
  external: true,
  servers: ['http://127.0.0.1:4082', 'http://127.0.0.1:4999'],
}

const invokeMock = mock(async (...args: unknown[]) => {
  const command = String(args[0])
  const commandArgs = args[1]
  invokeCalls.push({ command, args: commandArgs })
  if (command === 'desktop_backend_status') return statusPayload
  if (command === 'desktop_set_backend_base_url') return null
  throw new Error(`unexpected command: ${command}`)
})

mock.module('@tauri-apps/api/core', () => ({
  invoke: invokeMock,
}))

beforeEach(() => {
  invokeCalls.length = 0
  statusPayload = {
    base_url: 'http://127.0.0.1:5999',
    sidecar_running: false,
    external: true,
    servers: ['http://127.0.0.1:4082', 'http://127.0.0.1:4999'],
  }
  window.__OAD_API_BASE_URL__ = 'http://127.0.0.1:5999'
  const fetchMock = mock((...args: unknown[]) => {
    const url = String(args[0])
    const ok = url.startsWith('http://127.0.0.1:4082/')
    return Promise.resolve(new Response(null, { status: ok ? 204 : 503 }))
  })
  globalThis.fetch = fetchMock as typeof fetch
})

afterEach(() => {
  cleanup()
  globalThis.fetch = originalFetch
  delete window.__OAD_API_BASE_URL__
})

describe('DesktopBackendDialog', () => {
  it('loads saved servers and shows live online/offline indicators', async () => {
    render(<DesktopBackendDialog open onOpenChange={() => {}} />)

    expect(await screen.findByText('http://127.0.0.1:4082')).toBeTruthy()
    expect(screen.getByText('http://127.0.0.1:4999')).toBeTruthy()

    await waitFor(() => expect(screen.getByLabelText('Online')).toBeTruthy())
    await waitFor(() => expect(screen.getByLabelText('Offline')).toBeTruthy())
  })

  it('blocks incomplete URLs before invoking the desktop switch command', async () => {
    const user = userEvent.setup()
    render(<DesktopBackendDialog open onOpenChange={() => {}} />)

    await user.type(screen.getByLabelText(/add or connect server url/i), 'localhost')
    await user.click(screen.getByRole('button', { name: 'Connect' }))

    expect(await screen.findByText('Enter a full server URL, including http:// or https://.')).toBeTruthy()
    expect(invokeCalls.some((call) => call.command === 'desktop_set_backend_base_url')).toBe(false)
  })

  it('connects a valid typed URL through the desktop command', async () => {
    const user = userEvent.setup()
    const onOpenChange = mock(() => {})
    render(<DesktopBackendDialog open onOpenChange={onOpenChange} />)

    await user.type(screen.getByLabelText(/add or connect server url/i), 'http://127.0.0.1:4082')
    await user.click(screen.getByRole('button', { name: 'Connect' }))

    await waitFor(() => {
      expect(invokeCalls).toContainEqual({
        command: 'desktop_set_backend_base_url',
        args: { baseUrl: 'http://127.0.0.1:4082' },
      })
    })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('connects a saved server directly without copying stale input', async () => {
    const user = userEvent.setup()
    render(<DesktopBackendDialog open onOpenChange={() => {}} />)

    await user.type(screen.getByLabelText(/add or connect server url/i), 'http://wrong.example')
    await user.click(await screen.findByText('http://127.0.0.1:4082'))

    await waitFor(() => {
      expect(invokeCalls).toContainEqual({
        command: 'desktop_set_backend_base_url',
        args: { baseUrl: 'http://127.0.0.1:4082' },
      })
    })
  })
})
