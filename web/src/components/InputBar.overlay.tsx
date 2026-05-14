/**
 * Visual chip overlay for the InputBar's textarea.
 *
 * Renders a mirror ``<div>`` directly behind the textarea with the same
 * font and wrapping rules. The mirror's text is transparent, so only the
 * colored chip backgrounds at committed `@mention` positions bleed through;
 * the textarea's caret and selection paint normally on top.
 *
 * Same pattern GitHub / Linear use — strictly cosmetic, leaves the
 * underlying ``<textarea>`` plain-text so paste / select-all / IME work
 * without surprises.
 */
import { useEffect, useRef } from 'react'

import { findCommittedMentions } from './InputBar.mentions'

interface MentionOverlayProps {
  /** Current textarea value. */
  value: string
  /**
   * Range of the mention currently being typed (from ``findActiveMention``).
   * Excluded from highlighting so users don't see a chip materialise on
   * every keystroke before they've committed the selection.
   */
  activeRange: { start: number; end: number } | null
  /** Ref to the textarea so we can mirror its scroll position. */
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
}

export function MentionOverlay({
  value,
  activeRange,
  textareaRef,
}: MentionOverlayProps) {
  const mirrorRef = useRef<HTMLDivElement>(null)
  const ranges = findCommittedMentions(value, activeRange)

  // Keep the mirror's scroll position in lock-step with the textarea so
  // chips stay aligned when the message overflows the bar's max-height.
  // Re-runs whenever ``ranges`` changes because adding/removing a chip can
  // shift the textarea's scrollHeight before the next scroll event fires.
  useEffect(() => {
    const ta = textareaRef.current
    const mirror = mirrorRef.current
    if (!ta || !mirror) return
    const sync = () => {
      mirror.scrollTop = ta.scrollTop
      mirror.scrollLeft = ta.scrollLeft
    }
    sync()
    ta.addEventListener('scroll', sync)
    return () => ta.removeEventListener('scroll', sync)
  }, [textareaRef, ranges.length])

  // No chips? Skip the mirror entirely — keeps the DOM clean when the
  // user is composing a plain message.
  if (ranges.length === 0) return null

  // Build alternating plain text + chip spans in one pass.
  const segments: React.ReactNode[] = []
  let cursor = 0
  for (const r of ranges) {
    if (r.start > cursor) segments.push(value.slice(cursor, r.start))
    segments.push(
      <span
        key={r.start}
        data-testid="mention-chip"
        // Soft accent tint that works in both light and dark themes —
        // same ``color-mix`` recipe the global focus-ring uses.
        style={{
          background:
            'color-mix(in srgb, var(--color-accent) 18%, transparent)',
        }}
        className="rounded-sm"
      >
        {value.slice(r.start, r.end)}
      </span>,
    )
    cursor = r.end
  }
  if (cursor < value.length) segments.push(value.slice(cursor))

  return (
    <div
      ref={mirrorRef}
      aria-hidden="true"
      // ``inset-0`` pins the mirror to the wrapper (which equals the
      // textarea's box). ``text-transparent`` hides the mirror's own
      // glyphs; only chip backgrounds remain visible. Wrapping classes
      // mirror the textarea so chip positions line up glyph-for-glyph.
      className="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words text-sm leading-relaxed text-transparent"
      style={{ maxHeight: '144px' }}
    >
      {segments}
    </div>
  )
}
