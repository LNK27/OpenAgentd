/**
 * /settings/agents — inline list of agents in the detail pane.
 *
 * Agents live in two flat namespaces on disk:
 *   - .openagentd/agents/normal/<name>.md
 *   - .openagentd/agents/coding/<name>.md
 *
 * The backend exposes the relative path as the agent `name`, so a coding
 * agent surfaces as `coding/lead`. We split rows by that prefix and let
 * the user filter via the Normal/Coding tabs.
 */
import { useParams } from '@tanstack/react-router'
import { Crown, Wrench } from 'lucide-react'
import { useMemo, useState } from 'react'

import { SettingsListView, type ListViewRow } from '@/components/settings/SettingsListView'
import { cn } from '@/lib/utils'
import { useAgentFilesQuery } from '@/queries'

type ModeFilter = 'normal' | 'coding'

function ModeTabs({ value, onChange, counts }: {
  value: ModeFilter
  onChange: (next: ModeFilter) => void
  counts: { normal: number; coding: number }
}) {
  const tabs: Array<{ id: ModeFilter; label: string; count: number }> = [
    { id: 'normal', label: 'Normal', count: counts.normal },
    { id: 'coding', label: 'Coding', count: counts.coding },
  ]
  return (
    <div
      role="tablist"
      aria-label="Filter agents by mode"
      className="inline-flex h-8 items-center gap-1 rounded-lg border border-(--color-border) bg-(--bg-card) p-1"
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={value === tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            'flex h-6 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors',
            'focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-(--focus-ring)/40',
            value === tab.id
              ? 'bg-(--bg-key) text-(--color-text) ring-1 ring-(--color-border)'
              : 'text-(--color-text-muted) hover:text-(--color-text)',
          )}
        >
          {tab.label}
          <span className="font-mono text-[10px] tabular-nums opacity-70">{tab.count}</span>
        </button>
      ))}
    </div>
  )
}

export function AgentsListPage() {
  const { data, isLoading, isError } = useAgentFilesQuery()
  const { name: selected } = useParams({ strict: false }) as { name?: string }
  const [mode, setMode] = useState<ModeFilter>('normal')

  const counts = useMemo(() => {
    const agents = data?.agents ?? []
    return {
      normal: agents.filter((a) => !a.name.startsWith('coding/')).length,
      coding: agents.filter((a) => a.name.startsWith('coding/')).length,
    }
  }, [data?.agents])

  const rows = useMemo<ListViewRow[]>(() => {
    const agents = data?.agents ?? []
    const filtered = agents.filter((a) =>
      mode === 'coding' ? a.name.startsWith('coding/') : !a.name.startsWith('coding/'),
    )
    return filtered.map((a): ListViewRow => {
      const isLead = a.role === 'lead'
      return {
        key: a.name,
        to: '/settings/agents/$name',
        params: { name: a.name },
        active: selected === a.name,
        title: a.name.replace(/^coding\//, ''),
        badge: isLead ? 'lead' : undefined,
        description: a.description || a.model || 'No description',
        invalidReason: !a.valid ? (a.error ?? 'Invalid configuration') : undefined,
        trailing: (
          <span
            className="flex h-7 w-7 items-center justify-center rounded-md bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border)"
            aria-hidden="true"
          >
            {isLead ? <Crown size={13} /> : <Wrench size={13} />}
          </span>
        ),
      }
    })
  }, [data?.agents, mode, selected])

  return (
    <SettingsListView
      title="Agents"
      description="Markdown files with YAML frontmatter. Agents are scoped per mode — .openagentd/agents/normal/ and /coding/."
      newTo="/settings/agents/new"
      newLabel="New agent"
      filterPlaceholder="Filter agents…"
      tabs={<ModeTabs value={mode} onChange={setMode} counts={counts} />}
      rows={rows}
      isLoading={isLoading}
      isError={isError}
      emptyTitle="No agents yet"
      emptyBody="Define a team member with a model, tools, and a system prompt."
    />
  )
}
