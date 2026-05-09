/**
 * ToolCall — paper-card record of a tool invocation.
 *
 * Visual language follows the pencil source (nodes ``dqwZw`` / ``LJOUY``)
 * and the canonical spec at ``applications.md#tool-call-row``:
 *
 *   - Outer card: 1px ``--color-border`` outline, ``rounded-md``, on the
 *     ambient surface (no fill of its own — sits on the chat surface).
 *   - Header row: status dot + mono tool-name (or one-line summary) +
 *     chevron, padded ``px-3 py-2``.
 *   - Expanded body: divider, then the args/result panels on the warm
 *     ``--bg-key`` surface so the actual content gets a calm reading wash.
 *
 * Identity is carried by a colored status dot (pending / running /
 * done) matching the capability colour vocabulary.
 *
 * The per-tool header/args customisation lives in ``./display.tsx``;
 * this module owns only the chrome (collapse, copy, status dot, motion).
 */

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronRight, Copy, Check } from 'lucide-react'
import { ToolResult } from '../ToolResult'
import { DURATIONS_S, EASINGS } from '@/lib/motion'
import { StatusDot } from './StatusDot'
import { getToolDisplay } from './display'
import type { ToolCallState } from './types'

interface ToolCallProps {
  name: string
  args?: string
  done?: boolean
  result?: string // tool response content
}

export function ToolCall({ name, args, done, result }: ToolCallProps) {
  // Hooks must be called unconditionally — before any early returns
  const [expanded, setExpanded] = useState(false)
  const [copiedArgs, setCopiedArgs] = useState(false)
  const [copiedResult, setCopiedResult] = useState(false)

  // Determine status: pending (no args yet) → running (args, not done) → done
  const isPending = args === undefined || args === null
  const isRunning = !isPending && !done
  const state: ToolCallState = done ? 'done' : isRunning ? 'running' : 'pending'

  const { header, headerTitle, formattedArgs, language, suppressResult } =
    getToolDisplay(name, args)
  const shownResult = suppressResult ? undefined : result

  const handleCopyArgs = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const text = formattedArgs || args || ''
    try {
      await navigator.clipboard.writeText(text)
      setCopiedArgs(true)
      setTimeout(() => setCopiedArgs(false), 1500)
    } catch {
      // ignore
    }
  }

  const handleCopyResult = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const text = result || ''
    try {
      await navigator.clipboard.writeText(text)
      setCopiedResult(true)
      setTimeout(() => setCopiedResult(false), 1500)
    } catch {
      // ignore
    }
  }

  const hasDetails = Boolean(formattedArgs || shownResult)
  const displayName = name || 'tool'

  return (
    <div className="tool-row-enter my-2 overflow-hidden rounded-md border border-(--color-border)">
      {/* Header row — card-padded, mono name, chevron at end */}
      <button
        type="button"
        onClick={() => hasDetails && setExpanded((v) => !v)}
        className={`group flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs transition-colors duration-(--motion-fast) ease-(--ease-out) focus-visible:outline-2 focus-visible:outline-(--focus-ring) ${
          hasDetails
            ? 'cursor-pointer hover:bg-(--bg-key)'
            : 'cursor-default'
        }`}
        aria-expanded={expanded}
        aria-label={
          hasDetails
            ? expanded
              ? `Collapse ${displayName} details`
              : `Expand ${displayName} details`
            : `${displayName} (no details)`
        }
      >
        <StatusDot state={state} />

        {/* Header content: tool-specific summary or fallback to tool name.
            Only argument values inside the header are italicised (via <Arg>);
            the verb/framing text stays upright. Mono+600 per pencil dqwZw. */}
        {header ? (
          <span
            className="flex-1 truncate font-mono font-semibold text-(--color-text)"
            title={headerTitle ?? undefined}
          >
            {header}
          </span>
        ) : (
          <code className="flex-1 truncate font-mono font-semibold text-(--color-text)">
            {displayName}
          </code>
        )}

        {isPending && (
          <span className="shrink-0 font-mono text-(--color-text-muted)">pending</span>
        )}

        {hasDetails && (
          <ChevronRight
            size={14}
            className={`shrink-0 text-(--color-text-muted) transition-transform duration-(--motion-fast) ease-(--ease-out) ${expanded ? 'rotate-90' : ''}`}
            aria-hidden
          />
        )}
      </button>

      {/* Expandable details — divider then warm paper body per pencil LJOUY */}
      <AnimatePresence initial={false}>
        {expanded && hasDetails && (
          <motion.div
            key="tool-details"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: DURATIONS_S.base, ease: EASINGS.out }}
            className="overflow-hidden"
          >
            <div className="border-t border-(--color-border) bg-(--bg-key)">
              <div className="space-y-3 px-3 py-2.5">
                {/* Args section — caption + copy sit above the content. */}
                {formattedArgs && (
                  <section className="relative">
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <span className="text-[10px] uppercase tracking-wider text-(--color-text-subtle)">
                        {language === 'bash' ? 'bash' : 'arguments'}
                      </span>
                      <button
                        onClick={handleCopyArgs}
                        className="rounded p-0.5 text-(--color-text-muted) transition-colors hover:text-(--color-text) focus-visible:outline-2 focus-visible:outline-(--focus-ring)"
                        aria-label="Copy arguments"
                        title="Copy"
                      >
                        {copiedArgs ? (
                          <Check size={12} className="text-(--color-success)" />
                        ) : (
                          <Copy size={12} />
                        )}
                      </button>
                    </div>
                    {language === 'bash' ? (
                      <pre className="overflow-auto whitespace-pre-wrap break-all font-mono text-xs leading-relaxed text-(--color-accent)">
                        <span className="select-none text-(--color-text-muted)">$ </span>
                        {formattedArgs}
                      </pre>
                    ) : (
                      <pre className="overflow-auto whitespace-pre-wrap break-all font-mono text-xs leading-relaxed text-(--color-text-2)">
                        {formattedArgs}
                      </pre>
                    )}
                  </section>
                )}

                {/* Result section — same caption treatment as args. */}
                {shownResult && (
                  <section className="relative">
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <span className="text-[10px] uppercase tracking-wider text-(--color-text-subtle)">
                        result
                      </span>
                      <button
                        onClick={handleCopyResult}
                        className="rounded p-0.5 text-(--color-text-muted) transition-colors hover:text-(--color-text) focus-visible:outline-2 focus-visible:outline-(--focus-ring)"
                        aria-label="Copy result"
                        title="Copy result"
                      >
                        {copiedResult ? (
                          <Check size={12} className="text-(--color-success)" />
                        ) : (
                          <Copy size={12} />
                        )}
                      </button>
                    </div>
                    <div className="text-xs leading-relaxed text-(--color-text-2)">
                      <ToolResult toolName={name} result={shownResult} />
                    </div>
                  </section>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
