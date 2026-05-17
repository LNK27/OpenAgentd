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
 * Identity is carried by a colored status dot for the lifecycle:
 * start / running / success / failed.
 *
 * The per-tool header/args customisation lives in ``./display.tsx``;
 * this module owns only the chrome (collapse, copy, status dot, motion).
 */

import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronRight, Copy, Check } from 'lucide-react'
import { ToolResult } from '../ToolResult'
import { DURATIONS_S, EASINGS } from '@/lib/motion'
import { getToolDisplay } from './display'
import type { ToolCallState } from './types'

interface ToolCallProps {
  name: string
  args?: string
  done?: boolean
  liveOutput?: string
  result?: string // tool response content
}

function isFailedResult(result: string | undefined): boolean {
  if (!result) return false
  const firstLine = result.trimStart().split('\n', 1)[0]?.toLowerCase() ?? ''
  return (
    firstLine.startsWith('[failed') ||
    firstLine.startsWith('[error') ||
    firstLine.includes('exit code 1') ||
    firstLine.includes('exit 1')
  )
}

function formatShellResult(result: string | undefined): { statusLine: string | null; body: string | null } {
  if (!result) return { statusLine: null, body: null }

  const firstNewline = result.indexOf('\n')
  const firstLine = firstNewline >= 0 ? result.slice(0, firstNewline).trim() : result.trim()
  const hasStatusLine = /^\[(Succeeded|Failed|Error)/i.test(firstLine)

  if (!hasStatusLine) {
    return { statusLine: null, body: result }
  }

  const body = firstNewline >= 0 ? result.slice(firstNewline + 1).trimStart() : ''
  return { statusLine: firstLine, body: body || null }
}

export function ToolCall({ name, args, done, liveOutput, result }: ToolCallProps) {
  // Hooks must be called unconditionally — before any early returns
  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null)
  const [copiedArgs, setCopiedArgs] = useState(false)
  const [copiedResult, setCopiedResult] = useState(false)
  const liveOutputRef = useRef<HTMLPreElement>(null)

  // Determine status: start (name only) → running (args) → success/failed (result)
  const isPending = args === undefined || args === null
  const isRunning = !isPending && !done
  const state: ToolCallState = isPending
    ? 'start'
    : isRunning
      ? 'running'
      : isFailedResult(result)
        ? 'failed'
        : 'success'

  const { header, headerTitle, formattedArgs, language, suppressResult } =
    getToolDisplay(name, args)
  // Pending-state header comes from getToolDisplay's no-args branch
  // (e.g. ``recall`` → "Checking memory…", ``team_message`` →
  // "Preparing message…"). Tools without a custom pending header return
  // ``header: null`` from that branch and fall back to the raw tool name
  // below, preserving the previous behaviour for every other tool.
  const visibleHeader = header
  const shownResult = suppressResult ? undefined : result
  const shownLiveOutput = shownResult ? undefined : liveOutput
  const isShell = language === 'bash'
  const isShellTerminal = isShell && Boolean(formattedArgs)
  const shellResult = isShell ? formatShellResult(shownResult) : null
  const shellOutput = shellResult?.body ?? shownLiveOutput

  useEffect(() => {
    const el = liveOutputRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [shownLiveOutput])

  const handleCopyArgs = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const text = isShellTerminal
      ? `${formattedArgs}${shellOutput ? `\n${shellOutput}` : ''}`
      : formattedArgs || args || ''
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

  const hasDetails = Boolean(formattedArgs || shownLiveOutput || shownResult)
  const expanded = manualExpanded ?? Boolean(shownLiveOutput)
  const displayName = name || 'tool'
  const headerClassName = `flex-1 truncate font-mono font-semibold text-(--color-text) ${state === 'running' ? 'animate-pulse text-(--color-marker-orange)' : ''}`

  return (
    <div className="tool-row-enter my-2 overflow-hidden rounded-md border border-(--color-border)">
      {/* Header row — card-padded, mono name, chevron at end */}
      <button
        type="button"
        onClick={() => hasDetails && setManualExpanded(!expanded)}
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
        {/* Header content: tool-specific summary or fallback to tool name.
            Mono+600 per pencil dqwZw. */}
        {visibleHeader ? (
          <span
            className={headerClassName}
            title={headerTitle ?? undefined}
          >
            {visibleHeader}
          </span>
        ) : (
          <code className={headerClassName}>
            {displayName}
          </code>
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
                        {isShellTerminal ? 'terminal' : 'arguments'}
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
                    {isShellTerminal ? (
                      <div className="flex flex-col gap-1">
                        <pre
                          ref={shownLiveOutput ? liveOutputRef : undefined}
                          className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-(--color-text-2)"
                        >
                          <span className="select-none text-(--color-text-muted)">$ </span>
                          <span className="text-(--color-accent)">{formattedArgs}</span>
                          {shellOutput ? `\n${shellOutput}` : ''}
                        </pre>
                        {shellResult?.statusLine && (
                          <span
                            className={`font-mono text-[11px] font-medium ${
                              shellResult.statusLine.startsWith('[Succeeded')
                                ? 'text-(--color-success)'
                                : 'text-(--color-error)'
                            }`}
                          >
                            {shellResult.statusLine}
                          </span>
                        )}
                      </div>
                    ) : (
                      <pre className="overflow-auto whitespace-pre-wrap break-all font-mono text-xs leading-relaxed text-(--color-text-2)">
                        {formattedArgs}
                      </pre>
                    )}
                  </section>
                )}

                {shownLiveOutput && !isShellTerminal && (
                  <section className="relative">
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <span className="text-[10px] uppercase tracking-wider text-(--color-text-subtle)">
                        output
                      </span>
                    </div>
                    <pre
                      ref={liveOutputRef}
                      className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-(--color-text-2)"
                    >
                      {shownLiveOutput}
                    </pre>
                  </section>
                )}

                {/* Result section — same caption treatment as args. */}
                {shownResult && !isShellTerminal && (
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
