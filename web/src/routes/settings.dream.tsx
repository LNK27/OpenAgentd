/**
 * /settings/dream — edit dream.md: the dream agent's prompt and schedule.
 *
 * dream.md uses the same frontmatter format as regular agent files (parsed
 * by the same YAML loader), with two additional dream-specific fields:
 *   - enabled:  whether the scheduler fires automatically
 *   - schedule: cron expression (UTC)
 *
 * The page parses the file using the shared splitFrontmatter helper so the
 * block-style tools list (- item per line) is handled correctly — matching
 * what the backend's yaml.safe_load produces and consumes.
 *
 * A "Run now" button triggers POST /api/dream/run immediately.
 */
import { useMemo, useState } from 'react'
import { ArrowLeft, Moon, Play, Save } from 'lucide-react'
import { Link } from '@tanstack/react-router'

import {
  useDreamConfigQuery,
  useUpdateDreamConfigMutation,
  useTriggerDreamMutation,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { useIsMobile } from '@/hooks/use-mobile'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { splitFrontmatter } from '@/components/settings/frontmatter'

// ── Types ─────────────────────────────────────────────────────────────────────

interface DreamForm {
  // Agent fields
  name: string
  /**
   * Role is always written as ``member`` (dream never leads a team) but we
   * preserve it on the form so a user who hand-edits the file to ``lead``
   * doesn't have their change silently dropped on save.  Read on parse,
   * defaulted to ``member`` on write.
   */
  role: string
  model: string
  tools: string[]
  // Dream-specific
  enabled: boolean
  schedule: string
}

const DEFAULT_FORM: DreamForm = {
  name: 'dream',
  role: 'member',
  model: '',
  tools: ['ls', 'read', 'write', 'edit', 'rm', 'wiki_search'],
  enabled: false,
  schedule: '0 2 * * *',
}

const DEFAULT_BODY = `You are the dream agent. Your job is to maintain a structured, interlinked wiki from unprocessed conversation sessions and notes.

Your working directory is the wiki root. Use relative paths directly:
- \`USER.md\` - pure YAML durable user facts
- \`INDEX.md\` - table of contents
- \`sources/{Source-Slug}.md\` - one summary per meaningful source
- \`topics/{slug}.md\` - concept pages
- \`entities/{slug}.md\` - people, tools, products, organizations
- \`comparisons/{slug}.md\` - X-vs-Y pages
- \`notes/{date}.md\` - read-only input; never edit notes

Each prompt begins with Today, Wiki state, and Source-Slug headers. Prefer editing existing pages listed in Wiki state over creating duplicates.

For each session/note you process:

1. Create or update \`sources/{Source-Slug}.md\` first for every meaningful source.

2. Update \`USER.md\` only if durable user facts were learned. Keep it pure YAML.

3. Create or update topic, entity, and comparison pages with required frontmatter:
   \`\`\`
   ---
   description: One-sentence summary (drives search relevance).
   tags: [tag1, tag2]
   updated: YYYY-MM-DD UTC
   confidence: high | medium | low
   sources:
     - <Source-Slug>
   related:
     - "[[related-slug]]"
   ---
   \`\`\`

4. Update related existing pages and \`INDEX.md\`.

Quality gate:
- Only promote durable facts worth remembering across sessions.
- Do not write noise, small talk, or one-off observations.
- If nothing worth promoting was found, do nothing.

Rules:
- Never edit \`notes/\` or \`LOG.md\`.
- Use surgical edits for existing pages.
- Write precise, query-friendly descriptions - they drive search relevance.`

// ── Parse / serialise ─────────────────────────────────────────────────────────

/**
 * Parse a raw dream.md string using the shared splitFrontmatter helper, then
 * walk the YAML lines to extract the form fields.  Uses the same block-list
 * format as agent .md files (- item per line).
 */
function parseDreamMd(raw: string): { form: DreamForm; body: string } {
  const { fm: fmText, body } = splitFrontmatter(raw)
  if (!fmText.trim()) return { form: { ...DEFAULT_FORM }, body: raw.trim() }

  const form = { ...DEFAULT_FORM }
  const lines = fmText.split('\n')
  let inTools = false
  const tools: string[] = []

  for (const rawLine of lines) {
    const line = rawLine.replace(/\s+$/, '')
    if (!line.trim() || line.trim().startsWith('#')) continue

    // Block-list item under tools:
    const listMatch = /^\s+-\s+(.+)$/.exec(line)
    if (inTools && listMatch) {
      tools.push(listMatch[1].trim())
      continue
    }
    inTools = false

    const kvMatch = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line)
    if (!kvMatch) continue
    const [, key, rawVal] = kvMatch
    const val = rawVal.trim().replace(/#.*$/, '').trim().replace(/^["']|["']$/g, '')

    switch (key) {
      case 'name':    form.name = val; break
      case 'role':    form.role = val; break
      case 'model':   form.model = val; break
      case 'enabled': form.enabled = val === 'true'; break
      case 'schedule': form.schedule = val; break
      case 'tools':
        // tools: (empty → block list follows)
        if (!val) { inTools = true }
        break
    }
  }

  if (tools.length > 0) form.tools = tools

  return { form, body: body.trim() }
}

/**
 * Serialise form fields back to canonical dream.md format:
 * - Uses block-style YAML lists (- item) matching the backend parser
 * - Tools sorted alphabetically (stable diffs)
 * - dream-specific fields (enabled, schedule) after agent fields
 */
function serialiseDreamMd(form: DreamForm, body: string): string {
  const lines: string[] = []
  lines.push(`name: ${form.name}`)
  // Preserve whatever role was in the parsed source.  Defaults to "member"
  // for fresh installs (DEFAULT_FORM) — matches the backend invariant that
  // dream is always a team member, never a lead.
  lines.push(`role: ${form.role || 'member'}`)
  if (form.model) lines.push(`model: ${form.model}`)
  lines.push(`enabled: ${form.enabled}`)
  lines.push(`schedule: "${form.schedule}"`)
  if (form.tools.length > 0) {
    lines.push('tools:')
    for (const t of [...form.tools].sort()) lines.push(`  - ${t}`)
  }
  return `---\n${lines.join('\n')}\n---\n\n${body.trim()}\n`
}

// ── Page component ────────────────────────────────────────────────────────────

export function DreamSettingsPage() {
  const isMobile = useIsMobile()
  const { data, isLoading, error } = useDreamConfigQuery()
  const updateMut = useUpdateDreamConfigMutation()
  const dreamMut = useTriggerDreamMutation()
  const push = useToastStore((s) => s.push)

  const [form, setForm] = useState<DreamForm>(DEFAULT_FORM)
  const [body, setBody] = useState(DEFAULT_BODY)
  const [sourceRaw, setSourceRaw] = useState('')

  // Rebase form onto server data when it changes (snapshot identity pattern)
  const serverRaw = data?.content ?? ''
  if (serverRaw !== sourceRaw) {
    const parsed = parseDreamMd(serverRaw)
    setForm(parsed.form)
    setBody(parsed.body)
    setSourceRaw(serverRaw)
  }

  const currentRaw = useMemo(() => serialiseDreamMd(form, body), [form, body])
  const dirty = currentRaw !== sourceRaw

  const handleSave = async () => {
    try {
      await updateMut.mutateAsync(currentRaw)
      setSourceRaw(currentRaw)
      push({ tone: 'success', title: 'Dream config saved' })
    } catch (err) {
      push({
        tone: 'error',
        title: 'Save failed',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  const handleRunNow = async () => {
    try {
      const result = await dreamMut.mutateAsync()
      push({
        tone: 'success',
        title: 'Dream run complete',
        description: `${result.sessions_processed} sessions, ${result.notes_processed} notes processed.`,
      })
    } catch (err) {
      push({
        tone: 'error',
        title: 'Dream run failed',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  const setField = <K extends keyof DreamForm>(key: K, val: DreamForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: val }))

  // Tools displayed as a comma-separated string in the input
  const toolsStr = form.tools.join(', ')
  const setTools = (raw: string) =>
    setField('tools', raw.split(',').map((s) => s.trim()).filter(Boolean))

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
        <Moon size={15} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
        <h1 className="flex-1 truncate text-sm font-semibold text-(--color-text)">Dream</h1>
        {dirty && (
          <span className="text-xs text-(--color-text-muted)" aria-live="polite">
            Unsaved
          </span>
        )}
        <Button
          size="sm"
          variant="outline"
          onClick={handleRunNow}
          disabled={dreamMut.isPending}
        >
          <Play size={12} aria-hidden="true" />
          {dreamMut.isPending ? 'Running…' : 'Run now'}
        </Button>
        <Button
          size="sm"
          onClick={handleSave}
          disabled={!dirty || updateMut.isPending}
        >
          <Save size={12} aria-hidden="true" />
          {updateMut.isPending ? 'Saving…' : 'Save'}
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-6 p-6">
          <p className="text-sm leading-relaxed text-(--color-text-muted)">
            The dream agent runs on a cron schedule and synthesises unprocessed conversation
            sessions and notes into wiki topics. Configure its schedule, model, and system prompt
            below, or click <strong>Run now</strong> to trigger it immediately.
          </p>

          {isLoading && <p className="text-sm text-(--color-text-muted)">Loading…</p>}
          {error && (
            <p className="text-sm text-(--color-error)">
              {error instanceof Error ? error.message : String(error)}
            </p>
          )}

          {!isLoading && !error && (
            <div className="space-y-5">
              {/* ── Schedule ────────────────────────────────────── */}
              <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Schedule
                </h2>

                <div className="flex items-center gap-3">
                  <label className="flex cursor-pointer items-center gap-2 text-sm text-(--color-text)">
                    <Switch
                      checked={form.enabled}
                      onCheckedChange={(checked) => setField('enabled', checked)}
                    />
                    Enabled
                  </label>
                  <span className="text-xs text-(--color-text-muted)">
                    When disabled, dream runs only via <em>Run now</em> or the Command Palette.
                  </span>
                </div>

                <div className="grid gap-1.5">
                  <label htmlFor="dream-schedule" className="text-xs font-medium text-(--color-text-muted)">
                    Cron expression
                  </label>
                  <Input
                    id="dream-schedule"
                    value={form.schedule}
                    onChange={(e) => setField('schedule', e.target.value)}
                    placeholder="0 2 * * *"
                    className="h-9 font-mono text-sm"
                  />
                  <p className="text-[11px] text-(--color-text-muted)">
                    Standard 5-field cron (UTC). Example: <code className="font-mono">0 2 * * *</code> = daily at 2 AM.
                  </p>
                </div>
              </section>

              {/* ── Model ───────────────────────────────────────── */}
              <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Model
                </h2>

                <div className="grid gap-1.5">
                  <label htmlFor="dream-model" className="text-xs font-medium text-(--color-text-muted)">
                    Model ID
                  </label>
                  <Input
                    id="dream-model"
                    value={form.model}
                    onChange={(e) => setField('model', e.target.value)}
                    placeholder="googlegenai:gemini-2.0-flash"
                    className="h-9 font-mono text-sm"
                  />
                  <p className="text-[11px] text-(--color-text-muted)">
                    Format: <code className="font-mono">provider:model-name</code>. Leave empty to skip LLM synthesis (infrastructure-only mode).
                  </p>
                </div>

                <div className="grid gap-1.5">
                  <label htmlFor="dream-tools" className="text-xs font-medium text-(--color-text-muted)">
                    Extra tools (comma-separated)
                  </label>
                  <Input
                    id="dream-tools"
                    value={toolsStr}
                    onChange={(e) => setTools(e.target.value)}
                    placeholder="ls, read, wiki_search, write"
                    className="h-9 font-mono text-sm"
                  />
                  <p className="text-[11px] text-(--color-text-muted)">
                    <code className="font-mono">read, write, edit, rm, ls, wiki_search</code> are always injected by the backend regardless of this list.
                  </p>
                </div>
              </section>

              {/* ── Prompt ──────────────────────────────────────── */}
              <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  System prompt
                </h2>

                <Textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  rows={20}
                  spellCheck={false}
                  className="resize-y font-mono text-sm leading-normal"
                  placeholder={DEFAULT_BODY}
                />
                <p className="text-[11px] text-(--color-text-muted)">
                  The dream agent receives each unprocessed session transcript and note as user messages. This prompt sets its behaviour and quality gates.
                </p>
              </section>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
