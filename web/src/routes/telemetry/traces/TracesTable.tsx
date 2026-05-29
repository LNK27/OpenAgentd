/**
 * Recent traces table — header rendered by ``TracesSection``.  Each row is
 * clickable; the parent owns the selection state.
 */

import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import type { TraceListItem } from '@/api/client'
import {
  formatCompact,
  formatMs,
  formatPercent,
  formatShortId,
  formatUsd,
  timeAgo,
} from '@/utils/telemetryFormat'
import { Td, Th } from '../primitives'

export function TracesTable({
  traces,
  onSelect,
  embedded = false,
}: {
  traces: TraceListItem[]
  onSelect: (traceId: string) => void
  embedded?: boolean
}) {
  // "Now" is captured once per TracesTable mount via a lazy useState initializer
  // — keeps the render pure (no Date.now() call during render) while still
  // giving fresh labels whenever the table unmounts/remounts on refetch.
  const [now] = useState(() => Date.now())
  const table = (
    <table className="min-w-[720px] w-full text-xs">
      <thead className="sticky top-0 z-10">
        <tr className="border-b border-(--color-border) bg-(--bg-key)">
          <Th>When</Th>
          <Th>Session</Th>
          <Th>Agent</Th>
          <Th>Provider:model</Th>
          <Th align="right">Duration</Th>
          <Th align="right">Input / output</Th>
          <Th align="right">Cache hit</Th>
          <Th align="right">Cost</Th>
          <Th align="right">Status</Th>
          <Th />
        </tr>
      </thead>
      <tbody>
        {traces.map((t) => (
          <tr
            key={t.span_id}
            onClick={() => onSelect(t.trace_id)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onSelect(t.trace_id)
              }
            }}
            tabIndex={0}
            role="button"
            aria-label={`Open trace ${formatShortId(t.trace_id)}`}
            className="cursor-pointer border-b border-(--color-border) transition-colors last:border-b-0 hover:bg-(--bg-key)/40 focus:bg-(--bg-key)/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-(--focus-ring)"
          >
            <Td>
              <span title={new Date(t.start_ms).toLocaleString()}>
                {timeAgo(t.start_ms, now)}
              </span>
            </Td>
            <Td muted mono>
              {t.session_id ? formatShortId(t.session_id) : '—'}
            </Td>
            <Td>{t.agent_name ?? '—'}</Td>
            <Td muted>{t.provider_model ?? t.model ?? '—'}</Td>
            <Td align="right">{formatMs(t.duration_ms)}</Td>
            <Td align="right" muted>
              {formatCompact(t.input_tokens)} / {formatCompact(t.output_tokens)}
            </Td>
            <Td align="right" muted>
              {formatPercent(cachePercent(t.cached_tokens, t.input_tokens))}
            </Td>
            <Td align="right" muted>{formatUsd(t.estimated_cost_usd)}</Td>
            <Td align="right">
              {t.error ? (
                <span className="rounded bg-(--color-error-subtle) px-1.5 py-0.5 text-[10px] font-medium text-(--color-error)">
                  error
                </span>
              ) : (
                <span className="text-(--color-text-muted)">ok</span>
              )}
            </Td>
            <Td align="right">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) md:h-6 md:w-6">
                <ChevronRight size={15} className="md:h-3.5 md:w-3.5" aria-hidden="true" />
              </span>
            </Td>
          </tr>
        ))}
      </tbody>
    </table>
  )

  if (embedded) return table

  return (
    <div className="overflow-x-auto rounded-lg border border-(--color-border) bg-(--bg-card)">
      {table}
    </div>
  )
}

function cachePercent(cachedTokens: number, inputTokens: number): number {
  if (inputTokens <= 0) return 0
  return (cachedTokens / inputTokens) * 100
}
