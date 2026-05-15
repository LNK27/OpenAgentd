/**
 * AppHeader — shared 40 px application header rendered above any
 * route's content. The wireframe (.diagrams/OpenAgentd-ui.pen) shows
 * the same chrome on every screen: Home / hamburger on the left, page
 * title in the middle, status indicator on the right.
 *
 *   ┌──────────────────────────────────────────────────────────┐
 *   │ [⊕ ]  [🏠] [☰]  Settings                        ● local  │
 *   └──────────────────────────────────────────────────────────┘
 *      ↑
 *   macOS Tauri: 70 px left inset that the OS overlays with the
 *   close / minimize / maximize traffic-light buttons (configured via
 *   `trafficLightPosition` in `desktop/src-tauri/tauri.conf.json`).
 *   The buttons are 12 px tall; (40 − 12) / 2 = 14 px from the window
 *   top, which matches `y: 14` in tauri.conf.json — they're centered
 *   inside the 40 px header.
 *
 * Cross-platform behaviour
 * ────────────────────────
 * - **Browser**: plain 40 px bar. No drag handler, no inset.
 * - **Tauri Windows / Linux**: the OS keeps its native title bar
 *   (`decorations: true`), so the header sits beneath it. No special
 *   handling needed.
 * - **Tauri macOS** (`titleBarStyle: "Overlay"`, `hiddenTitle: true`):
 *   the `<header>` carries an `onMouseDown` handler from
 *   `useTauriDrag` that calls `window.startDragging()` only when the
 *   user pressed on the bare header (not on a child button). This
 *   sidesteps the `data-tauri-drag-region` footgun where mousedown on
 *   a drag-region container pre-empts child click handlers.
 *
 * Capability requirement
 * ──────────────────────
 * `window.startDragging()` only works when the window's capability
 * grants `core:window:allow-start-dragging` (see
 * `desktop/src-tauri/capabilities/default.json`). Without that
 * permission Tauri rejects the call silently.
 */
import { Link } from '@tanstack/react-router'
import { Home, Menu } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'

import { cn } from '@/lib/utils'
import { usePlatform } from '@/hooks/use-platform'
import { useTauriDrag } from '@/hooks/use-tauri-drag'

export interface AppHeaderProps {
  /** Title rendered to the right of the sidebar toggle. */
  title?: string
  /** Optional content rendered between the title and the right cluster. */
  center?: ReactNode
  /** Optional cluster pinned to the right (defaults to a small status pill). */
  right?: ReactNode
  /** Sidebar toggle handler. When omitted, the hamburger button is hidden. */
  onToggleSidebar?: () => void
  /** Shortcut hint shown in the toggle's tooltip — e.g. `'Ctrl+B'`. */
  toggleShortcut?: string
  /** Override the default Home link (`'/'`). */
  homeTo?: string
  /** Extra classes applied to the `<header>` element. */
  className?: string
}

/** Default status pill ("● local") — wireframe ``c7Afy`` / ``VEkqF``. */
function DefaultStatus() {
  return (
    <div className="flex items-center gap-1.5 pr-3 text-(--color-text-muted)">
      <span
        aria-hidden="true"
        className="h-2 w-2 rounded-full bg-(--color-success)"
      />
      <span className="font-mono text-[11px]">local</span>
    </div>
  )
}

export function AppHeader({
  title,
  center,
  right,
  onToggleSidebar,
  toggleShortcut,
  homeTo = '/',
  className,
}: AppHeaderProps) {
  const { isMacOverlay } = usePlatform()
  const dragHandlers = useTauriDrag()

  // Keep the platform attribute on `<html>` so any non-AppHeader code
  // path that needs to react to the mac-overlay condition can read it
  // without re-detecting.
  useEffect(() => {
    if (!isMacOverlay) return
    document.documentElement.setAttribute('data-platform', 'mac-overlay')
    return () => {
      document.documentElement.removeAttribute('data-platform')
    }
  }, [isMacOverlay])

  return (
    <header
      {...dragHandlers}
      className={cn(
        'relative z-30 flex h-(--spacing-app-header) shrink-0 items-center border-b border-(--color-border) bg-(--bg-page)',
        // Reserve room for the macOS traffic-light overlay.
        isMacOverlay && 'pl-(--spacing-mac-traffic-inset) select-none',
        className,
      )}
    >
      {/* ── Left cluster: Home + hamburger + title ─────────────── */}
      {/* ``pl-2`` (8 px) of breathing room after the macOS traffic-light
          inset; tighter than the default ``pl-3`` so the Home button
          doesn't read as drifting away from the inset. Other platforms
          use the same value for visual symmetry. */}
      <div className="flex shrink-0 items-center gap-1 pl-2">
        <Link
          to={homeTo}
          aria-label="Home"
          title="Home"
          className="flex h-7 w-7 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-(--focus-ring)/40"
        >
          <Home size={14} aria-hidden="true" />
        </Link>

        {onToggleSidebar && (
          <button
            type="button"
            onClick={onToggleSidebar}
            aria-label="Toggle sidebar"
            title={toggleShortcut ? `Toggle sidebar (${toggleShortcut})` : 'Toggle sidebar'}
            className="flex h-7 w-7 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-(--focus-ring)/40"
          >
            <Menu size={14} aria-hidden="true" />
          </button>
        )}

        {title && (
          <span className="ml-2 truncate text-sm font-semibold text-(--color-text)">
            {title}
          </span>
        )}
      </div>

      {/* ── Center slot ────────────────────────────────────────── */}
      <div className="flex min-w-0 flex-1 items-center">
        {center && <div className="min-w-0 flex-1">{center}</div>}
      </div>

      {/* ── Right cluster ─────────────────────────────────────── */}
      <div className="flex shrink-0 items-center">
        {right ?? <DefaultStatus />}
      </div>
    </header>
  )
}
