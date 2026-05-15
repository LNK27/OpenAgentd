/**
 * ViewToggle — two-state icon-only segmented control for chat view modes.
 *
 * Pencil component `T9nydm` (ViewToggle): equally-sized 28×28 icon-only
 * buttons inside a rounded-md pill bordered with `--color-border-subtle`.
 * The active button has a `--color-surface-2` fill; others are
 * transparent. Pencil uses Material Symbols `person` / `view_column`;
 * we map to the closest lucide equivalents to preserve semantics.
 *
 * Modes:
 *   - "agent" → focus a single agent (User    ↔ person)
 *   - "split" → side-by-side panes  (Columns2 ↔ view_column)
 *
 * Labels live on `aria-label` and `title` only — the control is too
 * dense to fit both labels on the topbar. Tooltips surface them on
 * hover for sighted users.
 */

import { User, Columns2, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

export type ViewMode = 'agent' | 'split'

interface ModeDef {
  mode: ViewMode
  label: string
  Icon: LucideIcon
}

const MODES: readonly ModeDef[] = [
  { mode: 'agent', label: 'Agent view', Icon: User },
  { mode: 'split', label: 'Split view', Icon: Columns2 },
] as const

export interface ViewToggleProps {
  value: ViewMode
  onValueChange: (mode: ViewMode) => void
  className?: string
}

export function ViewToggle({
  value,
  onValueChange,
  className,
}: ViewToggleProps) {
  return (
    <div
      role="radiogroup"
      aria-label="View mode"
      className={cn(
        'inline-flex items-center overflow-hidden rounded-md border border-(--color-border-subtle) p-0.5',
        className,
      )}
    >
      {MODES.map(({ mode, label, Icon }) => {
        const selected = value === mode
        return (
          <button
            key={mode}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={label}
            title={label}
            onClick={() => onValueChange(mode)}
            className={cn(
              'inline-flex h-7 w-7 items-center justify-center rounded-sm transition-colors',
              selected
                ? 'bg-(--color-surface-2) text-(--color-text)'
                : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text-2)',
            )}
          >
            <Icon size={14} aria-hidden="true" />
          </button>
        )
      })}
    </div>
  )
}
