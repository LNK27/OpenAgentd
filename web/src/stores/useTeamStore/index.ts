/**
 * Team chat Zustand store.
 *
 * Owns the live state for the team chat route: per-agent streams,
 * session id/title, working flag, the SSE abort controller, and the
 * pending-message queue.  Public actions are split between session
 * lifecycle (``sendMessage``, ``stopTeam``, ``connectStream``,
 * ``loadTeamStatus``, ``loadSession``, ``newSession``) and small UI
 * accessors (``setActiveAgent``, ``cycleActiveAgent``, ``toggleSidebar``).
 *
 * The bulk of streaming logic — one switch case per SSE event type —
 * lives in ``./sse-reducer.ts`` to keep this file focused on store
 * assembly.  Helpers, types, and defaults live in their own modules.
 *
 * The public import path ``@/stores/useTeamStore`` resolves to this
 * file via folder-with-index, so consumers don't need updating.
 */
import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { postTeamChat, postTeamCommand, teamStream, teamStatus, teamHistory } from '@/api/client'
import { parseTeamBlocks, sumUsageFromMessages } from '@/utils/messages'
import { createDefaultAgentStream } from './defaults'
import { applyRevertBoundary, revokeBlobUrlsFromBlocks } from './helpers'
import { createSSEHandler } from './sse-reducer'
import { useToastStore } from '@/stores/useToastStore'
import type { TeamStore } from './types'
import type { MessageResponse } from '@/api/types'

function revertBoundaryTime(session: { revert?: { message_id?: string } | null; messages: MessageResponse[] }): number | null {
  const boundaryId = session.revert?.message_id
  if (!boundaryId) return null
  const boundary = session.messages.find((msg) => msg.id === boundaryId)
  return boundary?.created_at ? new Date(boundary.created_at).getTime() : null
}

function messagesBeforeTime(messages: MessageResponse[], boundaryTime: number | null): MessageResponse[] {
  if (boundaryTime === null) return messages
  return messages.filter((msg) => {
    if (!msg.created_at) return true
    return new Date(msg.created_at).getTime() < boundaryTime
  })
}

function messagesBeforeRevert(session: { revert?: { message_id?: string } | null; messages: MessageResponse[] }): MessageResponse[] {
  return messagesBeforeTime(session.messages, revertBoundaryTime(session))
}

// Re-export types so existing ``import type { AgentStream } from
// '@/stores/useTeamStore'`` consumers keep working.
export type {
  AgentStream,
  CacheInvalidation,
  PendingMessage,
  TeamStoreState,
  TeamStoreActions,
  TeamStore,
} from './types'

/**
 * Flatten the server's ``ChangedPaths`` envelope into a single,
 * deduped list. Returns ``undefined`` when the server didn't supply
 * the envelope (legacy / non-snapshot path) so the caller falls
 * back to broad invalidation.
 */
function mergeChangedPaths(
  changed: { added: string[]; modified: string[]; removed: string[] } | undefined,
): string[] | undefined {
  if (!changed) return undefined
  const seen = new Set<string>()
  for (const p of changed.added) seen.add(p)
  for (const p of changed.modified) seen.add(p)
  for (const p of changed.removed) seen.add(p)
  return [...seen]
}

/**
 * Push a workspace cache-invalidation event after a /undo or /redo.
 *
 * When the server reports which paths the snapshot restore actually
 * touched (``changed_paths`` — added/modified/removed), we drive a
 * *scoped* ``coding_workspace_paths`` event so the bridge can splice
 * a per-path git diff into the cached one instead of refetching the
 * whole repo (~30 ms saved on 30k files). When no paths changed
 * (e.g. /redo cleared the boundary but the workspace already matched
 * the live tip) we skip invalidation entirely.
 *
 * When ``paths`` is omitted (server didn't supply ``changed_paths``,
 * or we're in normal session-keyed mode), fall back to the broad
 * invalidation kinds — coding mode targets the absolute workspace
 * path; normal mode keys by sessionId.
 */
function enqueueWorkspaceInvalidation(
  set: (fn: (draft: TeamStore) => void) => void,
  get: () => TeamStore,
  sessionId: string,
  paths?: string[],
) {
  const workspace = get()._workspace
  if (workspace && paths !== undefined) {
    // Empty list = no filesystem change; skip the invalidation to
    // avoid an unnecessary diff/files refetch.
    if (paths.length === 0) return
    set((draft) => {
      draft.cacheInvalidations.push({
        kind: 'coding_workspace_paths',
        workspace,
        paths,
      })
    })
    return
  }
  set((draft) => {
    draft.cacheInvalidations.push(
      workspace
        ? { kind: 'coding_workspace', workspace }
        : { kind: 'workspace_files', sessionId },
    )
  })
}

export const useTeamStore = create<TeamStore>()(
  immer((set, get) => ({
    // State
    agentStreams: {},
    activeAgent: null,
    leadName: null,
    agentNames: [],
    liveAgentNames: null,
    sidebarOpen: false,
    sessionId: null,
    sessionTitle: null,
    isTeamWorking: false,
    isContinuing: false,
    isConnected: false,
    error: null,
    setupRequired: null,
    _pendingMessages: [],
    _abortController: null,
    _sessionGeneration: 0,
    cacheInvalidations: [],
    hasMore: false,
    nextCursor: null,
    _leadRevertTime: null,
    _workspace: null,
    _loadingOlder: false,

    newSession: () => {
      get()._abortController?.abort()
      set((state) => {
        const leadName = state.leadName ?? state.agentNames[0] ?? null
        state.sessionId = null
        state.sessionTitle = null
        state.isTeamWorking = false
        state.isContinuing = false
        state.isConnected = false
        state.error = null
        state.setupRequired = null
        state._abortController = null
        state._pendingMessages = []
        state._sessionGeneration = (state._sessionGeneration ?? 0) + 1
        // Drop any pending cache invalidations from the previous
        // session — workspace_files / todos events are session-keyed
        // and would target the wrong cache after the reset.
        state.cacheInvalidations = []
        state._pendingMessages = []
        state.hasMore = false
        state.nextCursor = null
        state._leadRevertTime = null
        state._workspace = null
        state._loadingOlder = false
        // A fresh chat starts with only the lead. Historical member streams can
        // remain cached for prior sessions, but they must not stay in the live roster.
        state.agentNames = leadName ? [leadName] : []
        state.liveAgentNames = leadName ? [leadName] : null
        state.activeAgent = leadName ?? null

        // Reset the lead and drop member streams. A fresh chat gets a fresh
        // team roster; prior session members reload from history on demand.
        Object.keys(state.agentStreams).forEach((name) => {
          if (name !== leadName) {
            delete state.agentStreams[name]
            return
          }
          state.agentStreams[name].blocks = []
          state.agentStreams[name].currentBlocks = []
          state.agentStreams[name].currentText = ''
          state.agentStreams[name].currentThinking = ''
          state.agentStreams[name].status = 'idle'
          state.agentStreams[name].lastError = null
          state.agentStreams[name].usage = { promptTokens: 0, completionTokens: 0, totalTokens: 0, cachedTokens: 0 }
          state.agentStreams[name]._completionBase = 0
          state.agentStreams[name].revertedCount = 0
          state.agentStreams[name].revertedMessages = []
          state.agentStreams[name]._revertedSuffix = []
        })
      })
    },

    sendMessage: async (content: string, files?: File[], options?: { mode?: string; workspace?: string | null }) => {
      const { leadName, agentStreams } = get()
      const leadWorking = leadName ? agentStreams[leadName]?.status === 'working' : false

      // Only queue if the lead is busy. Members running in the background
      // (e.g. sub-tasks) don't block the user from sending a new message.
      if (leadWorking) {
        set((draft) => {
          draft._pendingMessages.push({ id: `pm-${Date.now()}`, content, files })
          draft.error = null
        })
        return
      }

      get()._abortController?.abort()

      // Build optimistic attachments from files for immediate display
      const optimisticAttachments = files?.map((f) => ({
        original_name: f.name,
        media_type: f.type,
        category: (f.type.startsWith('image/') ? 'image' : 'document') as 'image' | 'document' | 'text',
        url: f.type.startsWith('image/') ? URL.createObjectURL(f) : undefined,
      }))

      set((draft) => {
          draft.isTeamWorking = true
          draft.isContinuing = false
          draft.error = null
          draft.setupRequired = null
        // The backend's ``cleanup_reverted_tail`` deletes post-boundary
        // rows the moment a new user message lands, so any
        // locally-stashed revert suffix is now stale — clear it on
        // every agent stream so a stray /redo doesn't resurrect dead
        // blocks. Also drop ``_leadRevertTime`` for the same reason:
        // the boundary is gone server-side.
        draft._leadRevertTime = null
        Object.values(draft.agentStreams).forEach((stream) => {
          stream._revertedSuffix = []
          stream.revertedCount = 0
          stream.revertedMessages = []
        })
        // Push user message as an optimistic block into the lead's stream.
        if (leadName && draft.agentStreams[leadName]) {
          draft.agentStreams[leadName].currentBlocks.push({
            id: `user-${Date.now()}`,
            type: 'user',
            content,
            timestamp: new Date(),
            attachments: optimisticAttachments,
          })
        }
      })

      try {
        const result = await postTeamChat(
          content,
          get().sessionId,
          false,
          files,
          options?.mode ?? 'normal',
          options?.workspace ?? null,
        )
        set((draft) => {
          draft.sessionId = result.session_id
          // Persist the coding-mode workspace on the store *before*
          // ``connectStream`` opens the SSE feed. Tool events fire as
          // soon as the lead starts working; without this, the first
          // turn's ``tool_end`` reducer sees ``_workspace = null`` and
          // emits a session-scoped ``workspace_files`` event instead
          // of the coding-mode key, leaving the Files / Diff sidebar
          // stale until the user clicks Refresh. ``loadSession`` will
          // overwrite this later with the same value.
          if (options?.workspace) {
            draft._workspace = options.workspace
          }
        })
        get().connectStream()
      } catch (err) {
        set((draft) => {
          draft.error = err instanceof Error ? err.message : 'Failed to send message'
          draft.isTeamWorking = false
        })
      }
    },

    continueTeam: async () => {
      const sessionId = get().sessionId
      if (!sessionId) {
        set((draft) => { draft.error = 'No active session to continue' })
        return
      }

      try {
        set((draft) => {
          draft.isTeamWorking = true
          draft.isContinuing = true
          draft.error = null
        })
        await postTeamCommand('continue', sessionId)
        get().connectStream()
      } catch (err) {
        set((draft) => {
          draft.error = err instanceof Error ? err.message : 'Failed to continue'
          draft.isTeamWorking = false
          draft.isContinuing = false
        })
      }
    },

    compactTeam: async () => {
      const sessionId = get().sessionId
      if (!sessionId) {
        set((draft) => { draft.error = 'No active session to compact' })
        return
      }

      try {
        set((draft) => {
          draft.isTeamWorking = true
          draft.error = null
        })
        await postTeamCommand('compact', sessionId)
        get().connectStream()
      } catch (err) {
        set((draft) => {
          draft.error = err instanceof Error ? err.message : 'Failed to compact'
          draft.isTeamWorking = false
        })
      }
    },

    undoTeam: async () => {
      const sessionId = get().sessionId
      if (!sessionId) {
        set((draft) => { draft.error = 'No active session to undo' })
        return
      }

      try {
        set((draft) => { draft.error = null })
        const response = await postTeamCommand('undo', sessionId)
        // Apply the new boundary *locally* instead of refetching
        // history via ``loadSession``. The response carries the user
        // message the boundary now points at; its ``created_at`` is
        // the new boundary time. ``applyRevertBoundary`` slices the
        // tail off each agent's ``blocks`` into ``_revertedSuffix`` so
        // a subsequent /redo can put them back without a refetch.
        //
        // Saves ~150–500ms per /undo (the history GET + parse +
        // store-overwrite that ``loadSession`` performs) — the cost
        // we used to pay was redundant because /undo is a *boundary
        // move*: no DB rows change, only ``ChatSession.revert``.
        const boundaryIso = response.message?.created_at
        const boundaryTime = boundaryIso ? new Date(boundaryIso).getTime() : null
        set((draft) => {
          draft._leadRevertTime = boundaryTime
          Object.values(draft.agentStreams).forEach((stream) => {
            applyRevertBoundary(stream, boundaryTime)
          })
        })
        // /undo restores the workspace to the target user message's
        // snapshot (see app/services/snapshot_service.py). The server
        // returns the exact A/M/D path partition the restore touched
        // — pass it through so the bridge does a scoped diff splice
        // instead of a whole-repo refetch.
        enqueueWorkspaceInvalidation(
          set,
          get,
          sessionId,
          mergeChangedPaths(response.changed_paths),
        )
        return response
      } catch (err) {
        set((draft) => {
          draft.error = err instanceof Error ? err.message : 'Failed to undo'
        })
        return undefined
      }
    },

    redoTeam: async () => {
      const sessionId = get().sessionId
      if (!sessionId) {
        set((draft) => { draft.error = 'No active session to redo' })
        return
      }

      const MAX_ITER = 200
      const allChangedPaths = new Set<string>()
      let sawChangedPaths = false
      let sawMissingChangedPaths = false
      let sawResponse = false
      try {
        set((draft) => { draft.error = null })
        for (let i = 0; i < MAX_ITER; i++) {
          const response = await postTeamCommand('redo', sessionId)
          sawResponse = true
          // The backend advances one redo boundary per call. The UI
          // action restores all undone turns, so loop until the
          // boundary clears (message: null).
          const boundaryIso = response.message?.created_at
          const boundaryTime = boundaryIso ? new Date(boundaryIso).getTime() : null
          set((draft) => {
            draft._leadRevertTime = boundaryTime
            Object.values(draft.agentStreams).forEach((stream) => {
              applyRevertBoundary(stream, boundaryTime)
            })
          })
          if (response.changed_paths === undefined) {
            sawMissingChangedPaths = true
          } else {
            sawChangedPaths = true
          }
          const merged = mergeChangedPaths(response.changed_paths)
          merged?.forEach((p) => allChangedPaths.add(p))
          if (response.message === null) break

          if (i === MAX_ITER - 1) {
            throw new Error('Redo did not reach the live tip')
          }
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        if (message.includes('No undone message to redo')) {
          set((draft) => {
            draft._leadRevertTime = null
            Object.values(draft.agentStreams).forEach((stream) => {
              applyRevertBoundary(stream, null)
            })
          })
        } else {
          set((draft) => {
            draft.error = `Failed to redo: ${message}`
          })
        }
      } finally {
        if (sawMissingChangedPaths) {
          enqueueWorkspaceInvalidation(set, get, sessionId)
        } else if (allChangedPaths.size > 0) {
          enqueueWorkspaceInvalidation(
            set,
            get,
            sessionId,
            [...allChangedPaths],
          )
        } else if (sawChangedPaths) {
          enqueueWorkspaceInvalidation(set, get, sessionId, [])
        } else if (sawResponse) {
          enqueueWorkspaceInvalidation(set, get, sessionId)
        }
      }
    },

    removePendingMessage: (id: string) => {
      set((draft) => {
        draft._pendingMessages = draft._pendingMessages.filter((m) => m.id !== id)
      })
    },

    stopTeam: async () => {
      const sessionId = get().sessionId
      if (!sessionId || !get().isTeamWorking) return

      // Interrupt all working members (interrupt=true, no message)
      try {
        await postTeamChat(null, sessionId, true)
      } catch (err) {
        console.warn('stopTeam failed', err)
      }
      // The SSE stream will deliver done event once all members go idle
    },

    connectStream: () => {
      const sessionId = get().sessionId
      if (!sessionId) return new AbortController()
      const generation = get()._sessionGeneration

      get()._abortController?.abort()
      const abort = new AbortController()
      set((draft) => { draft.isConnected = true; draft._abortController = abort })

      teamStream(
        sessionId,
        {
          onEvent: (type, data) => {
            const current = get()
            if (current.sessionId !== sessionId || current._sessionGeneration !== generation) return
            current._handleSSEEvent(type, data)
          },
          onParseError: (err) => {
            console.warn(err.message)
          },
          onError: (err) => {
            const current = get()
            if (current.sessionId !== sessionId || current._sessionGeneration !== generation) return
            if (!current.isTeamWorking) {
              set((draft) => { draft.isConnected = false })
              return
            }
            set((draft) => { draft.error = err.message; draft.isConnected = false })
          },
          onDone: () => {
            const current = get()
            if (current.sessionId !== sessionId || current._sessionGeneration !== generation) return
            set((draft) => { draft.isConnected = false })
          },
        },
        abort.signal,
      )
      return abort
    },

    loadTeamStatus: async (workspace?: string | null) => {
      try {
        const status = await teamStatus(workspace)
        if (status) {
          const allAgents = get().sessionId ? [status.lead, ...status.members] : [status.lead]
          const liveNames = allAgents.map((a) => a.name)
          set((draft) => {
            draft.leadName = status.lead.name
            draft.liveAgentNames = liveNames
            const historicalNames = draft.agentNames.filter((name) => !liveNames.includes(name))
            draft.agentNames = [...liveNames, ...historicalNames]
            allAgents.forEach((agent) => {
              if (!draft.agentStreams[agent.name]) {
                draft.agentStreams[agent.name] = createDefaultAgentStream()
              }
              draft.agentStreams[agent.name].model = agent.model
            })
            historicalNames.forEach((name) => {
              const stream = draft.agentStreams[name]
              if (stream && name !== status.lead.name && stream.status !== 'error') {
                stream.status = 'offline'
              }
            })
            if (!draft.activeAgent && draft.agentNames.length > 0) {
              draft.activeAgent = draft.agentNames[0]
            }
          })
        }
      } catch (err) {
        set((draft) => {
          draft.error = err instanceof Error ? err.message : 'Failed to load team status'
        })
      }
    },

    loadSession: async (sessionId: string, workspace?: string | null) => {
      const gen = get()._sessionGeneration
      set((draft) => {
        draft.isTeamWorking = false
        draft.isContinuing = false
      })
      try {
        const existingLiveNames = get().liveAgentNames
        const liveNamesPromise = existingLiveNames === null
          ? teamStatus(workspace).then((status) =>
              status ? [status.lead, ...status.members].map((agent) => agent.name) : null,
            )
          : Promise.resolve(existingLiveNames)
        const historyPromise = teamHistory(sessionId)
        const [liveNames, history] = await Promise.all([liveNamesPromise, historyPromise])

        if (get()._sessionGeneration !== gen) return

        set((draft) => {
          draft.sessionId = sessionId
          // Reset working state — the session being loaded is a completed
          // (or idle) history snapshot. If session A was streaming when the
          // user switched to session B, isTeamWorking would remain true and
          // the "..." indicator would persist indefinitely.
          draft.isTeamWorking = false
          draft.isContinuing = false
          draft.error = null

          // Clear reverted-message state on every stream. These fields are
          // keyed by agent name, so without this reset session A's "N
          // messages reverted" banner leaks into session B when both share
          // a lead. The lead's value is repopulated below from history.
          Object.values(draft.agentStreams).forEach((stream) => {
            stream.revertedCount = 0
            stream.revertedMessages = []
          })

          const leadName = history.lead.agent_name
          draft.leadName = leadName
          if (liveNames !== null) draft.liveAgentNames = liveNames

          const memberNames = history.members.map((m) => m.name)
          const allNames = leadName ? [leadName, ...memberNames] : memberNames
          draft.agentNames = allNames
          const leadRevertTime = revertBoundaryTime(history.lead)

          // Load lead blocks (includes user blocks from parseTeamBlocks).
          // Parse ALL messages — visible + post-boundary — then apply
          // the revert boundary via ``applyRevertBoundary``. That
          // populates ``_revertedSuffix`` on initial load so /redo can
          // restore the tail locally instead of refetching history.
          // ``usage`` and ``_completionBase`` still come from the
          // visible slice — reverted turns must not count toward
          // committed tokens.
          if (leadName) {
            if (!draft.agentStreams[leadName]) {
              draft.agentStreams[leadName] = createDefaultAgentStream()
            }
            // Revoke blob URLs from old blocks before replacing them
            revokeBlobUrlsFromBlocks(draft.agentStreams[leadName].currentBlocks)
            const leadStream = draft.agentStreams[leadName]
            leadStream.blocks = parseTeamBlocks(history.lead.messages)
            leadStream._revertedSuffix = []
            applyRevertBoundary(leadStream, leadRevertTime)
            leadStream.currentBlocks = []
            leadStream.currentText = ''
            leadStream.currentThinking = ''
            leadStream.status = 'idle'
            const leadVisibleMsgs = messagesBeforeRevert(history.lead)
            const leadUsage = sumUsageFromMessages(leadVisibleMsgs)
            leadStream.usage = leadUsage
            // Seed _completionBase so next live turn accumulates correctly
            leadStream._completionBase = leadUsage.completionTokens
          }

          // Load member blocks — members are sliced by the lead's
          // boundary (members don't have their own revert pointer).
          // Same all-then-split pattern so /redo works locally.
          history.members.forEach((member) => {
            const existingStatus = draft.agentStreams[member.name]?.status
            const isLiveMember = liveNames === null || liveNames.includes(member.name)
            if (!draft.agentStreams[member.name]) {
              draft.agentStreams[member.name] = createDefaultAgentStream()
            }
            // Revoke blob URLs from old blocks before replacing them
            revokeBlobUrlsFromBlocks(draft.agentStreams[member.name].currentBlocks)
            const memberStream = draft.agentStreams[member.name]
            memberStream.blocks = parseTeamBlocks(member.messages)
            memberStream._revertedSuffix = []
            applyRevertBoundary(memberStream, leadRevertTime)
            memberStream.currentBlocks = []
            memberStream.currentText = ''
            memberStream.currentThinking = ''
            memberStream.status =
              !isLiveMember
                ? 'offline'
                : existingStatus === 'offline' || existingStatus === 'error' ? existingStatus : 'idle'
            const memberVisibleMsgs = messagesBeforeTime(member.messages, leadRevertTime)
            const memberUsage = sumUsageFromMessages(memberVisibleMsgs)
            memberStream.usage = memberUsage
            // Seed _completionBase so next live turn accumulates correctly
            memberStream._completionBase = memberUsage.completionTokens
          })

          if (!draft.activeAgent || !allNames.includes(draft.activeAgent)) {
            draft.activeAgent = leadName ?? allNames[0] ?? null
          }

          draft.hasMore = history.has_more
          draft.nextCursor = history.next_cursor
          draft._leadRevertTime = revertBoundaryTime(history.lead)
          draft._workspace = workspace ?? null
          draft._loadingOlder = false
        })
      } catch (err) {
        if (get()._sessionGeneration !== gen) return
        set((draft) => {
          draft.error = err instanceof Error ? err.message : 'Failed to load session'
          draft.isContinuing = false
        })
      }
    },

    loadOlderMessages: async () => {
      const { sessionId, nextCursor, hasMore, leadName, _leadRevertTime, _loadingOlder } = get()
      if (!sessionId || !hasMore || !nextCursor || _loadingOlder) return
      set((draft) => { draft._loadingOlder = true })
      try {
        const history = await teamHistory(sessionId, nextCursor)
        set((draft) => {
          draft._loadingOlder = false
          draft.hasMore = history.has_more
          draft.nextCursor = history.next_cursor
          if (leadName && draft.agentStreams[leadName]) {
            const filtered = messagesBeforeTime(history.lead.messages, _leadRevertTime)
            const older = parseTeamBlocks(filtered)
            draft.agentStreams[leadName].blocks = [...older, ...draft.agentStreams[leadName].blocks]
          }
          history.members.forEach((member) => {
            if (draft.agentStreams[member.name]) {
              const filtered = messagesBeforeTime(member.messages, _leadRevertTime)
              const older = parseTeamBlocks(filtered)
              draft.agentStreams[member.name].blocks = [...older, ...draft.agentStreams[member.name].blocks]
            }
          })
        })
      } catch (err) {
        set((draft) => { draft._loadingOlder = false })
        throw err
      }
    },

    setActiveAgent: (name: string) => {
      set((draft) => { draft.activeAgent = name })
    },

    cycleActiveAgent: (dir: 'next' | 'prev') => {
      set((draft) => {
        const names = draft.agentNames
        if (names.length === 0) return
        const idx = names.indexOf(draft.activeAgent || '')
        draft.activeAgent = dir === 'next'
          ? names[(idx + 1) % names.length]
          : names[(idx - 1 + names.length) % names.length]
      })
    },

    toggleSidebar: () => {
      set((draft) => { draft.sidebarOpen = !draft.sidebarOpen })
    },

    dismissSetupRequired: () => {
      set((draft) => { draft.setupRequired = null })
    },

    _drainCacheInvalidations: () => {
      // Snapshot then atomically clear, so an SSE event that pushes
      // between the read and the clear isn't lost.
      const events = get().cacheInvalidations
      if (events.length === 0) return []
      set((draft) => { draft.cacheInvalidations = [] })
      return events
    },

    _handleSSEEvent: createSSEHandler({ set, get }),
  }))
)

// Push a toast whenever the team-level error is set.
// Covers all three write paths: SSE error event, sendMessage catch,
// and connectStream onError.
useTeamStore.subscribe((state, prev) => {
  if (state.error && state.error !== prev.error) {
    useToastStore.getState().push({ tone: 'error', title: 'Agent error', description: state.error })
  }
})
