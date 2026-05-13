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
import { useEffect, useMemo, useState } from 'react'
import { AgentPane } from '../AgentPane'
import type { AgentStream } from '@/stores/useTeamStore'

const EXIT_ANIMATION_MS = 180

interface SplitGridProps {
  agentNames: string[]
  leadName: string | null
  agentStreams: Record<string, AgentStream>
}

export function SplitGrid({
  agentNames, leadName, agentStreams,
}: SplitGridProps) {
  const visibleAgentNames = useMemo(() => agentNames.filter((name) => {
    const stream = agentStreams[name]
    return stream && stream.status !== 'offline'
  }), [agentNames, agentStreams])
  const visibleKey = visibleAgentNames.join('\u0000')
  const [renderedAgentNames, setRenderedAgentNames] = useState(visibleAgentNames)
  const [exitingAgentNames, setExitingAgentNames] = useState<string[]>([])

  useEffect(() => {
    const syncTimer = window.setTimeout(() => {
      setRenderedAgentNames((prev) => {
        const visibleSet = new Set(visibleAgentNames)
        const leaving = prev.filter((name) => !visibleSet.has(name) && agentStreams[name])
        const next = [...visibleAgentNames, ...leaving]

        if (leaving.length > 0) {
          setExitingAgentNames((current) => Array.from(new Set([...current, ...leaving])))
          window.setTimeout(() => {
            setRenderedAgentNames((current) => current.filter((name) => !leaving.includes(name)))
            setExitingAgentNames((current) => current.filter((name) => !leaving.includes(name)))
          }, EXIT_ANIMATION_MS)
        }

        return next.length === prev.length && next.every((name, idx) => name === prev[idx]) ? prev : next
      })
    }, 0)
    return () => window.clearTimeout(syncTimer)
  }, [visibleKey, visibleAgentNames, agentStreams])

  if (renderedAgentNames.length === 0) return null

  const renderPanel = (name: string) => {
    const stream = agentStreams[name]
    if (!stream) return null
    const isExiting = exitingAgentNames.includes(name)
    return (
      <div
        key={name}
        className={`split-pane-enter min-h-0 flex-1 transition-all duration-200 ease-out ${isExiting ? 'scale-95 opacity-0' : 'scale-100 opacity-100'}`}
      >
        <AgentPane
          name={name}
          stream={stream}
          isLead={name === leadName}
        />
      </div>
    )
  }

  const columnCount = Math.ceil(Math.sqrt(renderedAgentNames.length))
  const baseColumnSize = Math.floor(renderedAgentNames.length / columnCount)
  const extraColumns = renderedAgentNames.length % columnCount
  const columns: string[][] = []
  let offset = 0

  for (let col = 0; col < columnCount; col += 1) {
    const size = baseColumnSize + (col >= columnCount - extraColumns ? 1 : 0)
    columns.push(renderedAgentNames.slice(offset, offset + size))
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
