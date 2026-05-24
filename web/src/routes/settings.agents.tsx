import { useParams } from '@tanstack/react-router'
import { Crown, Wrench } from 'lucide-react'
import { useMemo } from 'react'

import { SettingsListView, type ListViewRow } from '@/components/settings/SettingsListView'
import { useAgentFilesQuery } from '@/queries'

export function AgentsListPage() {
  const { data, isLoading, isError } = useAgentFilesQuery()
  const { name: selected } = useParams({ strict: false }) as { name?: string }

  const rows = useMemo<ListViewRow[]>(() => {
    const agents = data?.agents ?? []
    const normal = agents.filter((a) => !a.name.startsWith('coding/'))
    const coding = agents.filter((a) => a.name.startsWith('coding/'))

    const mapAgent = (a: (typeof agents)[number]): ListViewRow => {
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
    }

    return [
      ...(normal.length > 0
        ? [{ key: 'group-normal', kind: 'group' as const, title: 'Normal' }, ...normal.map(mapAgent)]
        : []),
      ...(coding.length > 0
        ? [{ key: 'group-coding', kind: 'group' as const, title: 'Coding' }, ...coding.map(mapAgent)]
        : []),
    ]
  }, [data?.agents, selected])

  return (
    <SettingsListView
      title="Agents"
      description="Markdown files with YAML frontmatter. Normal and Coding agents are grouped below; built-in OpenAgentd profiles use additive local overrides."
      newTo="/settings/agents/new"
      newLabel="New agent"
      filterPlaceholder="Filter agents…"
      rows={rows}
      isLoading={isLoading}
      isError={isError}
      emptyTitle="No agents yet"
      emptyBody="Define a team member with a model, tools, and a system prompt."
    />
  )
}
