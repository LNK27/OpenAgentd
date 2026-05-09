/**
 * ViewToggle — three-state segmented control for chat view modes.
 *
 * Pencil component `T9nydm` (ViewToggle): single rounded pill, 1px subtle
 * border, three equally-sized icon buttons. The active button has a
 * `--color-surface-2` fill; others are transparent. The pencil uses
 * Material Symbols `person` / `view_column` / `view_quilt`; we map to
 * the lucide equivalents already used elsewhere in the codebase.
 *
 * Modes:
 *   - "agent"   → focus a single agent (Maximize2)
 *   - "split"   → side-by-side panes  (LayoutGrid)
 *   - "unified" → tabbed unified view (Layers)
 */

import { Maximize2, LayoutGrid, Layers, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

export type ViewMode = 'agent' | 'split' | 'unified'

interface ModeDef {
  mode: ViewMode
  label: string
  Icon: LucideIcon
}

const MODES: readonly ModeDef[] = [
  { mode: 'agent', label: 'Agent view', Icon: Maximize2 },
  { mode: 'split', label: 'Split view', Icon: LayoutGrid },
  { mode: 'unified', label: 'Unified view', Icon: Layers },
] as const

export interface ViewToggleProps {
  value: ViewMode
  onValueChange: (mode: ViewMode) => void
  /** Show text labels next to icons. Default true on desktop usage. */
  showLabels?: boolean
  className?: string
}

export function ViewToggle({
  value,
  onValueChange,
  showLabels = true,
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
              'inline-flex items-center justify-center gap-1.5 rounded-sm px-2.5 py-1 text-xs leading-none transition-all',
              selected
                ? 'bg-(--color-surface-2) text-(--color-text)'
                : 'text-(--color-text-muted) hover:text-(--color-text-2)',
            )}
          >
            <Icon size={12} aria-hidden="true" />
            {showLabels && <span className="capitalize">{mode}</span>}
          </button>
        )
      })}
    </div>
  )
}
