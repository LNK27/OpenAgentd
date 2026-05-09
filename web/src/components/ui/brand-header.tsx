/**
 * BrandHeader — sidebar brand row with mascot, Caveat title, and dock toggle.
 *
 * Pencil component `dtEOn` (BrandHeader):
 *   [mascot 44]  OpenAgentd                 [⫶]
 *                on-machine ai
 *
 * - Mascot 44×44 (image fill from /openagentd-app-icon.png)
 * - Title: font-hand (Caveat), 28px, weight 700, --color-text
 * - Subtitle: font-mono, 11px, --color-text-muted
 * - Dock toggle: 32×32 outlined button on the right
 * - Container: 64h, gap 12, padding 8×4
 *
 * Caveat is decorative chrome; the brand name is also conveyed by the
 * adjacent app icon and any document/page title, so screen readers will
 * still encounter "OpenAgentd" elsewhere.
 */

import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface BrandHeaderProps {
  /** Whether the sidebar is currently expanded; flips the dock-toggle icon. */
  expanded?: boolean
  onToggle?: () => void
  className?: string
  /** Skip the dock toggle (mobile sheet, etc.). */
  hideToggle?: boolean
}

export function BrandHeader({
  expanded = true,
  onToggle,
  hideToggle = false,
  className,
}: BrandHeaderProps) {
  const ToggleIcon = expanded ? PanelLeftClose : PanelLeftOpen

  return (
    <div
      className={cn(
        'flex h-16 items-center gap-3 px-1 py-2',
        className,
      )}
    >
      <img
        src="/brand/openagentd-app-icon.png"
        alt=""
        aria-hidden="true"
        className="h-11 w-11 shrink-0 select-none"
        draggable={false}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="font-hand text-[28px] font-bold leading-none text-(--color-text)">
          OpenAgentd
        </span>
        <span className="font-mono text-[11px] text-(--color-text-muted)">
          on-machine ai
        </span>
      </div>
      {!hideToggle && onToggle && (
        <button
          type="button"
          onClick={onToggle}
          aria-label={expanded ? 'Collapse sidebar' : 'Expand sidebar'}
          title={expanded ? 'Collapse sidebar' : 'Expand sidebar'}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm border border-(--color-border-subtle) text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
        >
          <ToggleIcon size={16} aria-hidden="true" />
        </button>
      )}
    </div>
  )
}
