import {
  appendThinking,
  appendText,
  initTool,
  addTool,
  appendToolOutput,
  completeTool,
  generateBlockId,
  startCompaction,
  appendCompactionContent,
  endCompaction,
} from '@/utils/blocks'
import { createDefaultAgentStream } from './defaults'
import {
  WIKI_MUTATING_TOOLS,
  FS_MUTATING_TOOLS,
  NOTE_TOOLS,
  SCHEDULER_MUTATING_TOOLS,
  TODO_MUTATING_TOOLS,
  extractToolPaths,
  touchesWiki,
} from './helpers'
import type { CacheInvalidation, TeamStore } from './types'

type Setter = (fn: (draft: TeamStore) => void) => void
type Getter = () => TeamStore

function ensureAgent(draft: TeamStore, agent: string) {
  if (!draft.agentStreams[agent]) draft.agentStreams[agent] = createDefaultAgentStream()
  if (!draft.agentNames.includes(agent)) draft.agentNames.push(agent)
}

interface CreateSSEHandlerArgs {
  set: Setter
  get: Getter
}

export function createSSEHandler({ set, get }: CreateSSEHandlerArgs) {
  return (type: string, data: unknown) => {
    const d = data as Record<string, unknown>

    switch (type) {
      case 'session': {
        set((draft) => { draft.sessionId = d.session_id as string })
        break
      }

      case 'title_update': {
        set((draft) => { draft.sessionTitle = d.title as string })
        break
      }

      case 'thinking': {
        const agent = d.agent as string
        const text = d.text as string
        set((draft) => {
          ensureAgent(draft, agent)
          const stream = draft.agentStreams[agent]
          stream.currentBlocks = appendThinking(
            stream.currentBlocks, text
          )
          if (text) {
            stream._completionEstimated = (stream._completionEstimated ?? 0) + (text.length / 4)
            const newEstimatedVal = Math.round(stream._completionEstimated)
            const currentTurnTokens = Math.max(stream.usage.completionTokens - stream._completionBase, newEstimatedVal)
            stream.usage.completionTokens = stream._completionBase + currentTurnTokens
            stream.usage.totalTokens = stream.usage.promptTokens + stream.usage.completionTokens
          }
        })
        break
      }

      case 'message': {
        const agent = d.agent as string
        const text = d.text as string
        set((draft) => {
          ensureAgent(draft, agent)
          const stream = draft.agentStreams[agent]
          stream.currentBlocks = appendText(
            stream.currentBlocks, text
          )
          if (text) {
            stream._completionEstimated = (stream._completionEstimated ?? 0) + (text.length / 4)
            const newEstimatedVal = Math.round(stream._completionEstimated)
            const currentTurnTokens = Math.max(stream.usage.completionTokens - stream._completionBase, newEstimatedVal)
            stream.usage.completionTokens = stream._completionBase + currentTurnTokens
            stream.usage.totalTokens = stream.usage.promptTokens + stream.usage.completionTokens
          }
        })
        break
      }

      case 'tool_call': {
        if (TODO_MUTATING_TOOLS.has(d.name as string)) break
        const agent = d.agent as string
        set((draft) => {
          ensureAgent(draft, agent)
          draft.agentStreams[agent].currentBlocks = initTool(
            draft.agentStreams[agent].currentBlocks,
            d.name as string,
            d.tool_call_id as string | undefined,
          )
        })
        break
      }

      case 'tool_start': {
        if (TODO_MUTATING_TOOLS.has(d.name as string)) break
        const agent = d.agent as string
        set((draft) => {
          ensureAgent(draft, agent)
          draft.agentStreams[agent].currentBlocks = addTool(
            draft.agentStreams[agent].currentBlocks,
            d.name as string,
            d.arguments as string | undefined,
            d.tool_call_id as string | undefined,
          )
        })
        break
      }

      case 'tool_output_delta': {
        if (TODO_MUTATING_TOOLS.has(d.name as string)) break
        const agent = d.agent as string
        set((draft) => {
          ensureAgent(draft, agent)
          draft.agentStreams[agent].currentBlocks = appendToolOutput(
            draft.agentStreams[agent].currentBlocks,
            d.name as string,
            d.tool_call_id as string | undefined,
            d.text as string,
          )
        })
        break
      }

      case 'tool_end': {
        const agent = d.agent as string
        const toolName = d.name as string
        const toolCallId = d.tool_call_id as string | undefined
        if (!TODO_MUTATING_TOOLS.has(toolName)) {
          set((draft) => {
            ensureAgent(draft, agent)
            draft.agentStreams[agent].currentBlocks = completeTool(
              draft.agentStreams[agent].currentBlocks,
              toolName,
              toolCallId,
              d.result as string | undefined,
            )
          })
        }
        const events: CacheInvalidation[] = []
        if (NOTE_TOOLS.has(toolName)) {
          events.push({ kind: 'wiki' })
        }
        let touchedWiki = false
        if (WIKI_MUTATING_TOOLS.has(toolName)) {
          const stream = get().agentStreams[agent]
          const block = stream?.currentBlocks.find(
            (b) => b.type === 'tool' && (toolCallId ? b.toolCallId === toolCallId : b.toolName === toolName),
          )
          if (touchesWiki(toolName, block?.toolArgs)) {
            events.push({ kind: 'wiki' })
            touchedWiki = true
          }
        }
        if (FS_MUTATING_TOOLS.has(toolName) && !touchedWiki) {
          const workspace = get()._workspace
          if (workspace) {
            const stream = get().agentStreams[agent]
            const block = stream?.currentBlocks.find(
              (b) =>
                b.type === 'tool' &&
                (toolCallId ? b.toolCallId === toolCallId : b.toolName === toolName),
            )
            const paths = extractToolPaths(toolName, block?.toolArgs)
            const workspacePaths = paths?.filter(
              (p) => !p.startsWith('wiki/') && p !== 'wiki',
            )
            if (workspacePaths && workspacePaths.length > 0) {
              events.push({
                kind: 'coding_workspace_paths',
                workspace,
                paths: workspacePaths,
              })
            } else {
              events.push({ kind: 'coding_workspace', workspace })
            }
          } else {
            const sid = get().sessionId
            if (sid) events.push({ kind: 'workspace_files', sessionId: sid })
          }
        }
        if (SCHEDULER_MUTATING_TOOLS.has(toolName)) {
          events.push({ kind: 'scheduler' })
        }
        if (TODO_MUTATING_TOOLS.has(toolName)) {
          const sid = get().sessionId
          if (sid) events.push({ kind: 'todos', sessionId: sid })
        }
        if (toolName === 'team_manage') {
          events.push({ kind: 'team_agents' })
        }
        if (events.length > 0) {
          set((draft) => { draft.cacheInvalidations.push(...events) })
        }
        break
      }

      case 'usage': {
        const meta = d.metadata as Record<string, unknown> | undefined
        if (meta?.turn_total) break
        const agent = (meta?.agent as string) ?? (d.agent as string)
        if (!agent) break
        set((draft) => {
          ensureAgent(draft, agent)
          const stream = draft.agentStreams[agent]
          const u = stream.usage
          u.promptTokens     = (d.prompt_tokens as number) || 0
          u.completionTokens = stream._completionBase + ((d.completion_tokens as number) || 0)
          u.cachedTokens     = (d.cached_tokens as number) ?? u.cachedTokens
          u.totalTokens      = u.promptTokens + u.completionTokens
        })
        break
      }

      case 'inbox': {
        const agent = d.agent as string
        set((draft) => {
          ensureAgent(draft, agent)
          draft.agentStreams[agent].currentBlocks.push({
            id: generateBlockId(),
            type: 'user',
            content: d.content as string,
            extra: { from_agent: d.from_agent as string },
            timestamp: new Date(),
          })
        })
        break
      }

      case 'queued_turn_start': {
        const agent = d.agent as string
        const messageIds = Array.isArray(d.message_ids) ? new Set(d.message_ids as string[]) : null
        set((draft) => {
          ensureAgent(draft, agent)
          if (agent !== draft.leadName || !draft.sessionId) return
          draft.isTeamWorking = true
          draft.isContinuing = false
          draft.error = null
          draft.agentStreams[agent].status = 'working'
          const queued = draft._pendingMessages.filter((msg) => {
            if (msg.sessionId !== draft.sessionId) return false
            return messageIds === null || messageIds.has(msg.id)
          })
          if (queued.length === 0) return
          draft.agentStreams[agent].currentBlocks.push(
            ...queued.map((msg) => ({
              id: msg.id,
              type: 'user' as const,
              content: msg.content,
              timestamp: new Date(),
            })),
          )
          const queuedIds = new Set(queued.map((msg) => msg.id))
          draft._pendingMessages = draft._pendingMessages.filter((msg) => !queuedIds.has(msg.id))
        })
        break
      }

      case 'agent_status': {
        const agent = d.agent as string
        const status = d.status as string
        set((draft) => {
          ensureAgent(draft, agent)
          if (status === 'working') {
            draft.agentStreams[agent].status = 'working'
            draft.agentStreams[agent]._completionEstimated = 0
            draft.isTeamWorking = true
            if (draft.liveAgentNames && !draft.liveAgentNames.includes(agent)) draft.liveAgentNames.push(agent)
          } else if (status === 'idle') {
            draft.agentStreams[agent].status = 'idle'
            if (draft.liveAgentNames && !draft.liveAgentNames.includes(agent)) draft.liveAgentNames.push(agent)
          } else if (status === 'offline') {
            draft.agentStreams[agent].status = 'offline'
            if (draft.liveAgentNames) draft.liveAgentNames = draft.liveAgentNames.filter((name) => name !== agent)
          } else if (status === 'error') {
            draft.agentStreams[agent].status = 'error'
            draft.agentStreams[agent].lastError =
              (d.metadata as Record<string, unknown>)?.message as string ?? null
            if (draft.liveAgentNames && !draft.liveAgentNames.includes(agent)) draft.liveAgentNames.push(agent)
          }
          if (status !== 'working') {
            draft.isTeamWorking = Object.values(draft.agentStreams).some(
              (s) => s.status === 'working',
            )
          }
        })
        break
      }

      case 'done': {
        set((draft) => {
          draft.isTeamWorking = false
          draft.isContinuing = false
          const completedAt = new Date()
          Object.keys(draft.agentStreams).forEach((name) => {
            const stream = draft.agentStreams[name]
            if (stream.currentBlocks.length > 0) {
              const stamped = stream.currentBlocks.map((b) =>
                b.timestamp ? b : { ...b, timestamp: completedAt },
              )
              stream.blocks = [...stream.blocks, ...stamped]
              stream.currentBlocks = []
            }
            stream._completionBase = stream.usage.completionTokens
            stream._completionEstimated = 0
            if (stream.status !== 'error' && stream.status !== 'offline') {
              stream.status = 'idle'
            }
          })
        })
        break
      }

      case 'error': {
        set((draft) => {
          draft.error = d.message as string
          draft.isTeamWorking = false
          draft.isContinuing = false
        })
        break
      }

      case 'summarization_start': {
        const agent = d.agent as string
        if (!agent) break
        set((draft) => {
          ensureAgent(draft, agent)
          draft.agentStreams[agent].currentBlocks = startCompaction(
            draft.agentStreams[agent].currentBlocks,
          )
        })
        break
      }

      case 'summarization_content': {
        const agent = d.agent as string
        const text = d.text as string
        if (!agent || !text) break
        set((draft) => {
          ensureAgent(draft, agent)
          draft.agentStreams[agent].currentBlocks = appendCompactionContent(
            draft.agentStreams[agent].currentBlocks,
            text,
          )
        })
        break
      }

      case 'summarization_end': {
        const agent = d.agent as string
        if (!agent) break
        const summary = (d.summary as string | undefined) ?? ''
        const meta = d.metadata as Record<string, unknown> | undefined
        const error = Boolean(meta?.error)
        set((draft) => {
          ensureAgent(draft, agent)
          draft.agentStreams[agent].currentBlocks = endCompaction(
            draft.agentStreams[agent].currentBlocks,
            summary,
            error,
          )
        })
        break
      }

      case 'agent_not_configured': {
        const agent = d.agent as string
        set((draft) => {
          ensureAgent(draft, agent)
          draft.agentStreams[agent].status = 'error'
          draft.agentStreams[agent].lastError = d.message as string
          draft.setupRequired = {
            agent,
            message: d.message as string,
            action: (d.action as { type?: string; tab?: string } | undefined) ?? {},
          }
          draft.isTeamWorking = false
        })
        break
      }
    }
  }
}
