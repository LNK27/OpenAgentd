import { useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, ExternalLink, KeyRound, Loader2, ShieldCheck } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

import { oauthLoginStream, type OAuthLoginEvent, type ProviderInfo } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { queryKeys, useInstallSeedMutation, useProvidersQuery, useSaveProviderMutation } from '@/queries'
import { cn } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'

function defaultModel(provider: ProviderInfo): string {
  return provider.default_models[0] ?? ''
}

function providerModel(provider: ProviderInfo, model: string): string {
  return `${provider.id}:${model || defaultModel(provider)}`
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
      <CardHeader className="gap-3 sm:grid-cols-[1fr_auto]">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{provider.label}</CardTitle>
            {provider.is_configured && (
              <span className="inline-flex items-center gap-1 rounded-full bg-(--accent-green-soft) px-2 py-0.5 text-[11px] font-medium text-(--accent-green)">
                <CheckCircle2 size={12} aria-hidden="true" />
                Connected
              </span>
            )}
          </div>
          <CardDescription>{provider.description}</CardDescription>
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
      <CardContent className="space-y-3">
        {provider.kind === 'api_key' && (
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px_auto] sm:items-end">
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
          <div className="flex flex-col gap-3 rounded-lg bg-(--bg-key) p-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-(--color-text-muted)">
              Connect through the provider's browser device flow. Tokens are stored locally.
            </p>
            <Button type="button" onClick={() => setOauthOpen(true)}>
              <ShieldCheck size={14} aria-hidden="true" />
              Connect
            </Button>
          </div>
        )}

        {provider.kind !== 'api_key' && provider.kind !== 'oauth' && (
          <p className="rounded-lg bg-(--bg-key) p-3 text-xs text-(--color-text-muted)">
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
  const queryClient = useQueryClient()
  const seedMutation = useInstallSeedMutation()
  const push = useToastStore((s) => s.push)
  const latest = events.at(-1)
  const deviceEvent = events.find((event) => event.event === 'device_code')

  useEffect(() => {
    if (!open) return undefined
    const abort = new AbortController()
    openedUrlRef.current = null
    oauthLoginStream(
      provider.id,
      {
        onEvent: () => undefined,
        onOAuthEvent: (event) => {
          setEvents((current) => [...current, event])
          if (event.verification_uri && openedUrlRef.current !== event.verification_uri) {
            openedUrlRef.current = event.verification_uri
            window.open(event.verification_uri, '_blank', 'noopener,noreferrer')
          }
          if (event.event === 'success') {
            void queryClient.invalidateQueries({ queryKey: queryKeys.settings.providers() })
            const model = event.suggested_model
            if (model) {
              seedMutation.mutate(model, {
                onSuccess: () => {
                  push({ tone: 'success', title: 'Provider connected', description: 'Default agents and skills are ready.' })
                },
                onError: (err) => {
                  push({ tone: 'error', title: 'Seed install failed', description: err instanceof Error ? err.message : String(err) })
                },
              })
            } else {
              push({ tone: 'success', title: 'Provider connected', description: provider.label })
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
  }, [open, provider.id, provider.label, push, queryClient, seedMutation])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Connect {provider.label}</DialogTitle>
          <DialogDescription>Approve the device code in your browser, then return here.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {deviceEvent?.user_code && (
            <div className="rounded-xl border border-(--color-border) bg-(--bg-key) p-4 text-center">
              <p className="text-xs text-(--color-text-muted)">Device code</p>
              <p className="mt-1 font-mono text-2xl font-semibold tracking-widest text-(--color-text)">{deviceEvent.user_code}</p>
              {deviceEvent.verification_uri && (
                <Button className="mt-3" size="sm" onClick={() => window.open(deviceEvent.verification_uri, '_blank', 'noopener,noreferrer')}>
                  Open authorization page
                </Button>
              )}
            </div>
          )}
          <div className="max-h-48 space-y-2 overflow-auto rounded-lg border border-(--color-border) bg-(--bg-page) p-3">
            {events.length === 0 ? (
              <p className="flex items-center gap-2 text-xs text-(--color-text-muted)">
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                Starting login flow…
              </p>
            ) : events.map((event, index) => (
              <p key={`${event.event}-${index}`} className="text-xs text-(--color-text-muted)">
                <span className="font-mono text-(--color-text)">{event.event}</span>
                {event.message ? ` · ${event.message}` : ''}
              </p>
            ))}
          </div>
          {latest?.event === 'success' && (
            <p className="rounded-lg bg-(--accent-green-soft) p-3 text-sm text-(--accent-green)">Connected successfully.</p>
          )}
          {error && <p className="rounded-lg bg-(--color-error)/10 p-3 text-sm text-(--color-error)">{error}</p>}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function ProvidersSettingsPage() {
  const providersQ = useProvidersQuery()
  const sortedProviders = useMemo(
    () => [...(providersQ.data?.providers ?? [])].sort((a, b) => Number(b.is_configured) - Number(a.is_configured) || a.label.localeCompare(b.label)),
    [providersQ.data?.providers],
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4 md:p-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        <div className="rounded-2xl border border-(--color-border) bg-(--bg-card) p-5">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-(--bg-key) text-(--color-accent)">
              <KeyRound size={18} aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-(--color-text)">Providers</h1>
              <p className="mt-1 max-w-2xl text-sm text-(--color-text-muted)">
                Add the model provider OpenAgentd should use for seeded agents. Credentials stay in your local OpenAgentd config/cache directories.
              </p>
            </div>
          </div>
        </div>

        {providersQ.isLoading ? (
          <div className="flex items-center gap-2 rounded-xl border border-(--color-border) bg-(--bg-card) p-4 text-sm text-(--color-text-muted)">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Loading providers…
          </div>
        ) : providersQ.error ? (
          <div className="rounded-xl border border-(--color-error)/30 bg-(--color-error)/10 p-4 text-sm text-(--color-error)">
            {providersQ.error instanceof Error ? providersQ.error.message : String(providersQ.error)}
          </div>
        ) : (
          <div className={cn('grid gap-4', sortedProviders.length > 1 && 'lg:grid-cols-2')}>
            {sortedProviders.map((provider) => (
              <ProviderCard key={provider.id} provider={provider} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
