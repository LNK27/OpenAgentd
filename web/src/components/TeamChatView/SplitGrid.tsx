/**
 * SplitGrid — automatic n-pane grid layout for the `split` view mode.
 *
 * All panes (lead included) are treated equally and follow `agentNames` order.
 * New spawned agents are appended by the store, so they automatically claim the
 * next available split-view slot. Columns grow by square capacity:
 *
 *   1 → fullscreen
 *   2 → side-by-side columns
 *   3 → big left, two stacked right
 *   4 → 2×2
 *   5..9 → three columns, stacked as needed
 */
import { AgentPane } from '../AgentPane'
import type { AgentStream } from '@/stores/useTeamStore'

interface SplitGridProps {
  agentNames: string[]
  leadName: string | null
  agentStreams: Record<string, AgentStream>
}

export function SplitGrid({
  agentNames, leadName, agentStreams,
}: SplitGridProps) {
  if (agentNames.length === 0) return null

  const renderPanel = (name: string) => {
    const stream = agentStreams[name]
    if (!stream) return null
    return (
      <div key={name} className="min-h-0 flex-1">
        <AgentPane
          name={name}
          stream={stream}
          isLead={name === leadName}
        />
      </div>
    )
  }

  const columnCount = Math.ceil(Math.sqrt(agentNames.length))
  const baseColumnSize = Math.floor(agentNames.length / columnCount)
  const extraColumns = agentNames.length % columnCount
  const columns: string[][] = []
  let offset = 0

  for (let col = 0; col < columnCount; col += 1) {
    const size = baseColumnSize + (col >= columnCount - extraColumns ? 1 : 0)
    columns.push(agentNames.slice(offset, offset + size))
    offset += size
  }

  return (
    <div className="flex h-full gap-3">
      {columns.map((column, idx) => (
        <div key={idx} className="flex min-w-0 flex-1 flex-col gap-3">
          {column.map(renderPanel)}
        </div>
      ))}
    </div>
  )
}
