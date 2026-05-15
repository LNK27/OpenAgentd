import { describe, it, expect, afterEach, mock, beforeEach } from 'bun:test'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { create } from 'zustand'
import { VoiceMicButton } from '@/components/VoiceMicButton'

const originalFetch = globalThis.fetch
const originalPlatform = navigator.platform

afterEach(() => {
  cleanup()
  globalThis.fetch = originalFetch
  delete (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
  Object.defineProperty(navigator, 'platform', {
    value: originalPlatform,
    configurable: true,
  })
})

// ── Mocks ─────────────────────────────────────────────────────────────────────

type TranscribeMode = 'success' | 'empty' | 'pending' | 'error'
let transcribeMode: TranscribeMode = 'success'

type Toast = { tone: string; title: string; description?: string }
type ToastWithId = Toast & { id: string }

// useToastStore — capture pushed toasts.
const pushedToasts: Toast[] = []
const mockPush = mock((...args: unknown[]) => {
  pushedToasts.push(args[0] as Toast)
})
const dialogAsk = mock(async () => false)
const invokeCalls: string[] = []

const useToastStoreMock = create<{
  toasts: ToastWithId[]
  push: (t: Toast) => void
  dismiss: (id: string) => void
}>()((set) => ({
  toasts: [],
  push: (t: Toast) => {
    mockPush(t)
    set((state) => ({
      toasts: [
        ...state.toasts,
        { id: `t-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`, ...t },
      ],
    }))
  },
  dismiss: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }))
  },
}))

mock.module('@/stores/useToastStore', () => ({
  useToastStore: useToastStoreMock,
}))

mock.module('@tauri-apps/plugin-dialog', () => ({
  ask: dialogAsk,
}))

mock.module('@tauri-apps/api/core', () => ({
  invoke: (command: string) => {
    invokeCalls.push(command)
    return Promise.resolve()
  },
}))

// MediaRecorder stub — not available in Happy DOM.
class MockMediaRecorder extends EventTarget {
  mimeType = 'audio/webm'
  ondataavailable: ((e: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null

  start() {
    // Immediately fire a data chunk
    this.ondataavailable?.({ data: new Blob(['audio'], { type: 'audio/webm' }) })
  }

  stop() {
    this.onstop?.()
  }
}

// getUserMedia stub
function makeStreamStub() {
  return {
    getTracks: () => [{ stop: mock(() => {}) }],
  }
}

beforeEach(() => {
  pushedToasts.length = 0
  mockPush.mockReset()
  dialogAsk.mockReset()
  dialogAsk.mockImplementation(async () => false)
  invokeCalls.length = 0
  useToastStoreMock.setState({ toasts: [] })
  transcribeMode = 'success'
  globalThis.fetch = mock(async (input: unknown) => {
    if (!String(input).startsWith('/api/speech/transcribe')) {
      return new Response(null, { status: 404 })
    }
    if (transcribeMode === 'pending') return new Promise<Response>(() => {})
    if (transcribeMode === 'error') {
      return new Response(JSON.stringify({ detail: 'Server error' }), { status: 500 })
    }
    return new Response(JSON.stringify({ text: transcribeMode === 'empty' ? '' : 'hello world' }))
  }) as typeof fetch

  // Install MediaRecorder + getUserMedia stubs
  ;(global as Record<string, unknown>).MediaRecorder = MockMediaRecorder
  Object.defineProperty(navigator, 'mediaDevices', {
    value: { getUserMedia: mock(async () => makeStreamStub()) },
    configurable: true,
    writable: true,
  })
})

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('VoiceMicButton — disabled state', () => {
  it('renders with MicOff icon when voice is disabled', () => {
    render(<VoiceMicButton voiceEnabled={false} onTranscript={() => {}} />)
    const btn = screen.getByLabelText('Voice input disabled')
    expect(btn).toBeTruthy()
  })

  it('button is disabled when voiceEnabled is false', () => {
    render(<VoiceMicButton voiceEnabled={false} onTranscript={() => {}} />)
    const btn = screen.getByLabelText('Voice input disabled') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
  })

  it('shows the disabled tooltip', () => {
    render(<VoiceMicButton voiceEnabled={false} onTranscript={() => {}} />)
    const btn = screen.getByLabelText('Voice input disabled')
    expect(btn.getAttribute('title')).toContain('Voice mode is disabled')
    expect(btn.getAttribute('title')).toContain('settings')
  })

  it('exact disabled tooltip text matches spec', () => {
    render(<VoiceMicButton voiceEnabled={false} onTranscript={() => {}} />)
    const btn = screen.getByLabelText('Voice input disabled')
    expect(btn.getAttribute('title')).toBe(
      'Voice mode is disabled. Enable it in settings to use voice input.'
    )
  })
})

describe('VoiceMicButton — idle state', () => {
  it('renders Mic icon when idle and enabled', () => {
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)
    const btn = screen.getByLabelText('Start voice input')
    expect(btn).toBeTruthy()
  })

  it('button is enabled when voiceEnabled is true', () => {
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)
    const btn = screen.getByLabelText('Start voice input') as HTMLButtonElement
    expect(btn.disabled).toBe(false)
  })

  it('button is disabled when disabled prop is true', () => {
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} disabled={true} />)
    const btn = screen.getByLabelText('Start voice input') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
  })
})

describe('VoiceMicButton — recording state', () => {
  it('transitions to recording state on click', async () => {
    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    const btn = screen.getByLabelText('Start voice input')
    await user.click(btn)

    await waitFor(() => {
      expect(screen.getByLabelText('Stop recording')).toBeTruthy()
    })
  })

  it('has data-recording attribute set when recording', async () => {
    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    await user.click(screen.getByLabelText('Start voice input'))

    await waitFor(() => {
      const btn = screen.getByLabelText('Stop recording')
      expect(btn.getAttribute('data-recording')).toBe('true')
    })
  })
})

describe('VoiceMicButton — transcript insertion', () => {
  it('calls onTranscript with transcribed text on stop', async () => {
    const user = userEvent.setup()
    let captured = ''
    const onTranscript = (t: string) => { captured = t }

    render(<VoiceMicButton voiceEnabled={true} onTranscript={onTranscript} />)

    // Start recording
    await user.click(screen.getByLabelText('Start voice input'))
    await waitFor(() => screen.getByLabelText('Stop recording'))

    // Stop recording
    await user.click(screen.getByLabelText('Stop recording'))

    await waitFor(() => {
      expect(captured).toBe('hello world')
    })
  })

  it('shows transcribing state while postTranscribe is pending', async () => {
    transcribeMode = 'pending'

    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    await user.click(screen.getByLabelText('Start voice input'))
    await waitFor(() => screen.getByLabelText('Stop recording'))
    await user.click(screen.getByLabelText('Stop recording'))

    expect(await screen.findByLabelText('Transcribing…')).toBeTruthy()
    expect(screen.getByLabelText('Transcribing…').hasAttribute('disabled')).toBe(true)
  })

  it('returns to idle state after successful transcription', async () => {
    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    await user.click(screen.getByLabelText('Start voice input'))
    await waitFor(() => screen.getByLabelText('Stop recording'))

    await user.click(screen.getByLabelText('Stop recording'))

    await waitFor(() => {
      expect(screen.getByLabelText('Start voice input')).toBeTruthy()
    })
  })

  it('does not call onTranscript when transcription returns empty text', async () => {
    transcribeMode = 'empty'

    const user = userEvent.setup()
    let called = false
    const onTranscript = () => { called = true }

    render(<VoiceMicButton voiceEnabled={true} onTranscript={onTranscript} />)

    await user.click(screen.getByLabelText('Start voice input'))
    await waitFor(() => screen.getByLabelText('Stop recording'))
    await user.click(screen.getByLabelText('Stop recording'))

    await waitFor(() => screen.getByLabelText('Start voice input'))
    expect(called).toBe(false)
  })
})

describe('VoiceMicButton — error handling', () => {
  it('shows toast on transcription failure and returns to idle', async () => {
    transcribeMode = 'error'

    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    await user.click(screen.getByLabelText('Start voice input'))
    await waitFor(() => screen.getByLabelText('Stop recording'))
    await user.click(screen.getByLabelText('Stop recording'))

    await waitFor(() => screen.getByLabelText('Start voice input'))
    expect(mockPush).toHaveBeenCalled()
    const call = mockPush.mock.calls[0][0] as Toast
    expect(call.tone).toBe('error')
  })

  it('shows toast on mic permission denial and stays idle', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      value: {
        getUserMedia: mock(async () => {
          throw new Error('Permission denied')
        }),
      },
      configurable: true,
      writable: true,
    })

    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    await user.click(screen.getByLabelText('Start voice input'))

    await waitFor(() => expect(mockPush).toHaveBeenCalled())
    const call = mockPush.mock.calls[0][0] as Toast
    expect(call.tone).toBe('error')

    // Should remain in idle state
    expect(screen.getByLabelText('Start voice input')).toBeTruthy()
  })

  it('uses a native desktop dialog for macOS microphone denial', async () => {
    ;(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {}
    Object.defineProperty(navigator, 'platform', {
      value: 'MacIntel',
      configurable: true,
    })
    Object.defineProperty(navigator, 'mediaDevices', {
      value: {
        getUserMedia: mock(async () => {
          throw new DOMException(
            'The request is not allowed by the user agent or the platform in the current context, possibly because the user denied permission.',
            'NotAllowedError'
          )
        }),
      },
      configurable: true,
      writable: true,
    })

    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    await user.click(screen.getByLabelText('Start voice input'))

    await waitFor(() => expect(dialogAsk).toHaveBeenCalled())
    expect(mockPush).not.toHaveBeenCalled()
    expect(invokeCalls).toEqual([])
  })

  it('opens macOS Microphone settings when the native dialog is accepted', async () => {
    dialogAsk.mockImplementation(async () => true)
    ;(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {}
    Object.defineProperty(navigator, 'platform', {
      value: 'MacIntel',
      configurable: true,
    })
    Object.defineProperty(navigator, 'mediaDevices', {
      value: {
        getUserMedia: mock(async () => {
          throw new DOMException('Permission denied', 'NotAllowedError')
        }),
      },
      configurable: true,
      writable: true,
    })

    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    await user.click(screen.getByLabelText('Start voice input'))

    await waitFor(() => expect(invokeCalls).toEqual(['open_macos_microphone_settings']))
  })
})
