/**
 * Settings shell — responsive two-column layout.
 *
 * Desktop (≥768px):
 *   ┌──────────────┬─────────────────────────────┐
 *   │ ← Back        │                             │
 *   │               │                             │
 *   │ CONFIGURATION │  Detail / list / editor     │
 *   │ ▌ Agents  6   │  (rendered by route Outlet) │
 *   │   Skills 12   │                             │
 *   │   …           │                             │
 *   │ ABOUT         │                             │
 *   │   Telemetry   │                             │
 *   │   About       │                             │
 *   └──────────────┴─────────────────────────────┘
 *
 * Mobile (<768px): single column — the sidebar is replaced by the
 * settings hub at /settings, and detail routes render full-screen.
 *
 * The legacy three-column layout with a middle list column has been
 * replaced: list pages (agents/skills/MCP) now render cards inline in
 * the right pane via `SettingsListView`.
 */
import { Outlet, useLocation } from '@tanstack/react-router'

import { SettingsSidebar } from '@/components/settings/SettingsSidebar'
import { useIsMobile } from '@/hooks/use-mobile'

/** Returns true when the pathname points at a detail/editor route (not the list root). */
function isDetailRoute(pathname: string): boolean {
  return (
    pathname.startsWith('/settings/agents/') ||
    pathname.startsWith('/settings/skills/') ||
    pathname.startsWith('/settings/mcp/') ||
    pathname === '/settings/sandbox' ||
    pathname === '/settings/dream' ||
    pathname === '/settings/voice' ||
    pathname === '/settings'
  )
}

export function SettingsLayout() {
  const { pathname } = useLocation()
  const isMobile = useIsMobile()
  const onDetail = isDetailRoute(pathname)

  // Mobile layout: at /settings show the hub (which lists categories);
  // detail and list routes render full-screen via the Outlet.
  if (isMobile) {
    return (
      <div className="flex h-dvh flex-col overflow-hidden bg-(--bg-page) text-(--color-text)">
        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          {onDetail || pathname.startsWith('/settings/') ? (
            <Outlet />
          ) : (
            <Outlet />
          )}
        </main>
      </div>
    )
  }

  // Desktop layout: sidebar + outlet.
  return (
    <div className="flex h-dvh overflow-hidden bg-(--bg-page) text-(--color-text)">
      <SettingsSidebar />
      <main className="flex min-w-0 flex-1 flex-col">
        <Outlet />
      </main>
    </div>
  )
}
