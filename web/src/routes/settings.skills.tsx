/**
 * /settings/skills — inline list of skill packs in the detail pane.
 */
import { useParams } from '@tanstack/react-router'
import { Sparkles } from 'lucide-react'
import { useMemo } from 'react'

import { SettingsListView, type ListViewRow } from '@/components/settings/SettingsListView'
import { useSkillFilesQuery } from '@/queries'

export function SkillsListPage() {
  const { data, isLoading, isError } = useSkillFilesQuery()
  const { name: selected } = useParams({ strict: false }) as { name?: string }

  const rows = useMemo<ListViewRow[]>(
    () =>
      (data?.skills ?? []).map((s): ListViewRow => ({
        key: s.name,
        to: '/settings/skills/$name',
        params: { name: s.name },
        active: selected === s.name,
        title: s.name,
        description: s.built_in
          ? `${s.description || 'No description'} · Built-in`
          : s.description || 'No description',
        invalidReason: !s.valid ? (s.error ?? 'Invalid configuration') : undefined,
        trailing: (
          <span
            className="flex h-7 w-7 items-center justify-center rounded-md bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border)"
            aria-hidden="true"
          >
            <Sparkles size={13} />
          </span>
        ),
      })),
    [data?.skills, selected],
  )

  return (
    <SettingsListView
      title="Skills"
      description="Reusable instruction packs available to any agent. Triggered by the runtime based on user intent. Live in .openagentd/skills/."
      newTo="/settings/skills/new"
      newLabel="New skill"
      filterPlaceholder="Filter skills…"
      rows={rows}
      isLoading={isLoading}
      isError={isError}
      emptyTitle="No skills yet"
      emptyBody="Skills are reusable instruction modules agents load on demand via the skill tool."
    />
  )
}
