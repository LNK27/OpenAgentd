import { useRef, useState, useCallback, useImperativeHandle, forwardRef, useEffect, useMemo } from 'react'
import { ArrowUp, File, Folder, Loader2, MessageCircle, Paperclip, Square } from 'lucide-react'
import { motion } from 'framer-motion'
import { FilePreviewStrip } from './FilePreviewStrip'
import { VoiceMicButton } from './VoiceMicButton'
import { findActiveMention, rankFileRefs, type FileRef } from './InputBar.mentions'
import { MentionOverlay } from './InputBar.overlay'
import type { AgentCapabilities } from '@/api/types'
import { useReducedMotion } from '@/hooks/useReducedMotion'

// Re-export the public type so callers can import ``FileRef`` from this module
// alongside the component. (The helper ``findActiveMention`` is imported from
// './InputBar.mentions' directly to keep this file free of non-component
// runtime exports — react-refresh requirement.)
export type { FileRef } from './InputBar.mentions'

// ── Slash commands ──────────────────────────────────────────────────────────

export interface SlashCommand {
  id: string
  label: string
  description: string
  /**
   * When true, picking this command from the menu inserts ``/<id> `` into
   * the textarea and leaves the caret after the trailing space — for
   * commands that take free-form arguments the user still needs to type
   * (e.g. backend-discovered commands with ``$ARGUMENTS``). The default
   * is the legacy behaviour: the input is cleared and the parent's
   * ``onSlashCommand`` runs immediately.
   */
  keepInputOpen?: boolean
}

interface InputBarProps {
  onSubmit: (message: string, files?: File[]) => void
  onStop?: () => void
  onSlashCommand?: (id: string) => void
  slashCommands?: SlashCommand[]
  /**
   * Workspace files/folders the user can reference with `@`. When the list is
   * empty (or omitted) the picker stays dormant — the `@` character behaves as
   * plain text.
   */
  fileRefs?: FileRef[]
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
   * When true, render the slim collapsed action strip instead of the full
   * pill. The strip keeps file, voice, chat, and send/stop controls visible.
   * Clicking the chat affordance calls `onUnminimize` so the parent can swap
   * back to the full variant and focus the textarea.
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
  setFiles: (files: File[]) => void
}

const CHAR_WARN_THRESHOLD = 500

export const InputBar = forwardRef<InputBarHandle, InputBarProps>(function InputBar({
  onSubmit,
  onStop,
  onSlashCommand,
  slashCommands = [],
  fileRefs = [],
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
  const [mentionMenuIndex, setMentionMenuIndex] = useState(0)
  // The active @-mention window (positions in ``value``) — null when no
  // mention is being edited at the caret. Recomputed on every keystroke
  // and on caret-only moves (arrow keys, clicks) via ``syncMention``.
  const [mentionRange, setMentionRange] = useState<
    { start: number; end: number; query: string } | null
  >(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dragCounterRef = useRef(0)
  const prefersReducedMotion = useReducedMotion()

  // Refresh the active mention window from the current caret position. Called
  // whenever the caret might have moved without the value changing (arrow keys,
  // click, focus from history nav). Cheap; just a left-scan from the caret.
  const syncMention = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    const caret = el.selectionStart ?? el.value.length
    const next = findActiveMention(el.value, caret)
    setMentionRange((prev) => {
      if (!prev && !next) return prev
      if (
        prev && next &&
        prev.start === next.start &&
        prev.end === next.end &&
        prev.query === next.query
      ) return prev
      return next
    })
  }, [])

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
    // max 5 rows ≈ 120px
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
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
      // Programmatic value replacement invalidates any open mention picker —
      // its ``start``/``end`` indices refer to the old text.
      setMentionRange(null)
      // Trigger height recalculation after injecting text programmatically
      requestAnimationFrame(resize)
    },
    setFiles: (nextFiles: File[]) => {
      setFiles(nextFiles)
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
    // Clear the mention picker too — it tracks positions inside the value
    // we just wiped. Without this, a picker that was open at submit time
    // would render above the now-empty textarea on the next paint.
    setMentionRange(null)
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
  const slashMenuId = 'inputbar-slash-menu'
  const mentionMenuId = 'inputbar-mention-menu'

  // Clamp index to valid range (handles filter changes reducing the list)
  const clampedIndex = filteredSlashCommands.length > 0
    ? slashMenuIndex % filteredSlashCommands.length
    : 0

  // Refs for slash option buttons so the highlighted row stays visible when
  // the list overflows ``max-h-64``. Same pattern as the mention picker —
  // truncate to the current option count inside the effect, not during
  // render, so unmounted-but-still-recorded nulls don't accumulate.
  const slashOptionRefs = useRef<(HTMLButtonElement | null)[]>([])
  useEffect(() => {
    slashOptionRefs.current.length = filteredSlashCommands.length
    if (!slashMenuOpen) return
    const el = slashOptionRefs.current[clampedIndex]
    el?.scrollIntoView({ block: 'nearest' })
  }, [clampedIndex, slashMenuOpen, filteredSlashCommands])

  const executeSlashCommand = useCallback((cmd: SlashCommand) => {
    if (cmd.keepInputOpen) {
      // Insert ``/<id> `` and keep the textarea focused so the user can
      // append arguments. Submission is what triggers the action — the
      // parent's onSubmit handler inspects the raw text.
      const next = `/${cmd.id} `
      setValue(next)
      const el = textareaRef.current
      if (el) {
        requestAnimationFrame(() => {
          el.focus()
          el.setSelectionRange(next.length, next.length)
          resize()
        })
      }
      return
    }
    setValue('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    onSlashCommand?.(cmd.id)
  }, [onSlashCommand, resize])

  // ── @-mention filtering ────────────────────────────────────────────────────

  const MENTION_MAX_RESULTS = 20

  const filteredMentions = useMemo(() => {
    if (!mentionRange || fileRefs.length === 0) return [] as FileRef[]
    return rankFileRefs(fileRefs, mentionRange.query, MENTION_MAX_RESULTS)
  }, [mentionRange, fileRefs])

  const mentionMenuOpen = mentionRange !== null && filteredMentions.length > 0
  const clampedMentionIndex = filteredMentions.length > 0
    ? mentionMenuIndex % filteredMentions.length
    : 0

  // Refs for each rendered option so the highlighted one can be scrolled
  // into view when the user arrow-keys past the visible window. The array is
  // truncated to the current option count inside the effect (not during
  // render) so unmounted-but-still-recorded nulls don't accumulate.
  const mentionOptionRefs = useRef<(HTMLButtonElement | null)[]>([])
  useEffect(() => {
    mentionOptionRefs.current.length = filteredMentions.length
    if (!mentionMenuOpen) return
    const el = mentionOptionRefs.current[clampedMentionIndex]
    // ``block: 'nearest'`` only scrolls when the item is actually outside the
    // viewport, so it's a no-op for items already visible — no jitter on the
    // initial render or when the user arrows within the visible band.
    el?.scrollIntoView({ block: 'nearest' })
  }, [clampedMentionIndex, mentionMenuOpen, filteredMentions])

  /** Replace the active @-token with the selected reference plus a trailing space. */
  const insertMention = useCallback((ref: FileRef) => {
    if (!mentionRange) return
    const el = textareaRef.current
    const display = ref.type === 'directory' ? `${ref.path}/` : ref.path
    const insertion = `@${display} `
    const before = value.slice(0, mentionRange.start)
    const after = value.slice(mentionRange.end)
    const next = before + insertion + after
    setValue(next)
    setMentionRange(null)
    setMentionMenuIndex(0)
    // Move the caret to just after the inserted token + trailing space. The
    // textarea state lags by one render so we defer with rAF.
    if (el) {
      const caret = before.length + insertion.length
      requestAnimationFrame(() => {
        el.focus()
        el.setSelectionRange(caret, caret)
        resize()
      })
    }
  }, [mentionRange, value, resize])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // IME composition guard: when a user is mid-composition (CJK, etc.) the
    // browser fires ``keydown`` with ``isComposing`` true for keys that drive
    // the IME (Enter commits the candidate, Arrow keys navigate it). We must
    // not hijack those — let the IME consume them. ``keyCode === 229`` is the
    // legacy fallback for browsers that don't surface ``isComposing`` on the
    // React synthetic event.
    if (e.nativeEvent.isComposing || e.keyCode === 229) return

    // Mention menu navigation takes priority over slash navigation: a
    // composed message can contain both `/cmd` (only valid at start) and
    // `@foo` (anywhere), and the mention is the active one whenever the
    // caret is sitting inside an `@`-token.
    if (mentionMenuOpen && filteredMentions.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setMentionMenuIndex((i) => (i + 1) % filteredMentions.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setMentionMenuIndex((i) => (i - 1 + filteredMentions.length) % filteredMentions.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        insertMention(filteredMentions[clampedMentionIndex])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setMentionRange(null)
        return
      }
    }

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
    setMentionMenuIndex(0)
    // ``selectionStart`` is already at the post-change caret position by the
    // time React fires onChange.
    const caret = e.target.selectionStart ?? e.target.value.length
    const next = findActiveMention(e.target.value, caret)
    setMentionRange(next)
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
    'flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-(--color-border) bg-(--color-surface) text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:cursor-not-allowed disabled:opacity-50'

  // Three states share one DOM tree: minimized, single-line, multi-line.
  // Multi-line is triggered by the slot's flex-basis:100% which wraps the
  // row so action buttons land on the line below — no DOM reordering.
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

  const chatEl = minimized ? (
    <button
      type="button"
      onClick={(e) => { stopClick(e); handleExpand() }}
      aria-label="Expand input bar"
      title="Click to write"
      className={actionBtnClass}
    >
      <MessageCircle size={14} aria-hidden="true" />
    </button>
  ) : null

  const activePopupId = mentionMenuOpen ? mentionMenuId : slashMenuOpen ? slashMenuId : undefined
  const activeOptionId = mentionMenuOpen
    ? `${mentionMenuId}-option-${clampedMentionIndex}`
    : slashMenuOpen
      ? `${slashMenuId}-option-${clampedIndex}`
      : undefined

  const sendOrStopEl = canStop && !hasText ? (
    <button
      type="button"
      onClick={(e) => { stopClick(e); onStop?.() }}
      aria-label="Stop generation"
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-(--color-error) bg-(--color-error) text-(--bg-page) transition-colors hover:opacity-90"
    >
      <Square size={12} fill="currentColor" />
    </button>
  ) : (
    <button
      type="button"
      onClick={(e) => {
        stopClick(e)
        submit()
      }}
      disabled={!canSend}
      aria-label="Send message"
      title="Send (Enter) · New line (Shift+Enter) · Commands (/)"
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-(--color-border) bg-(--color-surface) text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:cursor-not-allowed disabled:opacity-50"
    >
      {disabled && !minimized ? (
        <Loader2 size={14} className="animate-spin" aria-hidden="true" />
      ) : (
        <ArrowUp size={14} aria-hidden="true" />
      )}
    </button>
  )

  // The textarea stays mounted while minimized (opacity + pointer-events
  // toggle) so the ref stays valid and there's no remount flicker.
  const messageSlot = (
    <div
      aria-hidden={minimized}
      className={`flex w-full items-center transition-opacity duration-150 ${
        minimized ? 'pointer-events-none opacity-0' : 'opacity-100'
      }`}
    >
      {/* Position context for the chip overlay. ``relative`` + ``w-full``
          keep the overlay's bounding box equal to the textarea's, so
          chips line up pixel-for-pixel with the text glyphs above them.
          Intentionally not nesting the textarea's props one level deeper —
          keeps the diff against the prior version minimal. */}
      <div className="relative w-full">
      <MentionOverlay
        value={value}
        activeRange={mentionRange}
        textareaRef={textareaRef}
        fileRefs={fileRefs}
      />
      <textarea
        ref={setTextareaRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        // Caret-only moves (arrow keys, Home/End) don't fire onChange but
        // they can land the caret inside an existing `@token`. ``onSelect``
        // is the React-supported event that fires on selection / caret
        // moves and works in jsdom (used by our tests), so it's the
        // right hook for keeping the picker in sync.
        onSelect={syncMention}
        onClick={syncMention}
        onPaste={handlePaste}
        onFocus={onFocus}
        onBlur={() => {
          const canMinimize = value.trim().length === 0 && files.length === 0
          onBlur?.(canMinimize)
          // Close the picker on blur — clicks on its items use ``onMouseDown``
          // with ``preventDefault`` (see below) so they fire before the
          // textarea blurs and the menu still gets to commit its choice.
          setMentionRange(null)
        }}
        disabled={disabled || minimized}
        placeholder={
          minimized
            ? ''
            : disabled
              ? 'Waiting for response…'
              : isStreaming
                ? 'Queue a follow-up or /stop…'
                : placeholder
        }
        rows={1}
        autoFocus={autoFocus}
        tabIndex={minimized ? -1 : 0}
        // ``p-0`` zeroes WebKit's asymmetric default textarea padding (WKWebView
        // in the macOS Tauri shell ships ~2px top + ~1px bottom that bias the
        // single-line baseline upward). ``align-middle`` keeps the textarea's
        // bounding box centred in the flex row instead of sitting on the
        // baseline of adjacent inline-block buttons. Together they make the
        // placeholder sit vertically centred against the 28px action buttons
        // both in Chrome (web build) and WKWebView (desktop build).
        //
        // ``text-transparent`` + ``caret-color`` hides the textarea's own
        // glyphs so the syntax-highlight overlay (``MentionOverlay``) is
        // the one painting visible text. The caret stays visible. The
        // placeholder is exempt from ``text-transparent`` — it's owned by
        // ``::placeholder`` and ``placeholder-(--color-text-subtle)``
        // keeps it readable.
        // ``scrollbar-none`` hides the textarea's own scrollbar. Without it,
        // the textarea grows a ~15px-wide vertical scrollbar once content
        // exceeds ``maxHeight``, which narrows its inner text-width and makes
        // it wrap a few characters earlier than the overlay mirror (which
        // has no scrollbar). The wrap-point drift is invisible while typing
        // but the native spellcheck squiggle is anchored to textarea text
        // positions, so it ends up under the wrong overlay word and drifts
        // further with every scroll. The wrapper around the overlay handles
        // overflow via the overlay's ``overflow-hidden`` + scroll sync.
        className="block w-full resize-none scrollbar-none bg-transparent p-0 align-middle text-sm leading-relaxed break-words text-transparent caret-(--color-text) placeholder-(--color-text-subtle) selection:bg-(--color-accent)/30 selection:text-(--color-text) focus:outline-none disabled:opacity-50"
        // Cap matches the ``resize()`` ceiling above so the JS-driven height
        // and the CSS limit stay in lockstep.
        style={{ maxHeight: '120px' }}
        // Spellcheck disabled: the squiggle is painted by the browser under
        // the textarea's own glyphs, but the visible text comes from the
        // overlay mirror. Even with identical font/wrap/scroll the two
        // text-layout paths drift by 1–2px, leaving the squiggle a word
        // off. Same call Discord/Slack/ChatGPT make for the same reason.
        spellCheck={false}
        aria-label="Message input"
        aria-expanded={mentionMenuOpen || slashMenuOpen}
        aria-controls={activePopupId}
        aria-activedescendant={activeOptionId}
      />
      </div>
    </div>
  )

  return (
    <div className={floating ? '' : 'border-t border-(--color-border) bg-(--bg-page) px-4 py-3'}>
      <div className={floating ? 'relative' : 'relative mx-auto max-w-3xl'}>
        {!minimized && !filesBelow && filePreviews}

        {!minimized && slashMenuOpen && filteredSlashCommands.length > 0 && (
          <div
            id={slashMenuId}
            role="listbox"
            aria-label="Slash commands"
            className="absolute bottom-full left-0 right-0 z-10 mb-1 max-h-64 overflow-y-auto rounded-lg border border-(--color-border-strong) bg-(--color-surface) shadow-md"
          >
            {filteredSlashCommands.map((cmd, idx) => (
              <button
                key={cmd.id}
                id={`${slashMenuId}-option-${idx}`}
                role="option"
                aria-selected={idx === clampedIndex}
                ref={(node) => { slashOptionRefs.current[idx] = node }}
                onMouseDown={(e) => { e.preventDefault(); executeSlashCommand(cmd) }}
                className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition-colors ${
                  idx === clampedIndex
                    ? 'bg-(--bg-key) text-(--color-text)'
                    : 'text-(--color-text-muted) hover:bg-(--bg-key)'
                }`}
              >
                {/* Name keeps its full width (``shrink-0``); description gets
                    the remaining space and truncates with an ellipsis. The
                    container already constrains width via the input's
                    ``max-w-3xl`` wrapper, so we don't need a max-width here. */}
                <span className="shrink-0 font-mono text-xs text-(--color-accent)">/{cmd.id}</span>
                <span className="min-w-0 flex-1 truncate text-(--color-text-2)">
                  {cmd.description}
                </span>
              </button>
            ))}
          </div>
        )}

        {/* @-mention picker — same visual treatment as the slash menu, but
            scrollable since the workspace can contain hundreds of files. The
            list is capped to MENTION_MAX_RESULTS so the popover stays compact;
            the user narrows the list by typing. */}
        {!minimized && mentionMenuOpen && (
          <div
            id={mentionMenuId}
            role="listbox"
            aria-label="Reference workspace file"
            className="absolute bottom-full left-0 right-0 z-10 mb-1 max-h-64 overflow-y-auto rounded-lg border border-(--color-border-strong) bg-(--color-surface) shadow-md"
          >
            {filteredMentions.map((ref, idx) => {
              const isDir = ref.type === 'directory'
              // Show the basename emphasised, the parent directory dimmed.
              // For a top-level entry (no slash) the whole path is the
              // basename, so there's nothing to dim — display falls back
              // to a single span.
              const slash = ref.path.lastIndexOf('/')
              const parent = slash === -1 ? '' : ref.path.slice(0, slash + 1)
              const basename = slash === -1 ? ref.path : ref.path.slice(slash + 1)
              return (
                <button
                  key={`${ref.type}:${ref.path}`}
                  id={`${mentionMenuId}-option-${idx}`}
                  ref={(node) => { mentionOptionRefs.current[idx] = node }}
                  role="option"
                  aria-selected={idx === clampedMentionIndex}
                  // ``onMouseDown`` + ``preventDefault`` runs before the
                  // textarea's ``onBlur`` clears the picker, so the click
                  // actually reaches our handler.
                  onMouseDown={(e) => { e.preventDefault(); insertMention(ref) }}
                  className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors ${
                    idx === clampedMentionIndex
                      ? 'bg-(--bg-key) text-(--color-text)'
                      : 'text-(--color-text-muted) hover:bg-(--bg-key)'
                  }`}
                >
                  {isDir ? (
                    <Folder className="size-4 shrink-0 text-(--color-accent)" aria-hidden />
                  ) : (
                    <File className="size-4 shrink-0 text-(--color-text-subtle)" aria-hidden />
                  )}
                  <span className="min-w-0 flex-1 truncate font-mono text-xs">
                    {parent && (
                      <span className="text-(--color-text-subtle)">{parent}</span>
                    )}
                    <span className="text-(--color-text)">{basename}</span>
                    {isDir && <span className="text-(--color-text-subtle)">/</span>}
                  </span>
                </button>
              )
            })}
          </div>
        )}

        {/* ``flex justify-center`` centers the self-sized minimized pill. */}
        <div className={`relative ${minimized ? 'flex justify-center' : ''}`}>
          {renderDragHandle?.()}
          <motion.div
            layout
            initial={false}
            animate={{ padding: minimized ? 6 : 8 }}
            transition={{ duration: prefersReducedMotion ? 0.01 : 0.24, ease: [0.32, 0.72, 0, 1] }}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            className={`relative block rounded-lg border bg-(--color-surface) transition-[border-color,box-shadow,background-color] duration-200 ${
              minimized
                ? 'w-fit border-(--color-border) shadow-sm hover:bg-(--bg-key)'
                : 'w-full border-(--color-border-strong) shadow-md focus-within:ring-1 focus-within:ring-(--color-accent)'
            }`}
          >
            {/* Click-anywhere-to-expand on bare strip whitespace. Action
                buttons call stopClick so they don't trigger this. No ARIA
                role here — the Send button is the keyboard-accessible
                "Expand input bar" affordance. */}
            <div
              onClick={minimized ? handleExpand : undefined}
              className={`flex w-full flex-wrap items-center gap-2 ${
                minimized ? 'cursor-text' : ''
              }`}
            >
              {attachEl}
              {voiceEl}
              {chatEl}
              {/* Slot snaps w-0 ↔ flex-1 in lockstep with the card's
                  w-fit ↔ w-full. ``-ml-2`` absorbs the parent gap-2
                  when collapsed. */}
              <div
                style={{
                  flexBasis: !minimized && isMultiLine ? '100%' : undefined,
                  order: !minimized && isMultiLine ? -1 : 0,
                }}
                className={`min-w-0 overflow-hidden ${
                  minimized ? 'w-0 -ml-2' : 'flex-1'
                }`}
              >
                {messageSlot}
              </div>
              {!minimized && showCharCount && (
                <span
                  className={`shrink-0 font-mono text-xs ${
                    charCount > 2000 ? 'text-(--color-error)' : 'text-(--color-text-muted)'
                  }`}
                >
                  {charCount}
                </span>
              )}
              {/* Spacer pushes Send to the right edge in multi-line. */}
              {!minimized && isMultiLine && <div className="flex-1" />}
              {sendOrStopEl}
            </div>
          </motion.div>
        </div>

        {!minimized && filesBelow && filePreviews}

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
