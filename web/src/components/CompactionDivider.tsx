/**
 * CompactionDivider — inline divider rendered when the summarisation hook
 * compacts the session's context window. Shows "Session compacting" while
 * the summariser LLM is running and flips to "Session compacted" on
 * completion. ``error`` surfaces a failed compaction.
 *
 * Rendered as a horizontal rule with centered text — the visual marker
 * lets users see where in the conversation context was trimmed.
 */

interface CompactionDividerProps {
  state: 'compacting' | 'compacted'
  error?: boolean
}

export function CompactionDivider({ state, error }: CompactionDividerProps) {
  const label = error
    ? 'Compaction failed'
    : state === 'compacting'
      ? 'Session compacting…'
      : 'Session compacted'

  const tone = error
    ? 'text-(--color-danger)'
    : state === 'compacting'
      ? 'text-(--color-text-subtle)'
      : 'text-(--color-text-2)'

  return (
    <div
      role="separator"
      aria-label={label}
      className="my-4 flex items-center gap-3"
    >
      <span className="h-px flex-1 bg-(--color-border)" aria-hidden />
      <span className={`font-mono text-xs uppercase tracking-wider ${tone}`}>
        {label}
        {state === 'compacting' && !error && (
          <span className="ml-1 inline-block animate-pulse">●</span>
        )}
      </span>
      <span className="h-px flex-1 bg-(--color-border)" aria-hidden />
    </div>
  )
}
