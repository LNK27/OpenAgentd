import { useEffect, useState } from 'react'
import { Server } from 'lucide-react'

import { apiBaseUrl } from '@/api/base-url'
import {
  getDesktopBackendStatus,
  setDesktopBackendBaseUrl,
  type DesktopBackendStatus,
} from '@/lib/desktop-backend'

interface DesktopBackendDialogProps {
  /** Whether the connection dialog is visible. */
  open: boolean
  /** Called when the dialog should open or close. */
  onOpenChange: (open: boolean) => void
}

export function DesktopBackendDialog({ open, onOpenChange }: DesktopBackendDialogProps) {
  const [status, setStatus] = useState<DesktopBackendStatus | null>(null)
  const [baseUrl, setBaseUrl] = useState('')
  const [serverHealth, setServerHealth] = useState<Record<string, 'checking' | 'online' | 'offline'>>({})
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    void getDesktopBackendStatus().then((next) => {
      if (cancelled) return
      setStatus(next)
      setBaseUrl('')
      const servers = next?.servers ?? ['http://127.0.0.1:4082']
      setServerHealth(Object.fromEntries(servers.map((server) => [server, 'checking'])))
      for (const server of servers) {
        void pingServer(server).then((online) => {
          if (cancelled) return
          setServerHealth((prev) => ({ ...prev, [server]: online ? 'online' : 'offline' }))
        })
      }
    })
    return () => { cancelled = true }
  }, [open])

  if (!open) return null

  async function connectExternal(nextBaseUrl = baseUrl) {
    const target = nextBaseUrl.trim()
    const validationError = validateServerUrl(target)
    if (validationError) {
      setError(validationError)
      return
    }
    setPending(true)
    setError(null)
    try {
      await setDesktopBackendBaseUrl(target)
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setPending(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="desktop-backend-title"
      onClick={() => onOpenChange(false)}
    >
      <div
        className="w-full max-w-md rounded-xl border border-(--color-border) bg-(--bg-card) text-(--color-text) shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start gap-3 border-b border-(--color-border) px-4 py-4">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border)" aria-hidden="true">
            <Server size={18} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 id="desktop-backend-title" className="text-sm font-semibold">Backend connection</h2>
            <p className="mt-1 text-xs leading-5 text-(--color-text-muted)">
              Connect this desktop shell to a running OpenAgentd server.
            </p>
          </div>
        </div>

        <div className="space-y-4 px-4 py-4">
          <div className="rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-2 text-xs text-(--color-text-muted)">
            Current: <span className="font-mono text-(--color-text)">{status?.base_url || apiBaseUrl().replace(/\/api$/, '')}</span>
            <span className="ml-2 rounded bg-(--bg-key) px-1.5 py-0.5 text-[10px]">
              {status?.external ? 'external' : 'bundled'}
            </span>
          </div>

          <div>
            <div className="mb-2 text-xs font-medium text-(--color-text)">Saved servers</div>
            <div className="space-y-1">
              {(status?.servers ?? ['http://127.0.0.1:4082']).map((server) => (
                <button
                  key={server}
                  type="button"
                  onClick={() => { setBaseUrl(server); void connectExternal(server) }}
                  className="flex w-full items-center justify-between rounded-md border border-(--color-border) px-3 py-2 text-left font-mono text-xs hover:bg-(--bg-page)"
                  disabled={pending}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <ServerStatusDot status={serverHealth[server]} />
                    <span className="truncate">{server}</span>
                  </span>
                  <span className="ml-2 rounded bg-(--bg-key) px-1.5 py-0.5 font-sans text-[10px] text-(--color-text-muted)">connect</span>
                </button>
              ))}
            </div>
          </div>

          <label className="block text-xs font-medium text-(--color-text)" htmlFor="desktop-backend-url">
            Add or connect server URL
          </label>
          <div className="flex gap-2">
            <input
              id="desktop-backend-url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="http://127.0.0.1:4082"
              className="min-w-0 flex-1 rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-2 font-mono text-sm text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-muted) focus:border-(--focus-ring) focus:ring-3 focus:ring-(--focus-ring)/30"
            />
            <button
              type="button"
              onClick={() => void connectExternal()}
              className="rounded-md border border-(--color-border-strong) bg-(--bg-key) px-3 py-2 text-xs font-medium text-(--color-text) hover:bg-(--bg-page) disabled:cursor-not-allowed disabled:opacity-60"
              disabled={pending}
            >
              {pending ? 'Connecting…' : 'Connect'}
            </button>
          </div>
          <p className="text-xs leading-5 text-(--color-text-muted)">
            Checks if it is running before switching.
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
