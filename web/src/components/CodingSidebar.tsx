/**
 * CodingSidebar — VSCode-explorer style workspace + session tree for
 * the ``/coding`` route. Mirrors the wireframe sidebar ``Q4zeZN`` in
 * ``.diagrams/OpenAgentd-ui.pen``:
 *
 *   • Search input at the top — opens the command palette (Ctrl+P).
 *   • Flat list of workspaces. Each row is a collapsible tree node:
 *       📁 · workspace label · `+` new
 *     Expanding a row reveals the nested coding sessions belonging
 *     to that workspace, with the same delete-on-hover affordance as
 *     the cockpit sidebar.
 *   • ``+ Open folder…`` row at the bottom of the workspace list
 *     surfaces the trusted-workspace dialog.
 *   • Footer trio: ⚙ Settings · ❔ Help (palette) · 🌙 ThemeToggle.
 *
 * The 64 px icon rail from the previous design is gone — workspace
 * navigation now lives inline so the sidebar matches the cockpit's
 * single-column shape. ``activeWorkspace`` is the workspace driving
 * the current chat (loaded from the route's ``w=`` search param);
 * ``expandedWorkspaces`` is local UI state for which tree nodes are
 * currently showing their sessions. Multiple workspaces can stay open
 * at once. Switching the active workspace auto-expands it.
 */
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { AnimatePresence, motion } from 'framer-motion'
import { useIsMobile } from '@/hooks/use-mobile'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import {
  Folder,
  HelpCircle,
  Loader2,
  Plus,
  Search,
  Settings,
  Trash2,
} from 'lucide-react'
import { useDeleteTeamSessionMutation, useTeamSessionsQuery } from '@/queries/useSessionsQuery'
import { browseWorkspaces, validateWorkspace } from '@/api/client'
import { useTeamStore } from '@/stores/useTeamStore'
import { formatRelativeDate } from '@/utils/format'
import {
  codingSessionSearch,
  loadCodingWorkspaceEntries,
  loadCodingWorkspaces,
  saveLastCodingWorkspace,
  workspaceLabel,
} from '@/utils/workspace'
import { ThemeToggle } from './ThemeToggle'
import { HealthDot } from './HealthDot'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { SessionResponse } from '@/api/types'

interface CodingSidebarProps {
  currentSessionId?: string
  workspace?: string | null
  onCollapse?: () => void
  /** Bump this counter to programmatically open the workspace dialog
   *  (e.g. from a "no workspace attached" CTA). */
  openWorkspaceDialogKey?: number
  /** Open the command palette (search input + footer help). */
  onCommandPalette?: () => void
  /** Desktop only: when true, the inline panel collapses to width=0. */
  desktopCollapsed?: boolean
  /** Mobile only: whether the overlay drawer is open. */
  mobileOpen?: boolean
  /** Mobile only: called when the drawer should close (backdrop tap, navigation). */
  onMobileClose?: () => void
}

export function CodingSidebar({
  currentSessionId,
  workspace,
  onCollapse,
  openWorkspaceDialogKey = 0,
  onCommandPalette,
  desktopCollapsed = false,
  mobileOpen = false,
  onMobileClose,
}: CodingSidebarProps) {
  const isMobile = useIsMobile()
  const prefersReducedMotion = useReducedMotion()
  // ``onCollapse`` is wired by TeamChatView's left-chrome hamburger.
  // We don't render an inline collapse toggle anymore — the topbar
  // hamburger and Ctrl+B own that surface.
  void onCollapse
  const navigate = useNavigate()
  const sessions = useTeamSessionsQuery()
  const deleteSession = useDeleteTeamSessionMutation()
  const isTeamWorking = useTeamStore((state) => state.isTeamWorking)

  const allSessions = sessions.data?.pages.flatMap((page) => page.data) ?? []
  const codingSessions = allSessions.filter(
    (session) => session.mode === 'coding' && session.workspace,
  )

  // Saved workspaces (localStorage) come first, sorted by creation time;
  // workspaces that only exist via session history are appended.
  const [workspaces, setWorkspaces] = useState<string[]>(() => loadCodingWorkspaces())
  const savedEntries = loadCodingWorkspaceEntries()
  const savedWorkspaceCreatedAt = new Map(
    savedEntries.map((entry) => [entry.path, Date.parse(entry.createdAt)]),
  )
  const savedWorkspaceTime = (path: string) => {
    const value = savedWorkspaceCreatedAt.get(path) ?? Number.MAX_SAFE_INTEGER
    return Number.isNaN(value) ? Number.MAX_SAFE_INTEGER : value
  }
  const savedWorkspaces = [...workspaces].sort((a, b) => savedWorkspaceTime(a) - savedWorkspaceTime(b))
  const sessionWorkspaces = Array.from(
    codingSessions.reduce((items, session) => {
      const path = session.workspace
      if (!path || savedWorkspaces.includes(path)) return items
      const createdAt = session.created_at ? Date.parse(session.created_at) : Number.MAX_SAFE_INTEGER
      const current = items.get(path)
      items.set(path, Math.min(current ?? Number.MAX_SAFE_INTEGER, Number.isNaN(createdAt) ? Number.MAX_SAFE_INTEGER : createdAt))
      return items
    }, new Map<string, number>()),
  )
    .sort(([, a], [, b]) => a - b)
    .map(([path]) => path)
  const visibleWorkspaces = [...savedWorkspaces, ...sessionWorkspaces]
  const activeWorkspace = workspace ?? null

  // ``expandedWorkspaces`` is local UI state — it auto-tracks the active
  // workspace but the user can also expand/collapse any other workspace
  // independently.
  const [expandedWorkspaces, setExpandedWorkspaces] = useState<Set<string>>(
    () => new Set(activeWorkspace ? [activeWorkspace] : []),
  )
  useEffect(() => {
    if (!activeWorkspace) return
    setExpandedWorkspaces((current) => {
      if (current.has(activeWorkspace)) return current
      const next = new Set(current)
      next.add(activeWorkspace)
      return next
    })
  }, [activeWorkspace])

  const toggleWorkspaceExpanded = (path: string) => {
    setExpandedWorkspaces((current) => {
      const next = new Set(current)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const [dialogOpen, setDialogOpen] = useState(false)
  const [browserPath, setBrowserPath] = useState<string | null>(null)
  const [parentPath, setParentPath] = useState<string | null>(null)
  const [dirs, setDirs] = useState<Array<{ name: string; path: string }>>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [pendingWorkspace, setPendingWorkspace] = useState<string | null>(null)
  const [trustWorkspace, setTrustWorkspace] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<SessionResponse | null>(null)

  const loadBrowser = useCallback(async (path?: string | null) => {
    setLoading(true)
    setError(null)
    try {
      const result = await browseWorkspaces(path)
      setBrowserPath(result.path)
      setParentPath(result.parent)
      setDirs(result.directories)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to read directory')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (dialogOpen && !browserPath) void loadBrowser(null)
  }, [dialogOpen, browserPath, loadBrowser])

  useEffect(() => {
    const handler = () => setWorkspaces(loadCodingWorkspaces())
    window.addEventListener('coding-workspaces-changed', handler)
    window.addEventListener('storage', handler)
    return () => {
      window.removeEventListener('coding-workspaces-changed', handler)
      window.removeEventListener('storage', handler)
    }
  }, [])

  useEffect(() => {
    if (openWorkspaceDialogKey > 0) setDialogOpen(true)
  }, [openWorkspaceDialogKey])

  useEffect(() => {
    if (pendingWorkspace && workspace === pendingWorkspace) setPendingWorkspace(null)
  }, [pendingWorkspace, workspace])

  const selectWorkspace = (path: string) => {
    const entry = saveLastCodingWorkspace(path)
    setPendingWorkspace(path)
    setWorkspaces(loadCodingWorkspaces())
    useTeamStore.getState().newSession()
    navigate({ to: '/coding', search: { w: entry.id } })
  }

  const openSelectedFolder = async () => {
    if (!browserPath) return
    try {
      const result = await validateWorkspace(browserPath)
      setTrustWorkspace(result.workspace)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Workspace is invalid')
    }
  }

  const confirmTrustedWorkspace = () => {
    if (!trustWorkspace) return
    const workspaceToOpen = trustWorkspace
    setTrustWorkspace(null)
    setDialogOpen(false)
    selectWorkspace(workspaceToOpen)
  }

  const handleSessionSelect = (session: SessionResponse, workspacePath: string) => {
    const search = codingSessionSearch(session.workspace, workspacePath)
    if (!search) return
    navigate({
      to: '/coding/$sessionId',
      params: { sessionId: session.id },
      search,
    })
    onMobileClose?.()
  }

  const handleSessionDelete = (e: React.MouseEvent, session: SessionResponse) => {
    e.stopPropagation()
    setDeleteTarget(session)
  }

  const confirmSessionDelete = () => {
    if (!deleteTarget) return
    deleteSession.mutate(deleteTarget.id)
    if (deleteTarget.id === currentSessionId) navigate({ to: '/coding' })
    setDeleteTarget(null)
  }

  return (
    <>
      {/* Mobile backdrop — closes the drawer on tap. */}
      <AnimatePresence>
        {isMobile && mobileOpen && (
          <motion.div
            key="coding-sidebar-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: prefersReducedMotion ? 0.01 : 0.2 }}
            className="fixed inset-0 z-30 bg-black/60 md:hidden"
            aria-hidden="true"
            onClick={onMobileClose}
          />
        )}
      </AnimatePresence>

    <motion.aside
      initial={false}
      animate={
        isMobile
          ? { x: mobileOpen ? 0 : -280 }
          : { width: desktopCollapsed ? 0 : 256 }
      }
      transition={{ duration: prefersReducedMotion ? 0.01 : 0.22, ease: [0.4, 0, 0.2, 1] }}
      className={
        isMobile
          ? 'fixed inset-y-0 left-0 z-40 flex w-[min(272px,calc(100vw-2rem))] shrink-0 flex-col overflow-hidden border-r border-(--color-border) bg-(--bg-page) shadow-xl'
          : 'flex shrink-0 flex-col overflow-hidden border-r border-(--color-border) bg-(--bg-page)'
      }
    >
      {/* Search trigger — opens the command palette (Ctrl+P). */}
      {onCommandPalette && (
        <div className="px-3 pt-3">
          <button
            type="button"
            onClick={onCommandPalette}
            className="flex h-8 w-full items-center gap-2 rounded-md border border-(--color-border) bg-(--bg-page) px-2.5 text-left text-xs text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
            aria-label="Open command palette"
            title="Open command palette (Ctrl+P)"
          >
            <Search size={13} aria-hidden="true" />
            <span className="flex-1">Search…</span>
            <kbd className="font-mono text-[10px] text-(--color-text-subtle)">^P</kbd>
          </button>
        </div>
      )}

      {/* Workspace + sessions tree */}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto pt-2">
        {visibleWorkspaces.length === 0 && (
          <p className="px-3 py-4 text-xs text-(--color-text-subtle)">
            No workspaces yet. Use “Open folder…” below to add one.
          </p>
        )}

        {visibleWorkspaces.map((path) => {
          const isActive = path === activeWorkspace
          const isExpanded = expandedWorkspaces.has(path)
          const isPending = pendingWorkspace === path
          const workspaceSessions = codingSessions.filter((s) => s.workspace === path)
          return (
            <div key={path} className="relative">
              {/* Workspace row */}
              <div className="group flex h-8 items-center pl-3 pr-2">
                <button
                  type="button"
                  onClick={() => toggleWorkspaceExpanded(path)}
                  className="flex min-w-0 flex-1 items-center gap-1.5 truncate rounded-md px-1.5 py-1 text-left text-xs transition-colors hover:bg-(--bg-key)"
                  aria-expanded={isExpanded}
                  aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${workspaceLabel(path)}`}
                  title={path}
                >
                  <Folder size={13} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
                  <span className={`truncate ${isActive ? 'font-semibold text-(--color-text)' : 'text-(--color-text-2)'}`}>
                    {workspaceLabel(path)}
                  </span>
                  {isPending && (
                    <Loader2 size={11} className="shrink-0 animate-spin text-(--color-text-muted)" aria-hidden="true" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => selectWorkspace(path)}
                  className="ml-1 flex h-5 w-5 shrink-0 items-center justify-center rounded border border-(--color-border) text-(--color-text-muted) opacity-0 transition-all hover:bg-(--bg-key) hover:text-(--color-text-2) group-hover:opacity-100"
                  aria-label={`New session in ${workspaceLabel(path)}`}
                  title={`New session in ${workspaceLabel(path)}`}
                >
                  <Plus size={11} aria-hidden="true" />
                </button>
              </div>

              {/* Nested sessions — only when expanded */}
              {isExpanded && (
                <div className="space-y-0.5 pb-2 pl-4 pr-2">
                  {workspaceSessions.length === 0 && (
                    <p className="px-2 py-1 text-xs text-(--color-text-subtle)">No sessions yet.</p>
                  )}
                  {workspaceSessions.map((session) => {
                    const isCurrent = session.id === currentSessionId
                    return (
                      <div key={session.id} className="group relative">
                        <button
                          type="button"
                          onClick={() => handleSessionSelect(session, path)}
                          className={`w-full rounded-md px-2 py-1.5 text-left text-xs transition-colors ${
                            isCurrent
                              ? 'bg-(--bg-key) text-(--color-text)'
                              : 'text-(--color-text-2) hover:bg-(--bg-key)'
                          }`}
                        >
                          <p className="truncate font-medium">{session.title || 'Untitled'}</p>
                          <p className="mt-0.5 truncate text-xs text-(--color-text-subtle)">
                            {formatRelativeDate(session.created_at)}
                          </p>
                          {isCurrent && isTeamWorking && (
                            <span
                              className="absolute right-7 top-1/2 -translate-y-1/2 text-(--color-accent)"
                              aria-label="Session running"
                            >
                              <Loader2 size={11} className="animate-spin" aria-hidden="true" />
                            </span>
                          )}
                        </button>
                        <button
                          type="button"
                          onClick={(e) => handleSessionDelete(e, session)}
                          className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 text-(--color-text-subtle) opacity-0 transition-all hover:bg-(--color-error-subtle) hover:text-(--color-error) group-hover:opacity-100"
                          aria-label={`Delete session ${session.title || 'Untitled'}`}
                        >
                          <Trash2 size={11} />
                        </button>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}

        {/* + Open folder… */}
        <button
          type="button"
          onClick={() => setDialogOpen(true)}
          className="mt-1 flex h-8 items-center gap-2 px-3 text-left text-xs italic text-(--color-accent) transition-colors hover:bg-(--bg-key)"
          aria-label="Open folder"
          title="Open a new workspace folder"
        >
          <Plus size={13} aria-hidden="true" />
          <span>Open folder…</span>
        </button>
      </div>

      {/* Footer trio — Settings · Help · HealthDot + ThemeToggle. Mirrors
          the cockpit sidebar so both feel like the same shell. */}
      <div className="flex items-center justify-between gap-2 border-t border-(--color-border) px-3 py-2 pb-safe">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => navigate({ to: '/settings' })}
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Settings"
            title="Settings"
          >
            <Settings size={14} aria-hidden="true" />
          </button>
          {onCommandPalette && (
            <button
              type="button"
              onClick={onCommandPalette}
              className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
              aria-label="Help and shortcuts"
              title="Help and shortcuts (Ctrl+P)"
            >
              <HelpCircle size={14} aria-hidden="true" />
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <HealthDot />
          <ThemeToggle collapsed />
        </div>
      </div>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open)
          if (!open) setTrustWorkspace(null)
        }}
      >
        <DialogContent showCloseButton={false}>
          {trustWorkspace ? (
            <>
              <DialogHeader>
                <DialogTitle>Trust this workspace?</DialogTitle>
                <DialogDescription>
                  Coding mode grants agents filesystem and shell access inside this exact directory.
                </DialogDescription>
              </DialogHeader>
              <div className="rounded-lg border border-(--color-border) bg-(--bg-page) px-3 py-2">
                <p className="break-all font-mono text-xs text-(--color-text-muted)">{trustWorkspace}</p>
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setTrustWorkspace(null)}>Back</Button>
                <Button type="button" onClick={confirmTrustedWorkspace}>Trust and open</Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>Open workspace</DialogTitle>
                <DialogDescription>Choose a server-local project folder.</DialogDescription>
              </DialogHeader>
              <div className="space-y-2">
                <div className="rounded-lg border border-(--color-border) bg-(--bg-page) px-3 py-2">
                  <p className="truncate font-mono text-xs text-(--color-text-muted)" title={browserPath ?? undefined}>
                    {browserPath ?? 'Loading folders…'}
                  </p>
                </div>
                <div className="max-h-64 space-y-1 overflow-y-auto rounded-lg border border-(--color-border) p-1">
                  {parentPath && (
                    <button
                      type="button"
                      className="w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-(--bg-key)"
                      onClick={() => void loadBrowser(parentPath)}
                    >
                      ..
                    </button>
                  )}
                  {loading && dirs.length === 0 && (
                    <p className="px-2 py-4 text-center text-xs text-(--color-text-subtle)">Loading folders…</p>
                  )}
                  {!loading && dirs.length === 0 && (
                    <p className="px-2 py-4 text-center text-xs text-(--color-text-subtle)">No folders here</p>
                  )}
                  {dirs.map((dir) => (
                    <button
                      type="button"
                      key={dir.path}
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-(--bg-key)"
                      onClick={() => void loadBrowser(dir.path)}
                    >
                      <Folder size={14} />
                      <span className="truncate">{dir.name}</span>
                    </button>
                  ))}
                </div>
                {error && <p className="text-xs text-(--color-error)">{error}</p>}
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
                <Button type="button" disabled={!browserPath || loading} onClick={openSelectedFolder}>Open this folder</Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete session</DialogTitle>
            <DialogDescription>
              &ldquo;{deleteTarget?.title || 'Untitled'}&rdquo; will be permanently deleted. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="p-3">
            <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button type="button" variant="destructive" onClick={confirmSessionDelete}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </motion.aside>
    </>
  )
}
