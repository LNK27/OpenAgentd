/**
 * Thinking — paper-card reasoning trace.
 *
 * Visual language follows the pencil source (node ``ptE8V``,
 * ``ThinkingCollapsed``):
 *
 *   - Outer card: 1px ``--color-border`` outline, ``rounded-md``, padded
 *     ``px-3 py-2.5``. Sits on the ambient surface (no fill of its own).
 *   - Header: label in Inter 13/500 ``--color-text-2`` plus a mono 11px
 *     ``--color-text-muted`` sub-hint ("tap to read" / "tap to collapse")
 *     that mirrors the pencil layout.
 *   - Streaming: dots replace the sub-hint while content is still
 *     arriving so the label stays the visual anchor.
 *
 * Label behaviour:
 *   - Default: "Reasoning".
 *   - When the first line of `content` has finalised (a newline arrived, OR
 *     a closing `**` for a leading bold heading), extract that line, strip
 *     common markdown, and use it as the label — provided it's ≤40 chars.
 *   - Lines longer than 40 chars fall back to "Reasoning" rather than
 *     truncating awkwardly mid-thought.
 *   - While streaming a partial first line, we show "Reasoning" + dots so
 *     the label doesn't thrash character-by-character.
 */

import { useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ThinkingDots } from './motion'
import { DURATIONS_S, EASINGS } from '@/lib/motion'

interface ThinkingProps {
  content: string
  isStreaming?: boolean
}

const MAX_LABEL_LEN = 40
const DEFAULT_LABEL = 'Reasoning'

/**
 * Has the first line of reasoning content finalised?
 *
 * Reasoning tokens arrive in multi-word chunks, not single characters, so
 * the concern isn't letter-level jitter. The concern is that a chunk may
 * contain a *partial* first line: the label would flip between successive
 * phrase prefixes ("Determining response" → "Determining response needs
 * for the user" → fallback to "Reasoning" once it exceeds 40 chars) until
 * the newline finally arrives. Gating on a completed first line — newline
 * or a closed leading `**bold**` heading — keeps the label stable until
 * we know what it should actually be.
 *
 * For non-streaming content (DB replay, finished turns) we always treat
 * whatever is there as finalised.
 */
function firstLineFinalised(content: string, isStreaming: boolean): boolean {
  if (!isStreaming) return true
  if (content.includes('\n')) return true
  const trimmed = content.trimStart()
  // Closed bold heading at the very start: `**...**`
  if (trimmed.startsWith('**')) {
    const rest = trimmed.slice(2)
    return rest.includes('**')
  }
  return false
}

/** Strip the most common leading markdown decorations from a single line. */
function stripLeadingMarkdown(line: string): string {
  let s = line.trim()
  // Bold wrapping: **text**
  const boldMatch = s.match(/^\*\*(.+?)\*\*\s*$/)
  if (boldMatch) return boldMatch[1].trim()
  // Italic wrapping: *text* or _text_
  const italicMatch = s.match(/^[*_](.+?)[*_]\s*$/)
  if (italicMatch) return italicMatch[1].trim()
  // ATX heading: leading `#`s
  s = s.replace(/^#{1,6}\s+/, '')
  // Blockquote/list marker: leading `>`, `-`, `*`, `+`, or digits like `1.`
  s = s.replace(/^(?:[>*+-]|\d+\.)\s+/, '')
  return s.trim()
}

interface Extracted {
  label: string
  /** True when the label was pulled from the content's first line — in
   *  that case the expanded body should omit that line to avoid repeating
   *  it underneath. */
  labelFromContent: boolean
}

function extract(content: string, isStreaming: boolean): Extracted {
  if (!content) return { label: DEFAULT_LABEL, labelFromContent: false }
  if (!firstLineFinalised(content, Boolean(isStreaming))) {
    return { label: DEFAULT_LABEL, labelFromContent: false }
  }

  // First non-empty line
  const firstLine = content
    .split('\n')
    .map((l) => l.trim())
    .find((l) => l.length > 0)
  if (!firstLine) return { label: DEFAULT_LABEL, labelFromContent: false }

  const cleaned = stripLeadingMarkdown(firstLine)
  if (!cleaned) return { label: DEFAULT_LABEL, labelFromContent: false }
  if (cleaned.length > MAX_LABEL_LEN) {
    return { label: DEFAULT_LABEL, labelFromContent: false }
  }
  return { label: cleaned, labelFromContent: true }
}

/**
 * Drop the first non-empty line (and any blank lines immediately following
 * it) from content. Used when that first line was promoted to the header
 * label so the expanded body doesn't repeat it.
 */
function stripFirstLine(content: string): string {
  const lines = content.split('\n')
  let i = 0
  // Skip leading blank lines, then the first non-empty line
  while (i < lines.length && lines[i].trim() === '') i++
  if (i < lines.length) i++
  // Skip blank separator lines
  while (i < lines.length && lines[i].trim() === '') i++
  return lines.slice(i).join('\n')
}

export function Thinking({ content, isStreaming }: ThinkingProps) {
  const [expanded, setExpanded] = useState(false)

  const { label, body } = useMemo(() => {
    const { label, labelFromContent } = extract(content, Boolean(isStreaming))
    const body = labelFromContent ? stripFirstLine(content) : content
    // If stripping the first line leaves nothing, fall back to the full
    // content so there's always something to show when expanded.
    return { label, body: body.trim() ? body : content }
  }, [content, isStreaming])

  return (
    <div className="my-2 overflow-hidden rounded-md border border-(--color-border)">
      {/* Trigger — paper card per pencil ptE8V */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="group flex w-full items-center gap-2.5 px-3 py-2.5 text-left transition-colors duration-(--motion-fast) ease-(--ease-out) hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--focus-ring)"
        aria-expanded={expanded}
        aria-label={expanded ? 'Collapse reasoning' : 'Expand reasoning'}
      >
        <span className="flex-1 truncate text-[13px] font-medium text-(--color-text-2)">
          {label}
        </span>
        {isStreaming ? (
          <ThinkingDots
            className="shrink-0 text-(--color-text-muted)"
            aria-label={`${label}…`}
          />
        ) : (
          <span className="shrink-0 font-mono text-[11px] text-(--color-text-muted)">
            {expanded ? 'tap to collapse' : 'tap to read'}
          </span>
        )}
      </button>

      {/* Expanded body — divider then warm paper wash, mono italic prose */}
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            key="thinking-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: DURATIONS_S.base, ease: EASINGS.out }}
            className="overflow-hidden"
          >
            <div className="border-t border-(--color-border) bg-(--bg-key) px-3 py-2.5">
              <p className="whitespace-pre-wrap font-mono text-xs italic leading-relaxed text-(--color-text-muted)">
                {body}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
