/**
 * TileArea — recursive tile-tree pane host for the `unified` view mode.
 *
 * Wraps ``TileTree`` with the empty state (an idle octobot + hint
 * message) and the outer flex/padding chrome. The actual tile recursion
 * and split logic lives in ``../TileTree``; the per-tile-leaf state
 * (open agents, focused agent, swap, close) is owned by
 * ``useTileLayout`` and threaded through here as ``tileLayout``.
 */
import OctobotMascot from '@/assets/brand/octobot-agentd-source.png'

import { TileTree } from '../TileTree'
import type { useTileLayout } from '@/hooks/useTileLayout'
import type { AgentStream } from '@/stores/useTeamStore'

interface TileAreaProps {
  tileLayout: ReturnType<typeof useTileLayout>
  agentStreams: Record<string, AgentStream>
  leadName: string | null
}

export function TileArea({ tileLayout, agentStreams, leadName }: TileAreaProps) {
  const { root, focusedAgent, focusAgent, closeAgent, swapAgents } = tileLayout

  if (!root) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 py-16">
        <img
          src={OctobotMascot}
          className="opacity-90"
          width={96}
          height={96}
          alt=""
          aria-hidden="true"
        />
        <h2 className="font-hand text-3xl font-bold text-(--color-text)">
          empty room.
        </h2>
        <p className="text-sm text-(--color-text-muted)">
          Click a tab above to open an agent pane
        </p>
      </div>
    )
  }

  return (
    <div className="min-h-0 flex-1 p-3">
      <TileTree
        node={root}
        agentStreams={agentStreams}
        leadName={leadName}
        focusedAgent={focusedAgent}
        onFocus={focusAgent}
        onClose={closeAgent}
        onSwap={swapAgents}
      />
    </div>
  )
}
