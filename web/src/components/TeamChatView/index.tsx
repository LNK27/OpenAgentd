/**
 * TeamChatView — top-level layout for the team chat route.
 *
 * Owns:
 *   - View-mode state (``agent`` / ``split``).
 *   - Side panels (``Sidebar``, ``WorkspaceFilesPanel``, ``AgentCapabilities``,
 *     todos popover, command palette).
 *   - The header (token totals, view toggle, panel toggles, agent tabs).
 *   - Mount-time SSE connect + session restore (carefully sequenced so
 *     ``loadSession`` runs *before* ``connectStream`` to avoid wiping
 *     replayed mid-turn state — see comment inside the init effect).
 *   - Keyboard shortcuts and the Command Palette assembly.
 *
 * Delegates:
 *   - ``SplitGrid``       — fixed n-pane grid layout (split mode).
 *   - ``useTeamCommands`` — Command Palette command list.
 *
 * Stream subscriptions are split into the smallest selectors that work
 * (one primitive per ``useTeamStore`` call) to avoid the infinite loop
 * that returning a freshly-built object on every render would trigger.
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import OctobotMascot from '@/assets/brand/octobot-agentd-source.png'

import { Link, useNavigate } from '@tanstack/react-router'
import { AgentCapabilities } from '../AgentCapabilities'
import { AgentView } from '../AgentView'
import { CodingSidebar } from '../CodingSidebar'
import { CodingWorkspacePanel } from '../CodingWorkspacePanel'
import { Sidebar } from '../Sidebar'
import { CommandPalette } from '../CommandPalette'
import { WorkspaceFilesPanel } from '../WorkspaceFilesPanel'
import { TodosPopover } from '../TodosPopover'
import { WikiPanel } from '../WikiPanel'
import { SchedulerPanel } from '../SchedulerPanel'
import { useTodosQuery } from '@/queries/useTodosQuery'
import { useTriggerDreamMutation } from '@/queries'
import { useTeamStore } from '@/stores/useTeamStore'
import { useToastStore } from '@/stores/useToastStore'
import { useUIStore } from '@/stores/useUIStore'
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts'
import { useTeamAgentsQuery } from '@/queries/useAgentsQuery'
import { useSpeechConfigQuery } from '@/queries/useSpeechConfigQuery'
import { useFileRefsQuery } from '@/queries/useFileRefsQuery'
import { FolderOpen, FolderCode, Home, Menu } from 'lucide-react'
import { useIsMobile } from '@/hooks/use-mobile'
import { AgentChip } from '@/components/ui/agent-chip'
import { Button } from '@/components/ui/button'
import { isAgentRole } from '@/lib/agent-roles'
import { AgentTopbar } from '@/components/AgentTopbar'
import { type InputBarHandle, type SlashCommand } from '../InputBar'
import { FloatingInputBar } from '../FloatingInputBar'
import type { AgentCapabilities as AgentCapabilitiesType } from '@/api/types'
import { SplitGrid } from './SplitGrid'
import { useTeamCommands } from './useTeamCommands'
import { VIEW_MODES, type ViewMode } from './types'
import { saveCodingWorkspace } from '@/utils/workspace'

interface TeamChatViewProps {
  sessionId?: string
  mode?: 'normal' | 'coding'
  workspace?: string | null
}

export function TeamChatView({ sessionId, mode = 'normal', workspace = null }: TeamChatViewProps) {
  const navigate = useNavigate()
  const isMobile = useIsMobile()
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const inputRef = useRef<InputBarHandle>(null)
  const mainColumnRef = useRef<HTMLDivElement>(null)
  const [showAgentSidebar, setShowAgentSidebar] = useState(false)
  const [showFilesPanel, setShowFilesPanel] = useState(false)
  const [codingPanel, setCodingPanel] = useState<null | 'files' | 'diff'>(null)
  const [codingSidebarCollapsed, setCodingSidebarCollapsed] = useState(false)
  const [openWorkspaceDialogKey, setOpenWorkspaceDialogKey] = useState(0)
  const [showTodos, setShowTodos] = useState(false)
  const [showPalette, setShowPalette] = useState(false)
  const [viewMode, setViewMode] = useState<ViewMode>('agent')

  // On mobile, always force agent view — split/unified require a wide screen.
  // Also close any desktop-only panels when shrinking to mobile.
  const effectiveViewMode: ViewMode = isMobile ? 'agent' : viewMode
  useEffect(() => {
    if (isMobile) {
      setShowAgentSidebar(false)
      setShowFilesPanel(false)
    }
  }, [isMobile])

  const connectStream  = useTeamStore((s) => s.connectStream)
  const loadTeamStatus = useTeamStore((s) => s.loadTeamStatus)
  const loadSession    = useTeamStore((s) => s.loadSession)
  const sendMessage    = useTeamStore((s) => s.sendMessage)
  const newSession     = useTeamStore((s) => s.newSession)
  const cycleActiveAgent = useTeamStore((s) => s.cycleActiveAgent)
  const setActiveAgent   = useTeamStore((s) => s.setActiveAgent)

  const dreamMutation = useTriggerDreamMutation()
  const pushToast = useToastStore((s) => s.push)

  const activeAgent    = useTeamStore((s) => s.activeAgent)
  const agentStreams   = useTeamStore((s) => s.agentStreams)
  const agentNames     = useTeamStore((s) => s.agentNames)
  const isTeamWorking  = useTeamStore((s) => s.isTeamWorking)
  const sessionIdState = useTeamStore((s) => s.sessionId)
  const sessionTitle   = useTeamStore((s) => s.sessionTitle)
  const leadName       = useTeamStore((s) => s.leadName)

  // Wiki + Scheduler drawer state lives in useUIStore so the topbar (here)
  // and any future consumer can open/close them through the same path.
  const wikiOpen        = useUIStore((s) => s.wikiOpen)
  const schedulerOpen   = useUIStore((s) => s.schedulerOpen)
  const toggleWiki      = useUIStore((s) => s.toggleWiki)
  const toggleScheduler = useUIStore((s) => s.toggleScheduler)
  const closeWiki       = useUIStore((s) => s.closeWiki)
  const closeScheduler  = useUIStore((s) => s.closeScheduler)

  // Subscribe to active-agent stream fields directly to avoid recomputing on
  // every other agent's tick.
  const activeBlocks        = useTeamStore((s) => s.activeAgent ? s.agentStreams[s.activeAgent]?.blocks : undefined)
  const activeCurrentBlocks = useTeamStore((s) => s.activeAgent ? s.agentStreams[s.activeAgent]?.currentBlocks : undefined)
  const activeStatus        = useTeamStore((s) => s.activeAgent ? s.agentStreams[s.activeAgent]?.status : undefined)

  const splitAgentNames = agentNames.filter((name) => agentStreams[name]?.status !== 'offline')

  const { data: todosData } = useTodosQuery(sessionIdState)
  const todos = todosData?.todos ?? []

  // Lead capabilities — used to drive composer affordances (slash menu).
  const agentWorkspace = mode === 'coding' ? workspace : null
  const hasCodingWorkspace = mode !== 'coding' || Boolean(workspace)
  const { data: teamAgentsData, isLoading: teamAgentsLoading } = useTeamAgentsQuery(agentWorkspace, hasCodingWorkspace)
  const leadCapabilities: AgentCapabilitiesType | undefined = teamAgentsData?.agents
    ?.find((a) => a.is_lead)?.capabilities

  // Voice input — enabled flag from /api/speech/config.
  const { data: speechConfig } = useSpeechConfigQuery()
  const voiceEnabled = speechConfig?.enabled ?? false

  // Workspace file/folder list for the InputBar's @-mention picker. Fetched
  // lazily — the query is keyed on workspace/session so coding and normal
  // modes don't share cache entries.
  const { refs: fileRefs } = useFileRefsQuery({
    mode,
    sessionId: sessionIdState,
    workspace,
    enabled: mode === 'coding' ? Boolean(workspace) : Boolean(sessionIdState),
  })

  // Sum tokens — four primitive selectors, no new object returned (avoids infinite loop).
  const totalPrompt     = useTeamStore((s) => Object.values(s.agentStreams).reduce((n, st) => n + st.usage.promptTokens, 0))
  const totalCompletion = useTeamStore((s) => Object.values(s.agentStreams).reduce((n, st) => n + st.usage.completionTokens, 0))
  const totalCached     = useTeamStore((s) => Object.values(s.agentStreams).reduce((n, st) => n + st.usage.cachedTokens, 0))
  const totalAll        = useTeamStore((s) => Object.values(s.agentStreams).reduce((n, st) => n + st.usage.totalTokens, 0))

  const abortRef = useRef<AbortController | null>(null)

  // ── Init / reconnect ───────────────────────────────────────────────────────

  useEffect(() => {
    if (hasCodingWorkspace) loadTeamStatus(agentWorkspace)
    if (!sessionId) return
    const store = useTeamStore.getState()
    if (store.sessionId === sessionId && store.isConnected) return

    useTeamStore.setState({ sessionId })

    // Order matters: load prior-turn history FIRST, then open the SSE.
    //
    // Before this ordering, `connectStream()` started SSE replay (which
    // writes synthetic thinking/message events into `currentBlocks`)
    // while `loadSession()` was still inflight. When `loadSession`
    // resolved it unconditionally set `currentBlocks = []`, wiping the
    // replayed state. On mid-turn refresh the UI looked blank until the
    // next live chunk arrived — often until `done`.
    //
    // Awaiting the DB read first means `loadSession` has already committed
    // `blocks` and emptied `currentBlocks` by the time any SSE event is
    // dispatched, so replay + live events accumulate cleanly.
    let cancelled = false
    ;(async () => {
      await loadSession(sessionId, agentWorkspace)
      if (cancelled) return
      const controller = connectStream()
      if (controller) abortRef.current = controller
    })()

    return () => {
      cancelled = true
      abortRef.current?.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, agentWorkspace, hasCodingWorkspace])

  // ── Commands / shortcuts ───────────────────────────────────────────────────

  const handleNewSession = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    newSession()
    if (mode === 'coding' && workspace) {
      const entry = saveCodingWorkspace(workspace)
      navigate({ to: '/coding', search: { w: entry.id } })
    } else {
      navigate({ to: mode === 'coding' ? '/coding' : '/cockpit' })
    }
    requestAnimationFrame(() => inputRef.current?.focus())
  }, [mode, workspace, newSession, navigate])

  const handleWorkspaceFiles = useCallback(() => {
    if (mode === 'coding') {
      if (workspace) {
        setCodingPanel((value) => value === null ? 'files' : null)
      } else {
        setCodingSidebarCollapsed(false)
        setOpenWorkspaceDialogKey((value) => value + 1)
      }
      return
    }
    if (sessionIdState) setShowFilesPanel((value) => !value)
  }, [mode, workspace, sessionIdState])

  const handleCodingSidebarToggle = useCallback(() => {
    setCodingSidebarCollapsed((value) => !value)
  }, [])

  const handleOpenWorkspaceDialog = useCallback(() => {
    setCodingSidebarCollapsed(false)
    setOpenWorkspaceDialogKey((value) => value + 1)
  }, [])

  const handleDreamRun = useCallback(() => {
    dreamMutation.mutate(undefined, {
      onSuccess: (result) => {
        const { sessions_processed, notes_processed, remaining } = result
        const processed = sessions_processed + notes_processed
        pushToast({
          tone: 'success',
          title: 'Dream complete',
          description: processed > 0
            ? `${processed} item${processed !== 1 ? 's' : ''} processed. ${remaining} remaining.`
            : `Nothing to process.`,
        })
      },
      onError: (err) => {
        pushToast({
          tone: 'error',
          title: 'Dream failed',
          description: err instanceof Error ? err.message : String(err),
        })
      },
    })
  }, [dreamMutation, pushToast])

  // Focus the chat input. Callable directly (shortcut / Command Palette)
  // or indirectly via `window.dispatchEvent(new CustomEvent('focus-chat-input'))`
  // — the latter decouples future callers (buttons elsewhere, other views)
  // from this component's ref.
  const focusInput = useCallback(() => {
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    const handler = () => focusInput()
    window.addEventListener('focus-chat-input', handler)
    return () => window.removeEventListener('focus-chat-input', handler)
  }, [focusInput])

  // Slash commands for the input bar (type / to trigger)
  const slashCommands: SlashCommand[] = [
    { id: 'stop', label: 'Stop', description: 'Stop all working agents' },
    { id: 'new', label: 'New Chat', description: 'Start a fresh team conversation' },
  ]

  const handleSlashCommand = useCallback((id: string) => {
    switch (id) {
      case 'stop':
        useTeamStore.getState().stopTeam()
        break
      case 'new':
        handleNewSession()
        break
    }
  }, [handleNewSession])

  const cycleViewMode = useCallback(() => {
    setViewMode((v) => {
      const idx = VIEW_MODES.indexOf(v)
      return VIEW_MODES[(idx + 1) % VIEW_MODES.length]
    })
  }, [])

  const commands = useTeamCommands({
    viewMode,
    cycleViewMode,
    setViewMode,
    setShowAgentSidebar,
    setShowTodos,
    handleWorkspaceFiles,
    handleCodingSidebarToggle,
    mode,
    handleNewSession,
    handleDreamRun,
    agentNames,
    leadName,
    cycleActiveAgent,
    setActiveAgent,
    navigate,
  })

  useKeyboardShortcuts({
    n: handleNewSession,
    v: isMobile ? undefined : cycleViewMode,
    a: () => setShowAgentSidebar((v) => !v),
    f: handleWorkspaceFiles,
    t: () => { if (sessionIdState) setShowTodos((v) => !v) },
    p: isMobile ? undefined : () => setShowPalette((v) => !v),
    b: mode === 'coding' ? handleCodingSidebarToggle : undefined,
    // Ctrl+M / Ctrl+S — open the wiki / scheduler drawers (state in useUIStore).
    m: toggleWiki,
    s: toggleScheduler,
    // Ctrl+I — focus the chat input (dispatched via CustomEvent so future
    // callers don't need a ref to the input).
    'i': () => window.dispatchEvent(new CustomEvent('focus-chat-input')),
  })

  // Tab / Shift+Tab — cycle the active agent in the store (agent view tabs
  // and split-mode pane focus both follow store activeAgent).
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || e.ctrlKey || e.metaKey) return
      e.preventDefault()
      cycleActiveAgent(e.shiftKey ? 'prev' : 'next')
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [cycleActiveAgent])

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    // h-dvh: accounts for iOS Safari's dynamic toolbar (h-screen is too tall).
    // flex-col so the header spans the full viewport width and the sidebar
    // sits below it — matches the wireframe layout (header above the
    // sidebar/content row).
    <div className="flex h-dvh flex-col bg-(--bg-page)">
      {/* Header — full width, above both sidebar and content. */}
      <header className="flex items-center border-b border-(--color-border) bg-(--bg-page) py-0">

          {/* Home — pinned to a 56 px column so it sits vertically aligned
              with the collapsed sidebar (which is also 56 px wide). On
              mobile the column shrinks to the natural button size since
              the sidebar is a position:fixed overlay, not a column. */}
          <div className="flex h-full shrink-0 items-center justify-center md:w-14">
            <Link
              to="/"
              aria-label="Home"
              title="Home"
              className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            >
              <Home size={16} aria-hidden="true" />
            </Link>
          </div>

          {/* Hamburger + optional session title. ``gap-1`` keeps the two
              affordances tight; ``mr-2`` pushes content away on the right.
              Hamburger target depends on mode: coding sidebar toggle, mobile
              drawer, or a synthetic Ctrl+B for the normal sidebar (whose
              collapse state is owned by ``Sidebar``). */}
          <div className="mr-2 flex shrink-0 items-center gap-1 pl-2 md:pl-0">
            <button
              type="button"
              onClick={() => {
                if (mode === 'coding') {
                  setCodingSidebarCollapsed((v) => !v)
                } else if (isMobile) {
                  setMobileSidebarOpen(true)
                } else {
                  // Ctrl+B is owned by Sidebar's window listener.
                  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', ctrlKey: true, metaKey: false, bubbles: true }))
                }
              }}
              aria-label="Toggle sidebar"
              title="Toggle sidebar (Ctrl+B)"
              className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            >
              <Menu size={16} aria-hidden="true" />
            </button>
            {mode !== 'coding' && sessionTitle && (
              <span className="ml-1 max-w-60 truncate text-sm font-semibold text-(--color-text)" title={sessionTitle}>
                {sessionTitle}
              </span>
            )}
          </div>

          {/* Left: agent tabs (agent view) or unified tab strip */}
          <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
            {effectiveViewMode === 'agent' && agentNames.map((name) => {
              const stream = agentStreams[name]
              const isActive = activeAgent === name
              const isWorking = stream?.status === 'working'
              const isError = stream?.status === 'error'
              const isOffline = stream?.status === 'offline'

              // Override dot color when status diverges from idle.
              const dotClassName = isError
                ? 'bg-(--color-error)'
                : isWorking
                  ? 'animate-pulse bg-(--color-accent)'
                  : isOffline
                    ? 'bg-(--color-text-subtle) opacity-50'
                  : undefined

              if (isAgentRole(name)) {
                return (
                  <AgentChip
                    key={name}
                    role={name}
                    active={isActive}
                    onClick={() => setActiveAgent(name)}
                    dotClassName={dotClassName}
                    label={name === leadName ? `${name} ·` : undefined}
                  />
                )
              }

              return (
                <button
                  key={name}
                  onClick={() => setActiveAgent(name)}
                  className={`flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-all ${
                    isActive
                      ? 'bg-(--bg-key) text-(--color-accent)'
                      : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text-2)'
                  }`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${
                    isError ? 'bg-(--color-error)'
                    : isWorking ? 'animate-pulse bg-(--color-accent)'
                    : isOffline ? 'bg-(--color-text-subtle) opacity-50'
                    : 'bg-(--color-success)'
                  }`} />
                  {name}
                   {name === leadName && <span className="text-(--color-text-subtle)">·</span>}
                </button>
              )
            })}

            {effectiveViewMode === 'split' && (
              <span className="text-xs text-(--color-text-muted)">
                Split · {splitAgentNames.length} agents
              </span>
            )}
          </div>

          {/* Right: tokens, dream, split-pane, view toggle, panel toggles —
              owned by the reusable ``AgentTopbar`` composite so this header
              stays in sync with single-agent surfaces and Pencil's
              ``AgentTopbar`` (`E8lml9`). */}
          <AgentTopbar
            isMobile={isMobile}
            tokens={
              totalAll > 0
                ? {
                    input: totalPrompt,
                    output: totalCompletion,
                    cached: totalCached,
                    pulsing: isTeamWorking,
                  }
                : undefined
            }
            dreamRunning={dreamMutation.isPending}
            viewMode={viewMode}
            onViewModeChange={setViewMode}
            todosSlot={
              <TodosPopover
                open={showTodos}
                onOpenChange={setShowTodos}
                todos={todos}
                sessionId={sessionIdState}
              />
            }
            filesAction={mode === 'coding'
              ? workspace ? {
                  Icon: FolderOpen,
                  label: 'Files & Diff',
                  onClick: () => setCodingPanel('files'),
                  title: 'Workspace files and git diff',
                  ariaLabel: 'Workspace files and git diff',
                  className: 'mr-2',
                } : undefined
              : {
                  Icon: FolderOpen,
                  label: 'Files',
                  onClick: () => setShowFilesPanel((v) => !v),
                  disabled: !sessionIdState,
                  title: sessionIdState ? 'Workspace files (Ctrl+F)' : 'No active session',
                  ariaLabel: 'Workspace files',
                  className: 'mr-2',
                }}
          />
      </header>

      {/* Body row — sidebar (or coding rail) + main content column. On
          mobile the Sidebar is position:fixed (overlay drawer), so it
          takes no space here and the main column is always full-width. */}
      <div className="flex min-h-0 flex-1">
        {mode === 'coding' ? (
          !codingSidebarCollapsed && (
            <CodingSidebar
              currentSessionId={sessionIdState || undefined}
              workspace={workspace}
              onCollapse={() => setCodingSidebarCollapsed(true)}
              openWorkspaceDialogKey={openWorkspaceDialogKey}
              onCommandPalette={isMobile ? undefined : () => setShowPalette(true)}
            />
          )
        ) : (
          <Sidebar
            currentSessionId={sessionIdState || undefined}
            onCommandPalette={isMobile ? undefined : () => setShowPalette(true)}
            onNewChat={handleNewSession}
            mobileOpen={mobileSidebarOpen}
            onMobileClose={() => setMobileSidebarOpen(false)}
          />
        )}

        <div ref={mainColumnRef} className="relative flex min-w-0 flex-1 flex-col">
        {/* Content area */}
        {effectiveViewMode === 'split' && splitAgentNames.length > 0 ? (
          <div className="min-h-0 flex-1 p-3">
            <SplitGrid
              agentNames={splitAgentNames}
              leadName={leadName}
              agentStreams={agentStreams}
            />
          </div>
        ) : mode === 'coding' && workspace && teamAgentsLoading ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-(--color-border) border-t-(--color-accent)" />
            <div>
              <h2 className="text-sm font-medium text-(--color-text)">Opening coding workspace…</h2>
              <p className="mt-1 text-xs text-(--color-text-muted)">Preparing agents for {workspace}</p>
            </div>
          </div>
        ) : mode === 'coding' && !workspace ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-(--bg-key) text-(--color-accent)">
              <FolderCode size={24} />
            </div>
            <div>
              <h2 className="text-base font-medium text-(--color-text)">No workspace attached</h2>
              <p className="mt-1 max-w-sm text-sm text-(--color-text-muted)">
                Choose a local project folder from the sidebar to start a coding session.
              </p>
            </div>
            <Button type="button" onClick={handleOpenWorkspaceDialog}>
              Open workspace
            </Button>
          </div>
        ) : activeAgent && agentStreams[activeAgent] ? (
          <AgentView
            blocks={activeBlocks ?? agentStreams[activeAgent].blocks}
            currentBlocks={activeCurrentBlocks ?? agentStreams[activeAgent].currentBlocks}
            isWorking={(activeStatus ?? agentStreams[activeAgent].status) === 'working'}
            isError={(activeStatus ?? agentStreams[activeAgent].status) === 'error'}
            lastError={agentStreams[activeAgent].lastError}
          />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3">
            <img src={OctobotMascot} className="opacity-25 grayscale" width={64} height={64} alt="Idle octobot" />
            <p className="text-sm text-(--color-text-muted)">Select an agent above</p>
          </div>
        )}

        <FloatingInputBar
          ref={inputRef}
          boundsRef={mainColumnRef}
          onSubmit={(content, files) => sendMessage(content, files, { mode, workspace })}
          onStop={() => useTeamStore.getState().stopTeam()}
          onSlashCommand={handleSlashCommand}
          slashCommands={slashCommands}
          fileRefs={fileRefs}
          isStreaming={isTeamWorking}
          disabled={mode === 'coding' && !workspace}
          autoFocus={!sessionId}
          placeholder={
            dreamMutation.isPending
              ? 'Dream is running…'
              : isTeamWorking
                ? 'Team working… type to interrupt'
                : mode === 'coding' && workspace
                  ? `Coding in ${workspace}`
                  : mode === 'coding'
                    ? 'Choose a workspace to start coding…'
                    : 'Message the team…'
          }
          capabilities={leadCapabilities}
          voiceEnabled={voiceEnabled}
        />
        </div>
        {mode === 'coding' && workspace && (
          <CodingWorkspacePanel
            key={codingPanel ?? 'closed'}
            workspace={workspace}
            open={codingPanel !== null}
            initialTab={codingPanel ?? 'files'}
            onClose={() => setCodingPanel(null)}
          />
        )}
      </div>

      <AgentCapabilities
        open={showAgentSidebar}
        agentNames={agentNames}
        agentStreams={agentStreams}
        workspace={agentWorkspace}
        onClose={() => setShowAgentSidebar(false)}
      />
      <WorkspaceFilesPanel
        open={mode !== 'coding' && showFilesPanel}
        sessionId={sessionIdState}
        onClose={() => setShowFilesPanel(false)}
      />
      <WikiPanel open={wikiOpen} onClose={closeWiki} />
      <SchedulerPanel open={schedulerOpen} onClose={closeScheduler} />
      {!isMobile && showPalette && (
        <CommandPalette commands={commands} onClose={() => setShowPalette(false)} />
      )}
    </div>
  )
}
