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
 * the current chat; ``expandedWorkspaces`` is local UI state for which tree nodes are
 * currently showing their sessions. Multiple workspaces can stay open
 * at once. Switching the active workspace auto-expands it.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { useIsMobile } from '@/hooks/use-mobile'
import { usePlatform } from '@/hooks/use-platform'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import {
  Folder,
  HelpCircle,
  Home,
  Loader2,
  Pencil,
  Plus,
  Search,
  Settings,
  Trash2,
} from 'lucide-react'
import { useCodingWorkspaceSessionsQuery, useDeleteTeamSessionMutation, useTeamSessionsQuery, useUpdateTeamSessionTitleMutation } from '@/queries/useSessionsQuery'
import { browseWorkspaces, resolveTeamSession, validateWorkspace } from '@/api/client'
import { useTeamStore } from '@/stores/useTeamStore'
import { prependSession, prependWorkspaceSession } from '@/stores/cache-invalidation-bridge'
import { formatRelativeDate } from '@/utils/format'
import {
  loadCodingWorkspaceEntries,
  loadCodingWorkspaces,
  removeCodingWorkspace,
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
import { LongPressButton } from '@/components/ui/long-press-button'

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

function WorkspaceSessionList({
  path,
  currentSessionId,
  runningSessions,
  collapsed = false,
  mobileLongPressActions = false,
  onSessionSelect,
  onSessionDelete,
  onSessionEdit,
  onSessionLongPress,
}: {
  path: string
  currentSessionId?: string
  runningSessions?: SessionResponse[]
  collapsed?: boolean
  mobileLongPressActions?: boolean
  onSessionSelect: (session: SessionResponse, workspacePath: string) => void
  onSessionDelete: (e: React.MouseEvent, session: SessionResponse) => void
  onSessionEdit: (session: SessionResponse) => void
  onSessionLongPress: (session: SessionResponse) => void
}) {
  const sessions = useCodingWorkspaceSessionsQuery(path, !collapsed)
  const workspaceSessions = collapsed
    ? (runningSessions ?? [])
    : (sessions.data?.pages.flatMap((page) => page.data) ?? [])

  return (
    <div className="space-y-0.5 pb-2 pl-4 pr-2">
      {workspaceSessions.length === 0 && !collapsed && !sessions.isLoading && (
        <p className="px-2 py-1 text-xs text-(--color-text-subtle)">No sessions yet.</p>
      )}
      {workspaceSessions.map((session) => {
        const isCurrent = session.id === currentSessionId
        const isRunning = session.running === true
        return (
          <div key={session.id} className="group relative">
            <LongPressButton
              enabled={mobileLongPressActions}
              onLongPress={() => onSessionLongPress(session)}
              type="button"
              onClick={() => onSessionSelect(session, path)}
              onDoubleClick={(e) => {
                e.stopPropagation()
                onSessionEdit(session)
              }}
              className={`w-full rounded-md px-2 py-1.5 text-left text-xs transition-colors ${
                isCurrent
                  ? 'bg-(--bg-key) text-(--color-text)'
                  : 'text-(--color-text-2) hover:text-(--color-text)'
              }`}
            >
              <p className="truncate font-medium">{session.title || 'Untitled'}</p>
              <p className="mt-0.5 truncate text-xs text-(--color-text-subtle)">
                {formatRelativeDate(session.created_at)}
              </p>
              {isRunning && (
                <span
                  className="absolute right-7 top-1/2 -translate-y-1/2 text-(--color-accent)"
                  aria-label="Session running"
                >
                  <Loader2 size={11} className="animate-spin" aria-hidden="true" />
                </span>
              )}
            </LongPressButton>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onSessionEdit(session)
              }}
              className="absolute right-6 top-1/2 -translate-y-1/2 rounded p-1 text-(--color-text-subtle) opacity-0 transition-all hover:bg-(--bg-key) hover:text-(--color-text) group-hover:opacity-100"
              aria-label={`Edit session ${session.title || 'Untitled'}`}
            >
              <Pencil size={11} />
            </button>
            <button
              type="button"
              onClick={(e) => onSessionDelete(e, session)}
              className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 text-(--color-text-subtle) opacity-0 transition-all hover:bg-(--color-error-subtle) hover:text-(--color-error) group-hover:opacity-100"
              aria-label={`Delete session ${session.title || 'Untitled'}`}
            >
              <Trash2 size={11} />
            </button>
          </div>
        )
      })}
      {!collapsed && sessions.hasNextPage && (
        <button
          type="button"
          onClick={() => { void sessions.fetchNextPage() }}
          disabled={sessions.isFetchingNextPage}
          className="mt-1 flex w-full items-center justify-center gap-1 rounded-md px-2 py-1.5 text-xs text-(--color-accent) transition-colors hover:bg-(--bg-key) disabled:cursor-not-allowed disabled:opacity-60"
        >
          {sessions.isFetchingNextPage && <Loader2 size={11} className="animate-spin" aria-hidden="true" />}
          <span>{sessions.isFetchingNextPage ? 'Loading…' : 'Load more'}</span>
        </button>
      )}
    </div>
  )
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
  const { isTauri, os } = usePlatform()
  const isTauriMobile = isTauri && (os === 'ios' || os === 'android')
  const mobileLongPressActions = isMobile && isTauriMobile && mobileOpen
  const prefersReducedMotion = useReducedMotion()
  // ``onCollapse`` is wired by TeamChatView's left-chrome hamburger.
  // We don't render an inline collapse toggle anymore — the topbar
  // hamburger and Ctrl+B own that surface.
  void onCollapse
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const sessions = useTeamSessionsQuery()
  const deleteSession = useDeleteTeamSessionMutation()
  const updateSessionTitle = useUpdateTeamSessionTitleMutation()

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
  const [selectedWorkspace, setSelectedWorkspace] = useState<string | null>(null)
  const [browserPath, setBrowserPath] = useState<string | null>(null)
  const [parentPath, setParentPath] = useState<string | null>(null)
  const [dirs, setDirs] = useState<Array<{ name: string; path: string }>>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [pendingWorkspace, setPendingWorkspace] = useState<string | null>(null)
  const [trustWorkspace, setTrustWorkspace] = useState<string | null>(null)
  const [editTarget, setEditTarget] = useState<SessionResponse | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const editTitleInputRef = useRef<HTMLInputElement>(null)
  const [deleteTarget, setDeleteTarget] = useState<SessionResponse | null>(null)
  const [mobileSessionActions, setMobileSessionActions] = useState<SessionResponse | null>(null)
  const [mobileWorkspaceActions, setMobileWorkspaceActions] = useState<string | null>(null)
  // Workspace pending removal — null when no confirmation is open. The
  // confirmation dialog reads this; ``confirmRemoveWorkspace`` commits.
  const [removeWorkspaceTarget, setRemoveWorkspaceTarget] = useState<string | null>(null)

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

  const openWebWorkspaceDialog = useCallback(() => {
    setSelectedWorkspace(null)
    setTrustWorkspace(null)
    setDialogOpen(true)
    if (!browserPath) void loadBrowser(null)
  }, [browserPath, loadBrowser])

  const openWorkspaceDialog = useCallback(async () => {
    setError(null)
    setSelectedWorkspace(null)
    setTrustWorkspace(null)

    if (!isTauri || isTauriMobile) {
      openWebWorkspaceDialog()
      return
    }

    setLoading(true)
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const selected = await open({
        directory: true,
        multiple: false,
        title: 'Open workspace',
      })
      if (typeof selected !== 'string') return
      setSelectedWorkspace(selected)
      const result = await validateWorkspace(selected)
      setTrustWorkspace(result.workspace)
      setDialogOpen(true)
    } catch (err) {
      setDialogOpen(true)
      setError(err instanceof Error ? err.message : 'Unable to open workspace')
    } finally {
      setLoading(false)
    }
  }, [isTauri, isTauriMobile, openWebWorkspaceDialog])

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
    if (openWorkspaceDialogKey > 0) void openWorkspaceDialog()
  }, [openWorkspaceDialogKey, openWorkspaceDialog])

  useEffect(() => {
    if (pendingWorkspace && workspace === pendingWorkspace) setPendingWorkspace(null)
  }, [pendingWorkspace, workspace])

  useEffect(() => {
    if (editTarget) editTitleInputRef.current?.focus()
  }, [editTarget])

  const selectWorkspace = async (path: string, opts: { create?: boolean } = {}) => {
    saveLastCodingWorkspace(path)
    setPendingWorkspace(path)
    setWorkspaces(loadCodingWorkspaces())
    try {
      const state = useTeamStore.getState()
      const create = opts.create && !(
        state.isEmptyIdleSession() &&
        state.sessionId === currentSessionId &&
        workspace === path
      )
      if (opts.create && !create) return
      const session = await resolveTeamSession({
        mode: 'coding',
        workspace: path,
        model: state.sessionModel,
        thinkingLevel: state.sessionThinkingLevel,
        create,
      })
      state.beginResolvedSession(session.id, {
        mode: 'coding',
        workspace: session.workspace ?? path,
        model: session.model ?? state.sessionModel,
        thinkingLevel: session.thinking_level ?? state.sessionThinkingLevel,
        skipInitialRestore: create && session.created,
      })
      if (create && session.created) {
        prependSession(queryClient, session)
        prependWorkspaceSession(queryClient, path, session)
      }
      navigate({ to: '/coding/$sessionId', params: { sessionId: session.id } })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create session')
    }
  }

  // Remove a workspace from the sidebar. Sessions stay in the backend —
  // reopening the same folder later resurfaces them. If the removed
  // workspace was the active one, navigate back to the empty /coding
  // route so the URL doesn't reference a workspace that no longer
  // appears in the sidebar. Called from the confirmation dialog below.
  const confirmRemoveWorkspace = () => {
    const path = removeWorkspaceTarget
    if (!path) return
    removeCodingWorkspace(path)
    setExpandedWorkspaces((current) => {
      if (!current.has(path)) return current
      const next = new Set(current)
      next.delete(path)
      return next
    })
    if (path === activeWorkspace) {
      navigate({ to: '/coding' })
    }
    setRemoveWorkspaceTarget(null)
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
    void selectWorkspace(workspaceToOpen)
  }

  const handleSessionSelect = (session: SessionResponse, workspacePath: string) => {
    if (session.workspace ?? workspacePath) saveLastCodingWorkspace(session.workspace ?? workspacePath)
    navigate({
      to: '/coding/$sessionId',
      params: { sessionId: session.id },
    })
    onMobileClose?.()
  }

  const handleSessionDelete = (e: React.MouseEvent, session: SessionResponse) => {
    e.stopPropagation()
    setDeleteTarget(session)
  }

  const handleSessionEdit = (session: SessionResponse) => {
    setEditTarget(session)
    setEditTitle(session.title || '')
  }

  const submitSessionTitle = (e: React.FormEvent) => {
    e.preventDefault()
    if (!editTarget) return
    const title = editTitle.trim()
    if (!title) return
    updateSessionTitle.mutate(
      { id: editTarget.id, title },
      { onSuccess: () => setEditTarget(null) },
    )
  }

  const confirmSessionDelete = () => {
    if (!deleteTarget) return
    const fallbackSession = deleteTarget.id === currentSessionId
      ? codingSessions.find((session) => session.id !== deleteTarget.id && session.workspace === deleteTarget.workspace)
        ?? codingSessions.find((session) => session.id !== deleteTarget.id)
      : null
    deleteSession.mutate(deleteTarget.id)
    if (deleteTarget.id === currentSessionId) {
      if (fallbackSession) {
        if (fallbackSession.workspace) saveLastCodingWorkspace(fallbackSession.workspace)
        navigate({
          to: '/coding/$sessionId',
          params: { sessionId: fallbackSession.id },
          replace: true,
        })
      } else {
        navigate({ to: '/coding', replace: true })
      }
    }
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
            className="mobile-safe-top fixed inset-x-0 bottom-0 z-30 bg-black/60 md:hidden"
            aria-hidden="true"
            onClick={onMobileClose}
          />
        )}
      </AnimatePresence>

    <motion.aside
      initial={false}
      animate={
        isMobile
          ? { x: mobileOpen ? 0 : -280, width: 'min(272px, calc(100vw - 2rem))' }
          : { width: desktopCollapsed ? 0 : 256 }
      }
      transition={{ duration: prefersReducedMotion ? 0.01 : 0.22, ease: [0.4, 0, 0.2, 1] }}
      className={
        isMobile
          ? 'mobile-safe-top fixed bottom-0 left-0 z-40 flex w-[min(272px,calc(100vw-2rem))] shrink-0 flex-col overflow-hidden border-r border-(--color-border) bg-(--bg-page) shadow-xl'
          : 'flex shrink-0 flex-col overflow-hidden border-r border-(--color-border) bg-(--bg-page)'
      }
    >
      {isMobile && (
        <nav aria-label="Primary" className="px-2 pt-3">
          <button
            type="button"
            onClick={() => { navigate({ to: '/' }); onMobileClose?.() }}
            className="flex h-9 w-full items-center gap-2 rounded-md px-2.5 text-left text-sm text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          >
            <Home size={15} aria-hidden="true" />
            <span>Home</span>
          </button>
        </nav>
      )}

      {/* Search trigger — opens the command palette (Ctrl+P). */}
      {onCommandPalette && (
        <div className={isMobile ? 'px-3 pt-3' : 'px-3 py-3'}>
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
          const runningSessions = workspaceSessions.filter((s) => s.running === true)
          const hasRunningSession = runningSessions.length > 0
          return (
            <div key={path} className="relative">
              {/* Workspace row */}
              <div className="group flex h-8 items-center pl-3 pr-2">
                <LongPressButton
                  enabled={mobileLongPressActions}
                  onLongPress={() => setMobileWorkspaceActions(path)}
                  type="button"
                  onClick={() => toggleWorkspaceExpanded(path)}
                  className="flex min-w-0 flex-1 items-center gap-1.5 truncate rounded-md px-1.5 py-1 text-left text-xs transition-colors"
                  aria-expanded={isExpanded}
                  aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${workspaceLabel(path)}`}
                  title={path}
                >
                  <Folder size={13} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
                  <span className={`truncate ${isActive ? 'font-semibold text-(--color-text)' : 'text-(--color-text-2) group-hover:text-(--color-text)'}`}>
                    {workspaceLabel(path)}
                  </span>
                  {(isPending || hasRunningSession) && (
                    <span aria-label={hasRunningSession ? 'Workspace has running session' : undefined}>
                      <Loader2 size={11} className="shrink-0 animate-spin text-(--color-text-muted)" aria-hidden="true" />
                    </span>
                  )}
                </LongPressButton>
                <button
                  type="button"
                  onClick={() => { void selectWorkspace(path, { create: true }) }}
                  className={`ml-1 flex h-5 w-5 shrink-0 items-center justify-center rounded border border-(--color-border) text-(--color-text-muted) transition-all hover:bg-(--bg-key) hover:text-(--color-text-2) ${isMobile ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
                  aria-label={`New session in ${workspaceLabel(path)}`}
                  title={`New session in ${workspaceLabel(path)}`}
                >
                  <Plus size={11} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => setRemoveWorkspaceTarget(path)}
                  className="ml-1 flex h-5 w-5 shrink-0 items-center justify-center rounded text-(--color-text-subtle) opacity-0 transition-all hover:bg-(--color-error-subtle) hover:text-(--color-error) group-hover:opacity-100"
                  aria-label={`Remove ${workspaceLabel(path)} from sidebar`}
                  title="Remove from sidebar"
                >
                  <Trash2 size={11} aria-hidden="true" />
                </button>
              </div>

              {/* Nested sessions — expanded list, or running sessions only when collapsed */}
              {(isExpanded || hasRunningSession) && (
                <WorkspaceSessionList
                  path={path}
                  currentSessionId={currentSessionId}
                  runningSessions={runningSessions}
                  collapsed={!isExpanded}
                  mobileLongPressActions={mobileLongPressActions}
                  onSessionSelect={handleSessionSelect}
                  onSessionDelete={handleSessionDelete}
                  onSessionEdit={handleSessionEdit}
                  onSessionLongPress={setMobileSessionActions}
                />
              )}
            </div>
          )
        })}

        {/* + Open folder… */}
        <button
          type="button"
          onClick={() => { void openWorkspaceDialog() }}
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
            onClick={() => { navigate({ to: '/settings' }); onMobileClose?.() }}
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
        <DialogContent showCloseButton={false} className="min-w-0">
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
          ) : isTauri && !isTauriMobile ? (
            <>
              <DialogHeader>
                <DialogTitle>Open workspace</DialogTitle>
                <DialogDescription>
                  Use the desktop folder picker to choose a local project folder.
                </DialogDescription>
              </DialogHeader>
              <div className="min-w-0 space-y-2">
                {selectedWorkspace && (
                  <div className="min-w-0 rounded-lg border border-(--color-border) bg-(--bg-page) px-3 py-2">
                    <p className="min-w-0 font-mono text-xs text-(--color-text-muted) [overflow-wrap:anywhere]" title={selectedWorkspace}>
                      {selectedWorkspace}
                    </p>
                  </div>
                )}
                {error && <p className="text-xs text-(--color-error)">{error}</p>}
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
                <Button type="button" disabled={loading} onClick={() => { void openWorkspaceDialog() }}>
                  {loading ? 'Opening…' : 'Choose folder…'}
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>Open workspace</DialogTitle>
                <DialogDescription>Choose a server-local project folder.</DialogDescription>
              </DialogHeader>
              <div className="min-w-0 space-y-2">
                <div className="min-w-0 rounded-lg border border-(--color-border) bg-(--bg-page) px-3 py-2">
                  <p className="min-w-0 font-mono text-xs text-(--color-text-muted) [overflow-wrap:anywhere]" title={browserPath ?? undefined}>
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
                      className="flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-(--bg-key)"
                      onClick={() => void loadBrowser(dir.path)}
                    >
                      <Folder size={14} className="shrink-0" />
                      <span className="min-w-0 truncate">{dir.name}</span>
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
        open={mobileWorkspaceActions !== null}
        onOpenChange={(open) => { if (!open) setMobileWorkspaceActions(null) }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{mobileWorkspaceActions ? workspaceLabel(mobileWorkspaceActions) : 'Workspace actions'}</DialogTitle>
            <DialogDescription>Choose a workspace action.</DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col items-stretch gap-2 p-3 sm:flex-col">
            <Button
              type="button"
              variant="outline"
              className="justify-start"
              onClick={() => {
                const path = mobileWorkspaceActions
                setMobileWorkspaceActions(null)
                if (path) void selectWorkspace(path, { create: true })
              }}
            >
              <Plus size={14} aria-hidden="true" />
              New session
            </Button>
            <Button
              type="button"
              variant="outline"
              className="justify-start text-(--color-error)"
              onClick={() => {
                const path = mobileWorkspaceActions
                setMobileWorkspaceActions(null)
                if (path) setRemoveWorkspaceTarget(path)
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
              Remove from sidebar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={mobileSessionActions !== null}
        onOpenChange={(open) => { if (!open) setMobileSessionActions(null) }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{mobileSessionActions?.title || 'Untitled'}</DialogTitle>
            <DialogDescription>Choose a session action.</DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col items-stretch gap-2 p-3 sm:flex-col">
            <Button
              type="button"
              variant="outline"
              className="justify-start"
              onClick={() => {
                const session = mobileSessionActions
                setMobileSessionActions(null)
                if (session) handleSessionEdit(session)
              }}
            >
              <Pencil size={14} aria-hidden="true" />
              Edit title
            </Button>
            <Button
              type="button"
              variant="outline"
              className="justify-start text-(--color-error)"
              onClick={() => {
                const session = mobileSessionActions
                setMobileSessionActions(null)
                if (session) setDeleteTarget(session)
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
              Delete session
            </Button>
          </DialogFooter>
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

      <Dialog
        open={editTarget !== null}
        onOpenChange={(open) => { if (!open) setEditTarget(null) }}
      >
        <DialogContent showCloseButton={false}>
          <form onSubmit={submitSessionTitle}>
            <DialogHeader>
              <DialogTitle>Edit session title</DialogTitle>
              <DialogDescription>
                Rename this session in the sidebar.
              </DialogDescription>
            </DialogHeader>
            <div className="px-3 py-2">
              <input
                ref={editTitleInputRef}
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                className="h-9 w-full min-w-0 rounded-[10px] border border-(--color-border) bg-(--bg-page) px-3 py-1 text-sm text-(--color-text) outline-none focus-visible:border-(--focus-ring) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25"
                aria-label="Session title"
                maxLength={255}
              />
              {updateSessionTitle.isError && (
                <p className="mt-2 text-xs text-(--color-error)">Failed to update title.</p>
              )}
            </div>
            <DialogFooter className="p-3">
              <Button type="button" variant="outline" onClick={() => setEditTarget(null)}>Cancel</Button>
              <Button type="submit" disabled={!editTitle.trim() || updateSessionTitle.isPending}>
                {updateSessionTitle.isPending ? 'Saving…' : 'Save'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={removeWorkspaceTarget !== null}
        onOpenChange={(open) => { if (!open) setRemoveWorkspaceTarget(null) }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Remove workspace from sidebar</DialogTitle>
            <DialogDescription>
              &ldquo;{removeWorkspaceTarget ? workspaceLabel(removeWorkspaceTarget) : ''}&rdquo; will be hidden from
              the sidebar. Its sessions stay on disk — reopening this folder later restores the list.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="p-3">
            <Button type="button" variant="outline" onClick={() => setRemoveWorkspaceTarget(null)}>Cancel</Button>
            <Button type="button" variant="destructive" onClick={confirmRemoveWorkspace}>Remove</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </motion.aside>
    </>
  )
}
