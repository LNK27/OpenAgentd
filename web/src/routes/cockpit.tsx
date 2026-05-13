import { useRef, useEffect, useLayoutEffect } from 'react'
import { Outlet, useLocation, useParams, useNavigate } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { TeamChatView } from '@/components/TeamChatView'
import { getTeamSession } from '@/api/client'
import { useTeamStore } from '@/stores/useTeamStore'
import { applyCacheInvalidations, patchSessionTitle } from '@/stores/cache-invalidation-bridge'
import { queryKeys } from '@/queries'
import { findCodingWorkspaceById, loadLastCodingWorkspace, saveLastCodingWorkspace, shouldResetCodingWorkspaceSession, shouldRestoreLastCodingWorkspace, workspaceFromSessionDetail } from '@/utils/workspace'

/**
 * Layout route for /cockpit, /coding, and their session routes.
 * Stays mounted across URL changes — handles navigation when a new
 * team session_id arrives from POST /team/chat.
 */
function TeamLayoutBase({ forcedMode }: { forcedMode?: 'normal' | 'coding' }) {
  const params = useParams({ strict: false }) as Record<string, string>
  const sessionId = params.sessionId as string | undefined
  const location = useLocation()
  const search = location.search as Record<string, unknown>
  const mode = forcedMode ?? 'normal'
  const workspaceId = typeof search.w === 'string' ? search.w : null
  const workspaceFromKey = mode === 'coding' ? findCodingWorkspaceById(workspaceId) : null
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const workspaceRef = useRef<string | null>(null)
  const previousWorkspaceRef = useRef<string | null>(null)
  const sessionQuery = useQuery({
    queryKey: queryKeys.team.sessions.detail(sessionId ?? ''),
    queryFn: () => getTeamSession(sessionId as string),
    enabled: mode === 'coding' && Boolean(sessionId) && !workspaceFromKey,
    staleTime: 30_000,
  })
  const workspace = workspaceFromSessionDetail(mode, sessionId, workspaceFromKey, sessionQuery.data?.workspace)

  useEffect(() => {
    if (mode !== 'coding' || sessionId || workspaceId) return
    const restore = window.setTimeout(() => {
      if (!shouldRestoreLastCodingWorkspace(mode, sessionId, workspaceId, window.location.pathname)) return
      const lastWorkspace = loadLastCodingWorkspace()
      if (!lastWorkspace) return
      navigate({ to: '/coding', search: { w: lastWorkspace.id }, replace: true })
    }, 0)
    return () => window.clearTimeout(restore)
  }, [mode, navigate, sessionId, workspaceId])

  const navigateRef = useRef(navigate)
  const sessionIdRef = useRef(sessionId)
  const modeRef = useRef(mode)
  useEffect(() => {
    navigateRef.current = navigate
    sessionIdRef.current = sessionId
    modeRef.current = mode
    workspaceRef.current = workspace
  })

  useLayoutEffect(() => {
    if (shouldResetCodingWorkspaceSession(mode, sessionId, previousWorkspaceRef.current, workspace)) {
      previousWorkspaceRef.current = workspace
      useTeamStore.getState().newSession()
    }
  }, [mode, sessionId, workspace])

  // When team store gets a new sessionId, navigate to the matching session route.
  useEffect(() => {
    return useTeamStore.subscribe((state, prev) => {
      if (state.sessionId && state.sessionId !== prev.sessionId && !sessionIdRef.current) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.all() })
        void queryClient.refetchQueries({ queryKey: queryKeys.team.sessions.infinite(), type: 'active' })
        if (modeRef.current === 'coding') {
          const workspace = workspaceRef.current
          const entry = workspace ? saveLastCodingWorkspace(workspace) : null
          navigateRef.current({
            to: '/coding/$sessionId',
            params: { sessionId: state.sessionId },
            search: entry ? { w: entry.id } : undefined,
            replace: true,
          })
        } else {
          navigateRef.current({
            to: '/cockpit/$sessionId',
            params: { sessionId: state.sessionId },
            replace: true,
          })
        }
      }

      // When title_update arrives, patch the cached team session list
      // in-place — no re-fetch. See ``patchSessionTitle``.
      if (state.sessionTitle && state.sessionTitle !== prev.sessionTitle && state.sessionId) {
        patchSessionTitle(queryClient, state.sessionId, state.sessionTitle)
        void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.infinite() })
      }

      // Cache-invalidation bridge: the SSE reducer enqueues domain
      // events on ``cacheInvalidations`` (memory, workspace_files,
      // scheduler, todos) rather than calling
      // ``queryClient.invalidateQueries`` directly, so the store
      // stays free of TanStack imports.  Drain the queue and hand
      // the events to the bridge helper, which owns the mapping.
      if (state.cacheInvalidations !== prev.cacheInvalidations && state.cacheInvalidations.length > 0) {
        applyCacheInvalidations(queryClient, useTeamStore.getState()._drainCacheInvalidations())
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <>
      <TeamChatView sessionId={sessionId} mode={mode} workspace={workspace} />
      <Outlet />
    </>
  )
}

export function TeamLayout() {
  return <TeamLayoutBase />
}

export function CodingLayout() {
  return <TeamLayoutBase forcedMode="coding" />
}
