import { useEffect, useState } from 'react'
import { Server } from 'lucide-react'

import { apiBaseUrl, setApiBaseUrl } from '@/api/base-url'
import {
  getAppBackendStatus,
  removeAppBackendServer,
  saveAppBackendServer,
  useBundledAppBackend,
  type SavedAppServer,
  type AppBackendStatus,
} from '@/lib/app-backend'

const DEFAULT_SERVERS: SavedAppServer[] = [{ base_url: 'http://127.0.0.1:4082', name: 'Local CLI server' }]

interface AppBackendDialogProps {
  /** Whether the connection dialog is visible. */
  open: boolean
  /** Called when the dialog should open or close. */
  onOpenChange: (open: boolean) => void
}

export function AppBackendDialog({ open, onOpenChange }: AppBackendDialogProps) {
  const [status, setStatus] = useState<AppBackendStatus | null>(null)
  const [baseUrl, setBaseUrl] = useState('')
  const [serverName, setServerName] = useState('')
  const [serverHealth, setServerHealth] = useState<Record<string, 'checking' | 'online' | 'offline'>>({})
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    void getAppBackendStatus().then((next) => {
      if (cancelled) return
      setStatus(next)
      setBaseUrl('')
      setServerName('')
      const servers = next?.servers ?? DEFAULT_SERVERS
      setServerHealth(Object.fromEntries(servers.map((server) => [server.base_url, 'checking'])))
      for (const server of servers) {
        void pingServer(server.base_url).then((online) => {
          if (cancelled) return
          setServerHealth((prev) => ({ ...prev, [server.base_url]: online ? 'online' : 'offline' }))
        })
      }
    })
    return () => { cancelled = true }
  }, [open])

  if (!open) return null

  async function checkExternal(nextBaseUrl = baseUrl) {
    const target = nextBaseUrl.trim()
    const validationError = validateServerUrl(target)
    if (validationError) {
      setError(validationError)
      return
    }
    setPending(true)
    setError(null)
    try {
      const normalized = target.replace(/\/+$/, '')
      const online = await pingServer(normalized)
      setServerHealth((prev) => ({ ...prev, [normalized]: online ? 'online' : 'offline' }))
      if (!online) {
        setError('Server did not respond to /api/health/live. Check that OpenAgentd is running with --host 0.0.0.0, this device is on the same network, and the URL uses the backend machine LAN IP.')
        return
      }
      setApiBaseUrl(normalized)
      setStatus((prev) => ({
        base_url: normalized,
        sidecar_running: false,
        external: true,
        supports_bundled: prev?.supports_bundled ?? false,
        servers: prev?.servers ?? DEFAULT_SERVERS,
      }))
    } finally {
      setPending(false)
    }
  }

  async function connectBundled() {
    await runConnectionSwitch(() => useBundledAppBackend())
  }

  async function saveServer() {
    const target = baseUrl.trim()
    const validationError = validateServerUrl(target)
    if (validationError) {
      setError(validationError)
      return
    }
    setPending(true)
    setError(null)
    try {
      const next = await saveAppBackendServer(target, serverName)
      setStatus(next)
      setBaseUrl('')
      setServerName('')
      const normalized = target.replace(/\/+$/, '')
      setServerHealth((prev) => ({ ...prev, [normalized]: 'checking' }))
      const online = await pingServer(normalized)
      setServerHealth((prev) => ({ ...prev, [normalized]: online ? 'online' : 'offline' }))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setPending(false)
    }
  }

  async function removeServer(baseUrl: string) {
    setPending(true)
    setError(null)
    try {
      const next = await removeAppBackendServer(baseUrl)
      setStatus(next)
      setServerHealth((prev) => {
        const { [baseUrl]: _removed, ...rest } = prev
        return rest
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setPending(false)
    }
  }

  async function runConnectionSwitch(action: () => Promise<void>) {
    setPending(true)
    setError(null)
    try {
      await action()
      const next = await getAppBackendStatus()
      setStatus(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setPending(false)
    }
  }

  return (
    <div
      className="mobile-safe-overlay fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="app-backend-title"
      onClick={() => onOpenChange(false)}
    >
      <div
        className="flex max-h-full w-full max-w-md flex-col overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card) text-(--color-text) shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start gap-3 border-b border-(--color-border) px-4 py-4">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border)" aria-hidden="true">
            <Server size={18} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 id="app-backend-title" className="text-sm font-semibold">Backend connection</h2>
            <p className="mt-1 text-xs leading-5 text-(--color-text-muted)">
              Connect this app to a running OpenAgentd server. Mobile apps use a remote backend only.
            </p>
          </div>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
          <div className="rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-2 text-xs text-(--color-text-muted)">
            Current: <span className="font-mono text-(--color-text)">{status?.base_url || apiBaseUrl().replace(/\/api$/, '')}</span>
            <span className="ml-2 rounded bg-(--bg-key) px-1.5 py-0.5 text-[10px]">
              {status?.external ? 'external' : 'bundled'}
            </span>
          </div>

          <div className="rounded-lg border border-(--accent-blue)/35 bg-(--accent-blue-soft) px-3 py-2 text-xs leading-5 text-(--color-text-muted)">
            <p className="font-medium text-(--color-text)">Connecting from iPhone or another device?</p>
            <ol className="mt-1 list-decimal space-y-1 pl-4">
              <li>Run the backend with <code className="rounded bg-(--bg-card) px-1 py-0.5 font-mono text-[10px]">--host 0.0.0.0 --port 8000</code>.</li>
              <li>Keep this device on the same Wi‑Fi/LAN as the backend machine.</li>
              <li>Enter that machine's LAN URL, for example <code className="rounded bg-(--bg-card) px-1 py-0.5 font-mono text-[10px]">http://192.168.1.62:8000</code>.</li>
            </ol>
          </div>

          <div>
            <div className="mb-2 text-xs font-medium text-(--color-text)">Saved servers</div>
            <div className="space-y-1">
              {status?.supports_bundled !== false ? (
                <button
                  type="button"
                  onClick={() => { void connectBundled() }}
                  className="flex w-full items-center justify-between rounded-md border border-(--color-border) px-3 py-2 text-left text-xs hover:bg-(--bg-page)"
                  disabled={pending}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <ServerStatusDot status={status?.sidecar_running ? 'online' : undefined} />
                    <span className="truncate font-medium">Builtin Desktop App server</span>
                  </span>
                  <span className="ml-2 rounded bg-(--bg-key) px-1.5 py-0.5 font-sans text-[10px] text-(--color-text-muted)">
                    {status?.external ? 'connect' : 'active'}
                  </span>
                </button>
              ) : null}
              {(status?.servers ?? DEFAULT_SERVERS).map((server) => (
                <div
                  key={server.base_url}
                  className="flex items-center gap-2 rounded-md border border-(--color-border) px-3 py-2 text-xs hover:bg-(--bg-page)"
                >
                  <button
                    type="button"
                    onClick={() => { setBaseUrl(server.base_url); void checkExternal(server.base_url) }}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                    disabled={pending}
                  >
                    <ServerStatusDot status={serverHealth[server.base_url]} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{server.name || server.base_url}</span>
                      {server.name ? <span className="block truncate font-mono text-[10px] text-(--color-text-muted)">{server.base_url}</span> : null}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => { setBaseUrl(server.base_url); setServerName(server.name ?? '') }}
                    className="rounded bg-(--bg-key) px-1.5 py-0.5 text-[10px] text-(--color-text-muted) hover:text-(--color-text)"
                    disabled={pending}
                  >
                    edit
                  </button>
                  <button
                    type="button"
                    onClick={() => { void removeServer(server.base_url) }}
                    className="rounded bg-(--bg-key) px-1.5 py-0.5 text-[10px] text-(--color-error) hover:bg-(--color-error)/10"
                    disabled={pending}
                  >
                    remove
                  </button>
                </div>
              ))}
            </div>
          </div>

          <label className="block text-xs font-medium text-(--color-text)" htmlFor="app-backend-url">
            Add or connect server URL
          </label>
          <div className="flex gap-2">
            <input
              id="app-backend-url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="http://192.168.1.62:8000"
              className="min-w-0 flex-1 rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-2 font-mono text-sm text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-muted) focus:border-(--focus-ring) focus:ring-3 focus:ring-(--focus-ring)/30"
            />
            <button
              type="button"
              onClick={() => void checkExternal()}
              className="rounded-md border border-(--color-border-strong) bg-(--bg-key) px-3 py-2 text-xs font-medium text-(--color-text) hover:bg-(--bg-page) disabled:cursor-not-allowed disabled:opacity-60"
              disabled={pending}
            >
              {pending ? 'Checking…' : 'Check'}
            </button>
          </div>
          <label className="block text-xs font-medium text-(--color-text)" htmlFor="app-backend-name">
            Server name
          </label>
          <div className="flex gap-2">
            <input
              id="app-backend-name"
              value={serverName}
              onChange={(event) => setServerName(event.target.value)}
              placeholder="Work laptop, Home server, Local CLI"
              className="min-w-0 flex-1 rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-2 text-sm text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-muted) focus:border-(--focus-ring) focus:ring-3 focus:ring-(--focus-ring)/30"
            />
            <button
              type="button"
              onClick={() => void saveServer()}
              className="rounded-md border border-(--color-border-strong) bg-(--bg-key) px-3 py-2 text-xs font-medium text-(--color-text) hover:bg-(--bg-page) disabled:cursor-not-allowed disabled:opacity-60"
              disabled={pending}
            >
              Save
            </button>
          </div>
          <p className="text-xs leading-5 text-(--color-text-muted)">
            Check verifies the server and uses it for this app session. Save persists or renames it for future use. If the check fails, confirm the backend is not bound to localhost only and that firewall/local-network permissions allow access.
          </p>

          {error ? (
            <div className="rounded-md border border-(--color-error)/40 bg-(--color-error)/10 px-3 py-2 text-xs text-(--color-error)" role="alert">
              {error}
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-(--color-border) px-4 py-3">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="rounded-md px-3 py-1.5 text-xs font-medium text-(--color-text-muted) hover:bg-(--bg-page)"
            disabled={pending}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

function validateServerUrl(value: string): string | null {
  if (!value) return 'Enter a server URL first.'
  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    return 'Enter a full server URL, including http:// or https://.'
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return `Unsupported URL scheme: ${parsed.protocol.replace(/:$/, '')}`
  }
  return null
}

async function pingServer(baseUrl: string): Promise<boolean> {
  const base = baseUrl.replace(/\/+$/, '')
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 1500)
  try {
    const res = await fetch(`${base}/api/health/live`, { signal: controller.signal })
    return res.ok
  } catch {
    return false
  } finally {
    window.clearTimeout(timeout)
  }
}

function ServerStatusDot({ status }: { status: 'checking' | 'online' | 'offline' | undefined }) {
  const className = status === 'online'
    ? 'bg-(--color-success)'
    : status === 'offline'
      ? 'bg-(--color-error)'
      : 'animate-pulse bg-(--color-text-muted)'
  const label = status === 'online' ? 'Online' : status === 'offline' ? 'Offline' : 'Checking'
  return <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${className}`} title={label} aria-label={label} />
}
