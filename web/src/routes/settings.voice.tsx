/**
 * /settings/voice — edit speech.yaml: voice input enable/disable and config.
 *
 * Follows the Dream/Sandbox pattern: local draft state rebased on the server
 * snapshot, dirty flag, Save button. Changes are written to speech.yaml via
 * PUT /api/speech/config and hot-reloaded by the backend on the next request.
 */
import { useMemo, useState } from 'react'
import { ArrowLeft, Mic, Save } from 'lucide-react'
import { Link } from '@tanstack/react-router'

import {
  useSpeechConfigQuery,
  useUpdateSpeechConfigMutation,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { useIsMobile } from '@/hooks/use-mobile'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import type { SpeechConfig } from '@/api/client'

// ── Types ─────────────────────────────────────────────────────────────────────

interface VoiceForm {
  enabled: boolean
  model: string
  language: string
  max_file_mb: number
}

const DEFAULT_FORM: VoiceForm = {
  enabled: false,
  model: 'local:base',
  language: 'auto',
  max_file_mb: 25,
}

function formFromConfig(cfg: SpeechConfig): VoiceForm {
  return {
    enabled: cfg.enabled,
    model: cfg.model,
    language: cfg.language,
    max_file_mb: cfg.max_file_mb,
  }
}

function configFromForm(form: VoiceForm): SpeechConfig {
  return {
    enabled: form.enabled,
    model: form.model.trim(),
    language: form.language.trim() || 'auto',
    max_file_mb: form.max_file_mb,
  }
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function VoiceSettingsPage() {
  const isMobile = useIsMobile()
  const { data, isLoading, error } = useSpeechConfigQuery()
  const updateMut = useUpdateSpeechConfigMutation()
  const push = useToastStore((s) => s.push)
  const availability = data?.availability
  const unavailableReason =
    availability?.local === 'unavailable'
      ? availability.reason || 'The local speech runtime is unavailable on this machine.'
      : null

  const [form, setForm] = useState<VoiceForm>(DEFAULT_FORM)
  const [sourceRaw, setSourceRaw] = useState<SpeechConfig | null>(null)

  // Rebase onto server snapshot (snapshot identity pattern — no useEffect).
  if (data && data !== sourceRaw) {
    setForm(formFromConfig(data))
    setSourceRaw(data)
  }

  const dirty = useMemo(() => {
    if (!sourceRaw) return false
    const src = formFromConfig(sourceRaw)
    return (
      form.enabled !== src.enabled ||
      form.model.trim() !== src.model ||
      (form.language.trim() || 'auto') !== src.language ||
      form.max_file_mb !== src.max_file_mb
    )
  }, [form, sourceRaw])

  const setField = <K extends keyof VoiceForm>(key: K, val: VoiceForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: val }))

  const handleSave = async () => {
    try {
      const saved = await updateMut.mutateAsync(configFromForm(form))
      setSourceRaw(saved)
      push({ tone: 'success', title: 'Voice config saved' })
    } catch (err) {
      push({
        tone: 'error',
        title: 'Save failed',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  return (
    <>
      <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-3 border-b border-(--color-border) bg-(--bg-page) px-4">
        {isMobile && (
          <Link
            to="/settings"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Back to settings"
          >
            <ArrowLeft size={14} />
          </Link>
        )}
        <Mic size={15} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
        <h1 className="flex-1 truncate text-sm font-semibold text-(--color-text)">Voice input</h1>
        {dirty && (
          <span className="text-xs text-(--color-text-muted)" aria-live="polite">
            Unsaved
          </span>
        )}
        <Button
          size="sm"
          className="min-h-11 md:min-h-0"
          onClick={handleSave}
          disabled={!dirty || updateMut.isPending}
        >
          <Save size={12} aria-hidden="true" />
          {updateMut.isPending ? 'Saving…' : 'Save'}
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-5 p-6">
          <p className="text-sm leading-relaxed text-(--color-text-muted)">
            Voice input lets you record from the microphone and insert the
            transcript into the chat input for review before sending.
            Transcription runs locally — no audio leaves your machine.
          </p>

          {isLoading && (
            <p className="text-sm text-(--color-text-muted)">Loading…</p>
          )}

          {error && (
            <div
              className="flex items-start gap-2 rounded-lg bg-(--color-error-subtle) p-3 text-xs text-(--color-error)"
              role="alert"
            >
              <span>{error instanceof Error ? error.message : String(error)}</span>
            </div>
          )}

          {unavailableReason && (
            <div
              className="space-y-2 rounded-xl border border-(--color-warning)/30 bg-(--color-warning-subtle) p-4 text-sm text-(--color-text)"
              role="status"
            >
              <p className="font-medium">Voice runtime unavailable</p>
              <p className="text-xs leading-relaxed text-(--color-text-muted)">
                OpenAgentd can still run normally, but local voice transcription is disabled because the bundled speech runtime could not load.
              </p>
              <p className="break-words rounded-md bg-(--bg-key) p-2 font-mono text-[11px] text-(--color-text-muted)">
                {unavailableReason}
              </p>
              <p className="text-xs text-(--color-text-muted)">
                On Windows, install the Microsoft Visual C++ Redistributable, check Defender exclusions for <code className="font-mono">C:\\Program Files\\OpenAgentd</code>, and verify your CPU supports AVX2. See the troubleshooting guide for details.
              </p>
            </div>
          )}

          {!isLoading && !error && (
            <div className="space-y-5">

              {/* ── Enable / disable ───────────────────────────────── */}
              <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Status
                </h2>

                <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm md:min-h-0">
                  <Switch
                    checked={form.enabled}
                    onCheckedChange={(checked) => setField('enabled', checked)}
                  />
                  <span className="text-(--color-text)">Enabled</span>
                </label>
                <p className="text-xs text-(--color-text-muted)">
                  When disabled the mic button in the chat input is shown but inactive.
                  Transcription runs locally via{' '}
                  <code className="rounded bg-(--bg-key) px-1 font-mono">faster-whisper</code>{' '}
                  and ships with every install — no extras needed.
                </p>
              </section>

              {/* ── Model ─────────────────────────────────────────── */}
              <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Model
                </h2>

                <div className="grid gap-1.5">
                  <label htmlFor="voice-model" className="text-xs font-medium text-(--color-text-muted)">
                    Model ID
                  </label>
                  <Input
                    id="voice-model"
                    value={form.model}
                    onChange={(e) => setField('model', e.target.value)}
                    placeholder="local:base"
                    className="min-h-11 font-mono text-sm md:min-h-9"
                  />
                  <p className="text-[11px] text-(--color-text-muted)">
                    Format: <code className="font-mono">provider:name</code>.
                    V1 supports <code className="font-mono">local:base</code>,{' '}
                    <code className="font-mono">local:small</code>, and{' '}
                    <code className="font-mono">local:medium</code> (faster-whisper model sizes).
                  </p>
                </div>
              </section>

              {/* ── Language & limits ─────────────────────────────── */}
              <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Transcription
                </h2>

                <div className="grid gap-1.5">
                  <label htmlFor="voice-language" className="text-xs font-medium text-(--color-text-muted)">
                    Language
                  </label>
                  <Input
                    id="voice-language"
                    value={form.language}
                    onChange={(e) => setField('language', e.target.value)}
                    placeholder="auto"
                    className="min-h-11 font-mono text-sm md:min-h-9"
                  />
                  <p className="text-[11px] text-(--color-text-muted)">
                    <code className="font-mono">auto</code> lets Whisper detect the language.
                    Use a BCP-47 code to force a specific language —{' '}
                    e.g. <code className="font-mono">en</code>, <code className="font-mono">fr</code>,{' '}
                    <code className="font-mono">ja</code>.
                  </p>
                </div>

                <div className="grid gap-1.5">
                  <label htmlFor="voice-max-mb" className="text-xs font-medium text-(--color-text-muted)">
                    Max upload (MB)
                  </label>
                  <Input
                    id="voice-max-mb"
                    type="number"
                    min={1}
                    max={200}
                    value={form.max_file_mb}
                    onChange={(e) => {
                      const n = parseInt(e.target.value, 10)
                      if (!isNaN(n) && n > 0) setField('max_file_mb', n)
                    }}
                    className="min-h-11 w-28 font-mono text-sm md:min-h-9"
                  />
                  <p className="text-[11px] text-(--color-text-muted)">
                    Recordings larger than this are rejected before transcription.
                    A few minutes of compressed WebM audio is typically under 5 MB.
                  </p>
                </div>
              </section>

            </div>
          )}
        </div>
      </div>
    </>
  )
}
