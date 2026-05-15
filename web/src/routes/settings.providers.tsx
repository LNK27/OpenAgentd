import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, CheckCircle2, ExternalLink, KeyRound, Loader2, ShieldCheck, TerminalSquare } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { installSeed, oauthLoginStream, type OAuthLoginEvent, type ProviderInfo } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { queryKeys, useInstallSeedMutation, useProvidersQuery, useSaveProviderMutation } from '@/queries'
import { openExternalUrl } from '@/lib/open-external'
import { useIsMobile } from '@/hooks/use-mobile'
import { useToastStore } from '@/stores/useToastStore'

function defaultModel(provider: ProviderInfo): string {
  return provider.default_models[0] ?? ''
}

function providerModel(provider: ProviderInfo, model: string): string {
  return `${provider.id}:${model || defaultModel(provider)}`
}

function providerKindLabel(kind: ProviderInfo['kind']): string {
  if (kind === 'api_key') return 'API key'
  if (kind === 'oauth') return 'OAuth'
  if (kind === 'local') return 'Local'
  return 'Cloud credentials'
}

function eventLabel(event: OAuthLoginEvent): string {
  if (event.event === 'started') return 'Starting secure login'
  if (event.event === 'device_code') return 'Waiting for browser approval'
  if (event.event === 'polling' && typeof event.elapsed_s === 'number') return `Still waiting (${event.elapsed_s}s)`
  if (event.event === 'token_acquired') return 'Token received'
  if (event.event === 'verifying') return 'Verifying provider access'
  if (event.event === 'success') return 'Connected'
  if (event.event === 'failed') return 'Connection failed'
  return event.message || event.event.replaceAll('_', ' ')
}

function ProviderCard({ provider }: { provider: ProviderInfo }) {
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(defaultModel(provider))
  const [oauthOpen, setOauthOpen] = useState(false)
  const saveMutation = useSaveProviderMutation()
  const seedMutation = useInstallSeedMutation()
  const push = useToastStore((s) => s.push)

  const canSave = provider.kind === 'api_key' && apiKey.trim().length > 0 && model.trim().length > 0

  const handleSave = async () => {
    try {
      const result = await saveMutation.mutateAsync({
        providerId: provider.id,
        body: { api_key: apiKey.trim(), default_model: model },
      })
      if (result.is_first_provider) {
        await seedMutation.mutateAsync(providerModel(provider, model))
      }
      setApiKey('')
      push({
        tone: 'success',
        title: 'Provider saved',
        description: result.is_first_provider ? 'Default agents and skills are ready.' : provider.label,
      })
    } catch (err) {
      push({
        tone: 'error',
        title: 'Provider setup failed',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  return (
    <Card size="sm" className="border-(--color-border) bg-(--bg-card)">
      <CardHeader className="gap-4 sm:grid-cols-[1fr_auto] sm:items-start">
        <div className="flex min-w-0 gap-3">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border)">
            {provider.kind === 'oauth' ? <ShieldCheck size={13} aria-hidden="true" /> : <KeyRound size={13} aria-hidden="true" />}
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle>{provider.label}</CardTitle>
              <span className="rounded-md bg-(--bg-key) px-2 py-0.5 text-[11px] font-medium text-(--color-text-muted)">
                {providerKindLabel(provider.kind)}
              </span>
            {provider.is_configured && (
              <span className="inline-flex items-center gap-1 rounded-md bg-(--color-success-subtle) px-2 py-0.5 text-[11px] font-medium text-(--color-success)">
                <CheckCircle2 size={12} aria-hidden="true" />
                Connected
              </span>
            )}
            </div>
            <CardDescription className="mt-1 max-w-2xl">{provider.description}</CardDescription>
          </div>
        </div>
        {provider.docs_url && (
          <a
            href={provider.docs_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 justify-self-start text-xs text-(--color-accent) hover:underline sm:justify-self-end"
          >
            Docs <ExternalLink size={12} aria-hidden="true" />
          </a>
        )}
      </CardHeader>
      <CardContent className="space-y-4 pl-12 max-sm:pl-3">
        {provider.kind === 'api_key' && (
          <div className="grid gap-3 lg:grid-cols-[minmax(260px,1fr)_240px_auto] lg:items-end">
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-(--color-text-muted)">{provider.env_var}</span>
              <Input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={provider.is_configured ? 'Enter a new key to replace current key' : 'Paste API key'}
                autoComplete="off"
              />
            </label>
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-(--color-text-muted)">Default model</span>
              <NativeSelect
                value={model}
                onChange={(event) => setModel(event.target.value)}
                className="w-full"
                aria-label={`${provider.label} default model`}
              >
                {provider.default_models.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </NativeSelect>
            </label>
            <Button
              type="button"
              onClick={handleSave}
              disabled={!canSave || saveMutation.isPending || seedMutation.isPending}
            >
              {(saveMutation.isPending || seedMutation.isPending) && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
              Save
            </Button>
          </div>
        )}

        {provider.kind === 'oauth' && (
          <div className="flex flex-col gap-3 rounded-lg border border-(--color-border) bg-(--bg-key) p-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-(--color-text-muted)">
              Opens a browser approval page and stores the token locally after success.
            </p>
            <Button type="button" onClick={() => setOauthOpen(true)}>
              <ShieldCheck size={14} aria-hidden="true" />
              Connect
            </Button>
          </div>
        )}

        {provider.kind !== 'api_key' && provider.kind !== 'oauth' && (
          <p className="rounded-lg border border-(--color-border) bg-(--bg-key) p-3 text-xs text-(--color-text-muted)">
            This provider is detected from local environment or system credentials.
          </p>
        )}
      </CardContent>
      {provider.kind === 'oauth' && oauthOpen && (
        <OAuthLoginDialog
          provider={provider}
          open={oauthOpen}
          onOpenChange={setOauthOpen}
        />
      )}
    </Card>
  )
}

function OAuthLoginDialog({
  provider,
  open,
  onOpenChange,
}: {
  provider: ProviderInfo
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [events, setEvents] = useState<OAuthLoginEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const openedUrlRef = useRef<string | null>(null)
  const successHandledRef = useRef(false)
  const queryClient = useQueryClient()
  const latest = events.at(-1)
  const deviceEvent = events.find((event) => event.event === 'device_code')
  const isSuccess = latest?.event === 'success'
  const isWorking = open && !isSuccess && !error

  useEffect(() => {
    if (!open) return undefined
    const abort = new AbortController()
    openedUrlRef.current = null
    successHandledRef.current = false
    oauthLoginStream(
      provider.id,
      {
        onEvent: () => undefined,
        onOAuthEvent: (event) => {
          setEvents((current) => [...current, event])
          if (event.verification_uri && openedUrlRef.current !== event.verification_uri) {
            openedUrlRef.current = event.verification_uri
            void openExternalUrl(event.verification_uri)
          }
          if (event.event === 'success' && !successHandledRef.current) {
            successHandledRef.current = true
            void queryClient.invalidateQueries({ queryKey: queryKeys.settings.providers() })
            const model = event.suggested_model
            if (model) {
              void installSeed(model)
                .then(() => {
                  useToastStore.getState().push({
                    tone: 'success',
                    title: 'Provider connected',
                    description: 'Default agents and skills are ready.',
                  })
                })
                .catch((err: unknown) => {
                  useToastStore.getState().push({
                    tone: 'error',
                    title: 'Seed install failed',
                    description: err instanceof Error ? err.message : String(err),
                  })
                })
            } else {
              useToastStore.getState().push({ tone: 'success', title: 'Provider connected', description: provider.label })
            }
          }
          if (event.event === 'failed') {
            setError(event.message ?? 'OAuth login failed')
          }
        },
        onError: (err) => setError(err.message),
      },
      abort.signal,
    )
    return () => abort.abort()
  }, [open, provider.id, provider.label, queryClient])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Connect {provider.label}</DialogTitle>
          <DialogDescription>Approve the browser prompt. This window will update when the token is saved.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="flex items-center gap-3 rounded-lg border border-(--color-border) bg-(--bg-key) p-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-(--bg-card) text-(--color-accent) ring-1 ring-(--color-border)">
              {isWorking ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <CheckCircle2 className="h-4 w-4" aria-hidden="true" />}
            </div>
            <div>
              <p className="text-sm font-medium text-(--color-text)">{latest ? eventLabel(latest) : 'Starting secure login'}</p>
              <p className="text-xs text-(--color-text-muted)">Keep this dialog open until setup completes.</p>
            </div>
          </div>
          {deviceEvent?.user_code && (
            <div className="rounded-lg border border-(--accent-blue)/30 bg-(--accent-blue-soft) p-5 text-center">
              <p className="text-xs text-(--color-text-muted)">Device code</p>
              <p className="mt-2 font-mono text-3xl font-semibold tracking-[0.18em] text-(--color-text)">{deviceEvent.user_code}</p>
              {deviceEvent.verification_uri && (
                <Button className="mt-4" size="sm" onClick={() => void openExternalUrl(deviceEvent.verification_uri!)}>
                  Open authorization page
                </Button>
              )}
            </div>
          )}
          {isSuccess && (
            <p className="rounded-md bg-(--color-success-subtle) p-3 text-sm text-(--color-success)">Connected successfully.</p>
          )}
          {error && <p className="rounded-md bg-(--color-error)/10 p-3 text-sm text-(--color-error)">{error}</p>}
          {events.length > 0 && (
            <details className="rounded-md border border-(--color-border) bg-(--bg-page) p-3">
              <summary className="flex cursor-pointer items-center gap-2 text-xs font-medium text-(--color-text-muted)">
                <TerminalSquare size={13} aria-hidden="true" />
                Technical details
              </summary>
              <div className="mt-3 max-h-40 space-y-2 overflow-auto">
                {events.map((event, index) => (
                  <p key={`${event.event}-${index}`} className="text-xs text-(--color-text-muted)">
                    <span className="font-mono text-(--color-text)">{event.event}</span>
                    {event.message ? ` · ${event.message}` : ''}
                  </p>
                ))}
              </div>
            </details>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function ProvidersSettingsPage() {
  const isMobile = useIsMobile()
  const providersQ = useProvidersQuery()
  const sortedProviders = useMemo(
    () => [...(providersQ.data?.providers ?? [])].sort((a, b) => Number(b.is_configured) - Number(a.is_configured) || a.label.localeCompare(b.label)),
    [providersQ.data?.providers],
  )

  const connectedCount = sortedProviders.filter((provider) => provider.is_configured).length

  return (
    <>
      <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-3 border-b border-(--color-border) bg-(--bg-page) px-4">
        {isMobile && (
          <Link
            to="/settings"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Back to settings"
          >
            <ArrowLeft size={14} />
          </Link>
        )}
        <KeyRound size={15} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
        <h1 className="flex-1 truncate text-sm font-semibold text-(--color-text)">Providers</h1>
        <span className="text-xs text-(--color-text-muted)">{connectedCount} connected</span>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-5 p-6">
          <p className="text-sm leading-relaxed text-(--color-text-muted)">
            Add the model provider OpenAgentd should use for seeded agents. API keys are written to your local config; OAuth tokens are stored in your local cache.
          </p>

        {providersQ.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-(--color-text-muted)">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Loading providers…
          </div>
        ) : providersQ.error ? (
          <div className="rounded-lg border border-(--color-error)/30 bg-(--color-error)/10 p-4 text-sm text-(--color-error)">
            {providersQ.error instanceof Error ? providersQ.error.message : String(providersQ.error)}
          </div>
        ) : (
          <div className="grid gap-3">
            {sortedProviders.map((provider) => (
              <ProviderCard key={provider.id} provider={provider} />
            ))}
          </div>
        )}
      </div>
      </div>
    </>
  )
}
