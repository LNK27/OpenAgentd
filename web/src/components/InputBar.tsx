import { useRef, useState, useCallback, useImperativeHandle, forwardRef, useEffect, useMemo } from 'react'
import { ArrowUp, Loader2, Paperclip, Square } from 'lucide-react'
import { motion } from 'framer-motion'
import { FilePreviewStrip } from './FilePreviewStrip'
import { VoiceMicButton } from './VoiceMicButton'
import type { AgentCapabilities } from '@/api/types'

// ── Slash commands ──────────────────────────────────────────────────────────

export interface SlashCommand {
  id: string
  label: string
  description: string
}

interface InputBarProps {
  onSubmit: (message: string, files?: File[]) => void
  onStop?: () => void
  onSlashCommand?: (id: string) => void
  slashCommands?: SlashCommand[]
  isStreaming?: boolean
  disabled?: boolean
  placeholder?: string
  autoFocus?: boolean
  capabilities?: AgentCapabilities
  /**
   * When true, the component renders only the inner rounded pill (no
   * top border, no background row chrome). A parent wrapper is expected
   * to provide positioning, shadow, and backdrop. Used by
   * `FloatingInputBar` for the draggable variant.
   */
  floating?: boolean
  /**
   * When true, file previews render below the input container instead of
   * above it. Used by `FloatingInputBar` when the panel is near the top
   * edge of its bounds so previews stay visible.
   */
  filesBelow?: boolean
  /**
   * Optional render-prop for a drag handle rendered anchored to the top
   * edge of the input pill (not the outer wrapper). This keeps the handle
   * pinned to the input regardless of whether file previews are rendered
   * above or below. Used by `FloatingInputBar`.
   */
  renderDragHandle?: () => React.ReactNode
  /**
   * Whether voice input is enabled (from GET /api/speech/config).
   * When false the mic button is shown disabled with an explanatory tooltip.
   * When true the mic button records, transcribes, and appends to input.
   */
  voiceEnabled?: boolean
  /**
   * When true, render the slim icon-only collapsed bar (pencil
   * `inputBar-collapsed-bar`, node `PKjWT`) instead of the full pill.
   * Clicking the bar's chat affordance calls `onUnminimize` so the
   * parent can swap back to the full variant and focus the textarea.
   */
  minimized?: boolean
  /** Called when the user clicks the collapsed bar to expand it. */
  onUnminimize?: () => void
  /** Forwarded to the textarea so the parent can drive minimize-on-blur. */
  onFocus?: () => void
  /**
   * Fired when the textarea blurs. ``canMinimize`` is ``false`` when the
   * input has uncommitted content (text or attachments) the user would
   * lose visual access to if the bar collapsed; the parent should keep
   * the bar expanded in that case.
   */
  onBlur?: (canMinimize: boolean) => void
  /**
   * Called whenever uncommitted content (text or attachments) appears or
   * disappears. The parent uses this to keep the bar expanded when the
   * user adds files via the minimized strip's attach button — without
   * this signal, dropping a file while collapsed would leave the bar
   * collapsed and the new file invisible.
   */
  onHasContentChange?: (hasContent: boolean) => void
}

export interface InputBarHandle {
  focus: () => void
  setValue: (text: string) => void
}

const CHAR_WARN_THRESHOLD = 500

export const InputBar = forwardRef<InputBarHandle, InputBarProps>(function InputBar({
  onSubmit,
  onStop,
  onSlashCommand,
  slashCommands = [],
  isStreaming = false,
  disabled,
  placeholder = 'Message OpenAgentd…',
  autoFocus,
  capabilities,
  floating = false,
  filesBelow = false,
  renderDragHandle,
  voiceEnabled = false,
  minimized = false,
  onUnminimize,
  onFocus,
  onBlur,
  onHasContentChange,
}, ref) {
  const [value, setValue] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [slashMenuIndex, setSlashMenuIndex] = useState(0)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dragCounterRef = useRef(0)

  // Create blob URLs for files — memoized to avoid recreating on every render
  const blobUrls = useMemo(() => {
    const urls = new Map<number, string>()
    files.forEach((file, idx) => {
      urls.set(idx, URL.createObjectURL(file))
    })
    return urls
  }, [files])

  // Revoke blob URLs when files change or on unmount
  useEffect(() => {
    return () => {
      blobUrls.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [blobUrls])

  // ``isMultiLine`` is updated as a side-effect of ``resize`` rather
  // than a separate effect, so the DOM measurement and the React
  // state stay in lock-step (one render cycle, no cascade).
  //
  // Hysteresis on the promote/demote decision:
  //   - Promote (false → true): textarea's scrollHeight exceeds one
  //     line height. Record the value length at the moment of
  //     promotion in ``promoteLengthRef``.
  //   - Demote (true → false): only when the value has no newlines
  //     AND its length is now ≤ 80% of the recorded promote-length.
  //     The 20% guard band absorbs the layout feedback loop where
  //     promoting widens the textarea (so the same content fits on
  //     one line again) which would otherwise demote → re-promote.
  const [isMultiLine, setIsMultiLine] = useState(false)
  const promoteLengthRef = useRef(0)
  const resize = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    // max 6 rows ≈ 144px
    el.style.height = `${Math.min(el.scrollHeight, 144)}px`
    const computed = window.getComputedStyle(el)
    const lineHeight = parseFloat(computed.lineHeight) ||
      parseFloat(computed.fontSize) * 1.5
    const wrapped = el.scrollHeight > lineHeight * 1.4
    const currentLen = el.value.length
    const hasNewline = el.value.includes('\n')

    setIsMultiLine((prev) => {
      if (!prev && wrapped) {
        // Promote: remember the length so we know when it's safe to
        // demote later.
        promoteLengthRef.current = currentLen
        return true
      }
      if (prev && !wrapped && !hasNewline) {
        // Demote candidate. Only commit if length has dropped clearly
        // below the promote-length (80% threshold) — guards against
        // the wrap-promote-rewrap loop in the boundary band.
        const demoteThreshold = Math.floor(promoteLengthRef.current * 0.8)
        if (currentLen <= demoteThreshold) {
          promoteLengthRef.current = 0
          return false
        }
      }
      return prev
    })
  }, [])

  useImperativeHandle(ref, () => ({
    focus: () => textareaRef.current?.focus(),
    setValue: (text: string) => {
      setValue(text)
      // Trigger height recalculation after injecting text programmatically
      requestAnimationFrame(resize)
    },
  }))

  // Auto-focus the textarea whenever the bar transitions from
  // minimized → expanded. The textarea is always mounted (visibility
  // is opacity-driven, not mount-driven) so the ref is reliably
  // populated; we just need to call ``.focus()`` at the transition.
  const prevMinimizedRef = useRef(minimized)
  useEffect(() => {
    const wasMinimized = prevMinimizedRef.current
    prevMinimizedRef.current = minimized
    if (!wasMinimized || minimized) return
    // ``rAF`` lets framer's parent ``layout`` tween start before
    // focus, so the caret doesn't appear mid-morph at the wrong
    // position.
    const id = requestAnimationFrame(() => {
      textareaRef.current?.focus()
    })
    return () => cancelAnimationFrame(id)
  }, [minimized])

  // Plain ref now — no auto-focus-on-mount magic needed since the
  // textarea never unmounts.
  const setTextareaRef = useCallback((node: HTMLTextAreaElement | null) => {
    textareaRef.current = node
  }, [])

  const submit = useCallback(() => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSubmit(trimmed, files.length > 0 ? files : undefined)
    setValue('')
    setFiles([])
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }, [value, disabled, onSubmit, files])

  const buildAcceptString = useCallback((): string => {
    const parts: string[] = [
      'text/plain', 'text/csv', 'text/tab-separated-values', 'text/markdown',
      'application/json', '.txt', '.csv', '.tsv', '.json', '.md',
    ]
    if (capabilities?.input.vision) parts.push('image/*')
    if (capabilities?.input.document_text) {
      parts.push('application/pdf', '.pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx')
    }
    if (capabilities?.input.audio) parts.push('audio/*')
    if (capabilities?.input.video) parts.push('video/*')
    return parts.join(',')
  }, [capabilities])

  const isFileTypeAllowed = useCallback((file: File): boolean => {
    const mimeType = file.type
    const name = file.name.toLowerCase()
    if (
      mimeType.startsWith('text/') || mimeType === 'application/json' ||
      name.endsWith('.txt') || name.endsWith('.csv') || name.endsWith('.tsv') ||
      name.endsWith('.json') || name.endsWith('.md')
    ) return true
    if (capabilities?.input.vision && mimeType.startsWith('image/')) return true
    if (capabilities?.input.document_text && (
      mimeType === 'application/pdf' ||
      mimeType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
      name.endsWith('.pdf') || name.endsWith('.docx')
    )) return true
    if (capabilities?.input.audio && mimeType.startsWith('audio/')) return true
    if (capabilities?.input.video && mimeType.startsWith('video/')) return true
    return false
  }, [capabilities])

  const addFile = useCallback((file: File) => {
    if (!isFileTypeAllowed(file)) return
    setFiles((prev) => [...prev, file])
  }, [isFileTypeAllowed])

  const removeFile = useCallback((index: number) => {
    const oldUrl = blobUrls.get(index)
    if (oldUrl) URL.revokeObjectURL(oldUrl)
    setFiles((prev) => prev.filter((_, i) => i !== index))
  }, [blobUrls])

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items
    if (!items) return
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      if (item.kind === 'file') {
        const file = item.getAsFile()
        if (file && isFileTypeAllowed(file)) {
          e.preventDefault()
          addFile(file)
        }
      }
    }
  }, [addFile, isFileTypeAllowed])

  const handleDragEnter = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    dragCounterRef.current++
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    dragCounterRef.current--
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
  }, [])

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    dragCounterRef.current = 0
    const droppedFiles = e.dataTransfer?.files
    if (!droppedFiles) return
    for (let i = 0; i < droppedFiles.length; i++) {
      const file = droppedFiles[i]
      if (isFileTypeAllowed(file)) {
        addFile(file)
      }
    }
  }, [addFile, isFileTypeAllowed])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.currentTarget.files
    if (!selectedFiles) return
    for (let i = 0; i < selectedFiles.length; i++) {
      const file = selectedFiles[i]
      if (isFileTypeAllowed(file)) {
        addFile(file)
      }
    }
    e.currentTarget.value = ''
  }, [addFile, isFileTypeAllowed])

  // ── Slash command filtering ────────────────────────────────────────────────

  const slashFilter = value.startsWith('/') && !value.includes(' ')
    ? value.slice(1).toLowerCase()
    : null
  const filteredSlashCommands = useMemo(() => {
    if (slashFilter === null || slashCommands.length === 0) return []
    return slashCommands.filter(
      (cmd) =>
        cmd.id.toLowerCase().includes(slashFilter) ||
        cmd.label.toLowerCase().includes(slashFilter)
    )
  }, [slashFilter, slashCommands])

  const slashMenuOpen = slashFilter !== null && filteredSlashCommands.length > 0

  // Clamp index to valid range (handles filter changes reducing the list)
  const clampedIndex = filteredSlashCommands.length > 0
    ? slashMenuIndex % filteredSlashCommands.length
    : 0

  const executeSlashCommand = useCallback((cmd: SlashCommand) => {
    setValue('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    onSlashCommand?.(cmd.id)
  }, [onSlashCommand])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Slash menu navigation
    if (slashMenuOpen && filteredSlashCommands.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSlashMenuIndex((i) => (i + 1) % filteredSlashCommands.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSlashMenuIndex((i) => (i - 1 + filteredSlashCommands.length) % filteredSlashCommands.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        executeSlashCommand(filteredSlashCommands[clampedIndex])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setValue('')
        return
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value)
    setSlashMenuIndex(0)
    resize()
  }

  // ── Voice transcript insertion ────────────────────────────────────────────
  const handleVoiceTranscript = useCallback((transcript: string) => {
    setValue((prev) => {
      const trimmed = prev.trimEnd()
      return trimmed ? `${trimmed} ${transcript}` : transcript
    })
    requestAnimationFrame(resize)
  }, [resize])

  const hasText = value.trim().length > 0
  const canSend = hasText && !disabled
  const canStop = isStreaming && !disabled && onStop != null
  const charCount = value.length
  const showCharCount = charCount > CHAR_WARN_THRESHOLD

  // Surface "has uncommitted content" to the parent so a minimized bar
  // can re-expand when the user attaches a file via the slim strip.
  // Edge-triggered on the boolean — not on the underlying length values —
  // so we only re-render the parent when crossing 0↔1.
  const hasContent = hasText || files.length > 0
  const lastHasContentRef = useRef(hasContent)
  useEffect(() => {
    if (lastHasContentRef.current !== hasContent) {
      lastHasContentRef.current = hasContent
      onHasContentChange?.(hasContent)
    }
  }, [hasContent, onHasContentChange])

  // Single-row, horizontally scrollable list so many attachments don't push
  // the input off-screen vertically. The strip owns its own scroll-position
  // hint (matches pencil's MultiAttachOverflow `attachmentScrollHint`).
  const filePreviews = files.length > 0 ? (
    <FilePreviewStrip
      files={files}
      blobUrls={blobUrls}
      onRemove={removeFile}
      filesBelow={filesBelow}
    />
  ) : null

  // Reusable pill button styles for the action row (attach, mic — pencil
  // calls these `inputBarAttach`, `inputBarMic`: 32×32, rounded-sm border,
  // --color-surface fill).
  const actionBtnClass =
    'flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-(--color-border) bg-(--color-surface) text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:cursor-not-allowed disabled:opacity-50'

  // ── Continuous-morph model ─────────────────────────────────────────
  // The bar has three states that all share the same DOM tree:
  //
  //   Minimized:     [attach] [voice] [📝 message btn] [send-btn]
  //   Expand 1-line: [attach] [voice] [textarea       ] [send]
  //   Expand multi:  [textarea full-width             ]
  //                  [attach] [voice]      [count] [send]
  //
  // The four buttons stay mounted in the same order in every state.
  // The "message slot" (3rd child) morphs between an icon button and a
  // textarea via framer-motion `layout` + AnimatePresence. In multi-
  // line mode the textarea slot escapes to a full-width row above by
  // setting `flex-basis: 100%` on its wrapper, which causes the
  // wrapping flex row to wrap; the buttons settle on the second line
  // automatically. No DOM reordering — just a width tween.
  const handleExpand = () => {
    onUnminimize?.()
  }
  const stopClick = (e: React.MouseEvent) => e.stopPropagation()

  const attachEl = (
    <button
      type="button"
      onClick={(e) => { stopClick(e); fileInputRef.current?.click() }}
      disabled={disabled}
      aria-label="Attach file"
      title="Attach file (paste or drag)"
      className={actionBtnClass}
    >
      <Paperclip size={14} aria-hidden="true" />
    </button>
  )

  const voiceEl = (
    <div onClick={stopClick}>
      <VoiceMicButton
        voiceEnabled={voiceEnabled}
        onTranscript={handleVoiceTranscript}
        disabled={disabled}
      />
    </div>
  )

  // Send/stop is a single 32×32 button matching the other action
  // buttons. In minimized mode the click expands the bar instead of
  // submitting (there's no text yet).
  const sendOrStopEl = canStop && !hasText ? (
    <button
      type="button"
      onClick={(e) => { stopClick(e); onStop?.() }}
      aria-label="Stop generation"
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-(--color-error) bg-(--color-error) text-(--bg-page) transition-colors hover:opacity-90"
    >
      <Square size={12} fill="currentColor" />
    </button>
  ) : (
    <button
      type="button"
      onClick={(e) => {
        stopClick(e)
        if (minimized) handleExpand()
        else submit()
      }}
      disabled={!minimized && !canSend}
      aria-label={minimized ? 'Expand input bar' : 'Send message'}
      title={minimized ? 'Click to write' : 'Send (Enter) · New line (Shift+Enter) · Commands (/)'}
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-(--color-border) bg-(--color-surface) text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:cursor-not-allowed disabled:opacity-50"
    >
      {disabled && !minimized ? (
        <Loader2 size={14} className="animate-spin" aria-hidden="true" />
      ) : (
        <ArrowUp size={14} aria-hidden="true" />
      )}
    </button>
  )

  // Message slot: just the textarea now. The slot's width is driven
  // entirely by the parent ``motion.div`` wrapper — collapsed to 0
  // when minimized (textarea slides out between voice and send), and
  // ``flex-1`` / ``basis-full`` when expanded. The textarea is always
  // mounted so the ref stays valid; ``opacity-0`` + ``pointer-events-
  // none`` while minimized hides it without a remount-induced flicker.
  // Send + click-anywhere on the strip already cover the "expand" tap
  // target, so a dedicated message button would be redundant.
  const messageSlot = (
    <div
      aria-hidden={minimized}
      className={`flex w-full items-center transition-opacity duration-150 ${
        minimized ? 'pointer-events-none opacity-0' : 'opacity-100'
      }`}
    >
      <textarea
        ref={setTextareaRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        onFocus={onFocus}
        onBlur={() => {
          const canMinimize = value.trim().length === 0 && files.length === 0
          onBlur?.(canMinimize)
        }}
        disabled={disabled || minimized}
        placeholder={
          // Clear the placeholder while minimizing so its faint
          // ghost doesn't bleed through the slot opacity fade.
          minimized
            ? ''
            : disabled
              ? 'Waiting for response…'
              : isStreaming
                ? 'Type /stop to interrupt, or click stop…'
                : placeholder
        }
        rows={1}
        autoFocus={autoFocus}
        tabIndex={minimized ? -1 : 0}
        className="w-full resize-none bg-transparent text-sm leading-relaxed text-(--color-text) placeholder-(--color-text-subtle) focus:outline-none disabled:opacity-50"
        style={{ maxHeight: '144px' }}
        aria-label="Message input"
      />
    </div>
  )

  // ── Outer chrome — same in both variants so the AnimatePresence
  //     swap doesn't reflow the page; only the inner pill changes.
  return (
    <div className={floating ? '' : 'border-t border-(--color-border) bg-(--bg-page) px-4 py-3'}>
      <div className={floating ? 'relative' : 'relative mx-auto max-w-3xl'}>
        {/* File previews (above when docked at bottom) — only meaningful
            in expanded mode; hidden during collapse to avoid orphaning. */}
        {!minimized && !filesBelow && filePreviews}

        {/* Slash command menu — floating above the input */}
        {!minimized && slashMenuOpen && filteredSlashCommands.length > 0 && (
          <div className="absolute bottom-full left-0 right-0 z-10 mb-1 overflow-hidden rounded-lg border border-(--color-border-strong) bg-(--color-surface) shadow-md">
            {filteredSlashCommands.map((cmd, idx) => (
              <button
                key={cmd.id}
                onMouseDown={(e) => { e.preventDefault(); executeSlashCommand(cmd) }}
                className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition-colors ${
                  idx === clampedIndex
                    ? 'bg-(--bg-key) text-(--color-text)'
                    : 'text-(--color-text-muted) hover:bg-(--bg-key)'
                }`}
              >
                <span className="font-mono text-xs text-(--color-accent)">/{cmd.id}</span>
                <span className="text-(--color-text-2)">{cmd.description}</span>
              </button>
            ))}
          </div>
        )}

        {/* Input pill wrapper — anchors the drag handle to the input
            itself, so it stays pinned to the pill regardless of file
            previews. ``flex justify-center`` so the self-sized minimized
            strip centers within the panel rather than left-aligning. */}
        <div className={`relative ${minimized ? 'flex justify-center' : ''}`}>
          {renderDragHandle?.()}
          {/* Continuous-morph card. Padding and width are animated as
              numeric motion values so framer has a smooth tween across
              minimized ↔ expanded (the Tailwind class swap is reserved
              for color/shadow which don't affect layout).
              ``flex-wrap`` is the trick that powers single ↔ multi-line:
              when the textarea slot's flex-basis hits 100%, it forces
              its row to wrap and the four buttons land on the line
              below. No reordering. */}
          <motion.div
            initial={false}
            animate={{
              padding: minimized ? 6 : 14,
              width: minimized ? 'auto' : '100%',
            }}
            transition={{ duration: 0.24, ease: [0.32, 0.72, 0, 1] }}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            className={`relative ${minimized ? 'inline-block' : 'block'} rounded-lg border bg-(--color-surface) shadow-sm transition-[border-color,box-shadow,background-color] duration-200 ${
              minimized
                ? 'border-(--color-border) hover:bg-(--bg-key)'
                : 'border-(--color-border-strong) shadow-md focus-within:ring-1 focus-within:ring-(--color-accent)'
            }`}
            style={{ willChange: 'padding, width' }}
          >
            {/* Click-anywhere-to-expand: the wrapper handles bare
                clicks (those that bubble up past the action buttons,
                which call ``stopClick``) so the user can click any
                whitespace in the minimized strip to summon the full
                pill. No ARIA role on the wrapper itself — that would
                hide the descendant interactive controls (button,
                textarea) from the accessibility tree. The dedicated
                Send button already provides a keyboard-accessible
                "Expand input bar" affordance. */}
            <div
              onClick={minimized ? handleExpand : undefined}
              className={`flex w-full flex-wrap items-center gap-2 ${
                minimized ? 'cursor-text' : ''
              }`}
            >
              <motion.div layout className="contents">
                {attachEl}
              </motion.div>
              <motion.div layout className="contents">
                {voiceEl}
              </motion.div>
              {/* Message slot grows to full-row when multi-line via
                  ``basis-full``, which causes the parent
                  ``flex-wrap`` to push the remaining buttons to a new
                  line. The ``order`` keeps the textarea visually
                  first when wrapped, and the buttons follow. */}
              {/* Slot wrapper drives the textarea's width and its
                  collapse-to-zero on minimize. The parent strip has
                  ``gap-2`` (8px between every flex child); a 0-width
                  slot still gets that gap on both sides, leaving a
                  16px ghost gap between voice and send. ``-mx-1``
                  (negative 4px each side) cancels the half-gap on
                  each side so the minimized strip reads as a tight
                  3-button row with no dead space.
                  ``overflow-hidden`` clips the textarea content
                  cleanly during the width tween. Multi-line uses
                  ``basis-full`` to force a wrap onto a new row. */}
              <motion.div
                layout
                className={`min-w-0 overflow-hidden ${
                  minimized
                    ? '-mx-1 w-0 flex-none'
                    : isMultiLine
                      ? 'order-first basis-full'
                      : 'flex-1'
                }`}
              >
                {messageSlot}
              </motion.div>
              {/* Char count surfaces past the warn threshold in any
                  expanded state — long messages typically wrap to
                  multi-line in practice but the count is useful even
                  in single-line for the rare edge case. */}
              {!minimized && showCharCount && (
                <motion.span
                  layout
                  className={`shrink-0 font-mono text-xs ${
                    charCount > 2000 ? 'text-(--color-error)' : 'text-(--color-text-muted)'
                  }`}
                >
                  {charCount}
                </motion.span>
              )}
              {/* Spacer pushes Send to the right edge in multi-line. */}
              {!minimized && isMultiLine && (
                <motion.div layout className="flex-1" />
              )}
              <motion.div layout className="contents">
                {sendOrStopEl}
              </motion.div>
            </div>
          </motion.div>
        </div>

        {/* File previews (below when floating near top) */}
        {!minimized && filesBelow && filePreviews}

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={buildAcceptString()}
          onChange={handleFileSelect}
          className="hidden"
          aria-hidden="true"
        />
      </div>
    </div>
  )
})
