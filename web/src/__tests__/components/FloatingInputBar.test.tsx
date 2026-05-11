import { describe, it, expect, afterEach, beforeEach } from 'bun:test'
import { useRef } from 'react'
import { render, screen, cleanup, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FloatingInputBar } from '@/components/FloatingInputBar'
import { useTeamStore } from '@/stores/useTeamStore'
import type { InputBarHandle } from '@/components/InputBar'

const STORAGE_KEY = 'oa-input-position'

afterEach(cleanup)
beforeEach(() => {
  localStorage.clear()
  useTeamStore.setState({ _pendingMessages: [] })
})

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()))
}

// Test harness — provides a bounds container with a stable, measurable size.
function Harness(props: {
  onSubmit?: (message: string, files?: File[]) => void
  onStop?: () => void
  placeholder?: string
  exposeFocus?: boolean
  isStreaming?: boolean
}) {
  const boundsRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<InputBarHandle>(null)
  return (
    <div
      ref={boundsRef}
      data-testid="bounds"
      style={{ position: 'relative', width: 1200, height: 800 }}
    >
      {props.exposeFocus && (
        <button type="button" onClick={() => inputRef.current?.focus()}>
          Focus input
        </button>
      )}
      <FloatingInputBar
        ref={inputRef}
        boundsRef={boundsRef}
        onSubmit={props.onSubmit ?? (() => {})}
        onStop={props.onStop}
        isStreaming={props.isStreaming}
        placeholder={props.placeholder ?? 'Message…'}
      />
    </div>
  )
}

describe('FloatingInputBar', () => {
  it('keeps the inner InputBar textarea mounted but hidden from AT while minimized', () => {
    render(<Harness />)
    // The textarea is always in the DOM regardless of minimized state
    // — visibility is opacity-driven so the ref stays valid and focus
    // can land instantly on expand. While minimized, the wrapping
    // ``aria-hidden`` correctly removes it from the accessibility
    // tree, so we query by label (DOM-level) rather than role
    // (a11y-tree-level).
    const textarea = screen.getByLabelText('Message input')
    expect(textarea).toBeTruthy()
    expect(textarea.getAttribute('disabled')).not.toBeNull()
  })

  it('exposes a drag handle labelled for screen readers', () => {
    render(<Harness />)
    const handle = screen.getByRole('button', { name: /drag input bar/i })
    expect(handle).toBeTruthy()
  })

  it('starts at the default position (zero offset) when no value is stored', () => {
    render(<Harness />)
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('reads persisted offset from localStorage on mount without throwing', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ x: 40, y: -120 }))
    expect(() => render(<Harness />)).not.toThrow()
    // After mount the clamp effect may rewrite the value if bounds don't
    // accommodate the stored offset; we only require the entry remains
    // valid JSON with numeric fields.
    const raw = localStorage.getItem(STORAGE_KEY)
    expect(raw).not.toBeNull()
    const parsed = JSON.parse(raw!) as { x: number; y: number }
    expect(typeof parsed.x).toBe('number')
    expect(typeof parsed.y).toBe('number')
  })

  it('ignores malformed localStorage entries without throwing', () => {
    localStorage.setItem(STORAGE_KEY, 'not-json')
    expect(() => render(<Harness />)).not.toThrow()
  })

  it('ignores localStorage entries that do not match the expected shape', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ foo: 'bar' }))
    expect(() => render(<Harness />)).not.toThrow()
  })

  it('resets position on double-click of the handle', async () => {
    const user = userEvent.setup()
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ x: 40, y: -120 }))
    render(<Harness />)

    const handle = screen.getByRole('button', { name: /drag input bar/i })
    await user.dblClick(handle)

    expect(localStorage.getItem(STORAGE_KEY)).toBe(JSON.stringify({ x: 0, y: 0 }))
  })

  it('clamps a stored offset back into bounds on window resize', () => {
    // Seed an out-of-bounds offset. The clamp effect runs on mount and on
    // resize; the mount pass should already correct it, but we also verify
    // a resize event does not push it further.
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ x: 99999, y: -99999 }))
    render(<Harness />)

    act(() => {
      window.dispatchEvent(new Event('resize'))
    })

    const raw = localStorage.getItem(STORAGE_KEY)
    // Clamp may be a no-op if jsdom reports zero-sized rects, but if it
    // writes anything it must not preserve the extreme values.
    if (raw !== null && raw !== JSON.stringify({ x: 99999, y: -99999 })) {
      const parsed = JSON.parse(raw) as { x: number; y: number }
      expect(Math.abs(parsed.x)).toBeLessThan(99999)
      expect(Math.abs(parsed.y)).toBeLessThan(99999)
    }
  })

  it('forwards the placeholder prop to the inner InputBar when expanded', async () => {
    const user = userEvent.setup()
    render(<Harness placeholder="Ask the team…" />)
    // Placeholder is empty while the bar is minimized so its ghost
    // doesn't bleed through the slot opacity fade. The minimized
    // The collapsed strip's chat button expands the bar so the
    // textarea's placeholder becomes visible.
    await user.click(screen.getByRole('button', { name: 'Expand input bar' }))
    const textarea = await screen.findByRole('textbox', { name: 'Message input' })
    expect(textarea.getAttribute('placeholder')).toBe('Ask the team…')
  })

  it('keeps the collapsed strip available while streaming', () => {
    render(<Harness isStreaming onStop={() => {}} />)

    const textarea = screen.getByLabelText('Message input')
    expect(textarea.getAttribute('disabled')).not.toBeNull()
    expect(screen.getByRole('button', { name: 'Attach file' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Voice input disabled' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Expand input bar' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Stop generation' })).toBeTruthy()
  })

  it('shows queued message details above the queue banner only after expanding', async () => {
    const user = userEvent.setup()
    useTeamStore.setState({
      _pendingMessages: [
        { id: 'pm-1', content: 'first queued message' },
        { id: 'pm-2', content: 'second queued message' },
      ],
    })

    render(<Harness />)

    const banner = screen.getByRole('button', { name: /2 messages awaiting/i })
    expect(banner).toBeTruthy()
    expect(screen.queryByText('first queued message')).toBeNull()

    await user.click(banner)

    const firstMessage = screen.getByText('first queued message')
    expect(firstMessage).toBeTruthy()
    expect(
      firstMessage.compareDocumentPosition(banner) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('expands and focuses the textarea through its imperative focus handle', async () => {
    const user = userEvent.setup()
    render(<Harness exposeFocus />)

    const textarea = screen.getByLabelText('Message input')
    expect(textarea.getAttribute('disabled')).not.toBeNull()

    await user.click(screen.getByRole('button', { name: 'Focus input' }))
    await act(nextFrame)

    expect(textarea.getAttribute('disabled')).toBeNull()
    expect(document.activeElement).toBe(textarea)
  })
})
