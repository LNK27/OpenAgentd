import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { create } from 'zustand'
import { VoiceMicButton } from '@/components/VoiceMicButton'

afterEach(() => {
  cleanup()
  delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition
  delete (window as Window & { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition
  Object.defineProperty(navigator, 'mediaDevices', {
    value: undefined,
    configurable: true,
  })
})

type Toast = { tone: string; title: string; description?: string }
type ToastWithId = Toast & { id: string }

const pushedToasts: Toast[] = []
const mockPush = mock((...args: unknown[]) => {
  pushedToasts.push(args[0] as Toast)
})

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

let activeRecognition: MockSpeechRecognition | null = null
let startThrows = false
let getUserMediaThrows = false
const mockTrackStop = mock(() => {})
const mockGetUserMedia = mock(async () => {
  if (getUserMediaThrows) throw new Error('Microphone denied')
  return {
    getTracks: () => [{ stop: mockTrackStop }],
  }
})

class MockSpeechRecognition {
  continuous = false
  interimResults = false
  lang = ''
  onresult: ((event: { resultIndex: number; results: Array<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null = null
  onerror: ((event: { error?: string; message?: string }) => void) | null = null
  onaudiostart: (() => void) | null = null
  onspeechstart: (() => void) | null = null
  onend: (() => void) | null = null

  start() {
    if (startThrows) throw new Error('Permission denied')
    activeRecognition = this as MockSpeechRecognition
  }

  stop() {
    this.onend?.()
  }

  emitFinal(transcript: string) {
    this.onresult?.({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript } }] })
  }

  emitInterim(transcript: string) {
    this.onresult?.({ resultIndex: 0, results: [{ isFinal: false, 0: { transcript } }] })
  }

  emitError(error: string, message?: string) {
    this.onerror?.({ error, message })
  }

  end() {
    this.onend?.()
  }
}

beforeEach(() => {
  pushedToasts.length = 0
  mockPush.mockReset()
  useToastStoreMock.setState({ toasts: [] })
  activeRecognition = null
  startThrows = false
  getUserMediaThrows = false
  mockGetUserMedia.mockClear()
  mockTrackStop.mockClear()
  Object.defineProperty(navigator, 'mediaDevices', {
    value: { getUserMedia: mockGetUserMedia },
    configurable: true,
  })
  Object.defineProperty(window, 'SpeechRecognition', {
    value: MockSpeechRecognition,
    configurable: true,
    writable: true,
  })
})

describe('VoiceMicButton — disabled state', () => {
  it('renders with MicOff icon when voice is disabled', () => {
    render(<VoiceMicButton voiceEnabled={false} onTranscript={() => {}} />)
    expect(screen.getByLabelText('Voice input disabled')).toBeTruthy()
  })

  it('button is disabled when voiceEnabled is false', () => {
    render(<VoiceMicButton voiceEnabled={false} onTranscript={() => {}} />)
    const btn = screen.getByLabelText('Voice input disabled') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
  })

  it('shows the disabled tooltip', () => {
    render(<VoiceMicButton voiceEnabled={false} onTranscript={() => {}} />)
    const btn = screen.getByLabelText('Voice input disabled')
    expect(btn.getAttribute('title')).toBe('Voice mode is disabled. Enable it in settings to use voice input.')
  })

  it('shows unavailable reason when speech recognition is unsupported', () => {
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)
    const btn = screen.getByLabelText('Voice input unavailable') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.getAttribute('title')).toContain('Speech recognition is unavailable')
  })

  it('shows an explicit unavailable reason when provided', () => {
    render(
      <VoiceMicButton
        voiceEnabled={true}
        unavailableReason="Speech recognition is disabled by policy."
        onTranscript={() => {}}
      />
    )
    const btn = screen.getByLabelText('Voice input unavailable') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.getAttribute('title')).toBe('Speech recognition is disabled by policy.')
  })
})

describe('VoiceMicButton — idle/listening state', () => {
  it('renders Mic icon when idle and enabled', () => {
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)
    expect(screen.getByLabelText('Start voice input')).toBeTruthy()
  })

  it('button is disabled when disabled prop is true', () => {
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} disabled={true} />)
    const btn = screen.getByLabelText('Start voice input') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
  })

  it('transitions to listening state on click', async () => {
    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    await user.click(screen.getByLabelText('Start voice input'))

    await waitFor(() => expect(screen.getByLabelText('Stop voice input')).toBeTruthy())
    expect(screen.getByLabelText('Stop voice input').getAttribute('data-recording')).toBe('true')
  })

  it('returns to idle when stopped', async () => {
    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    await user.click(screen.getByLabelText('Start voice input'))
    await waitFor(() => screen.getByLabelText('Stop voice input'))
    await user.click(screen.getByLabelText('Stop voice input'))

    await waitFor(() => expect(screen.getByLabelText('Start voice input')).toBeTruthy())
  })
})

describe('VoiceMicButton — transcript insertion', () => {
  it('calls onTranscript with final speech recognition text', async () => {
    const user = userEvent.setup()
    let captured = ''
    render(<VoiceMicButton voiceEnabled={true} onTranscript={(text) => { captured = text }} />)

    await user.click(screen.getByLabelText('Start voice input'))
    activeRecognition?.emitFinal(' hello world ')
    activeRecognition?.end()

    await waitFor(() => expect(captured).toBe('hello world'))
    await waitFor(() => expect(screen.getByLabelText('Start voice input')).toBeTruthy())
  })

  it('emits the latest interim transcript when recognition ends without a final result', async () => {
    const user = userEvent.setup()
    let captured = ''
    render(<VoiceMicButton voiceEnabled={true} onTranscript={(text) => { captured = text }} />)

    await user.click(screen.getByLabelText('Start voice input'))
    activeRecognition?.emitInterim(' partial speech ')
    activeRecognition?.end()

    await waitFor(() => expect(captured).toBe('partial speech'))
    await waitFor(() => expect(screen.getByLabelText('Start voice input')).toBeTruthy())
  })

  it('does not call onTranscript for empty final text', async () => {
    const user = userEvent.setup()
    let called = false
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => { called = true }} />)

    await user.click(screen.getByLabelText('Start voice input'))
    activeRecognition?.emitFinal('   ')
    activeRecognition?.end()

    await waitFor(() => screen.getByLabelText('Start voice input'))
    expect(called).toBe(false)
  })
})

describe('VoiceMicButton — error handling', () => {
  it('shows toast on speech recognition error and returns to idle', async () => {
    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    await user.click(screen.getByLabelText('Start voice input'))
    activeRecognition?.emitError('not-allowed')
    activeRecognition?.end()

    await waitFor(() => screen.getByLabelText('Start voice input'))
    expect(mockPush).toHaveBeenCalled()
    const call = mockPush.mock.calls[0][0] as Toast
    expect(call.tone).toBe('error')
    expect(call.description).toContain('permission was denied')
  })

  it('checks microphone permission before starting speech recognition', async () => {
    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    await user.click(screen.getByLabelText('Start voice input'))

    await waitFor(() => expect(mockGetUserMedia).toHaveBeenCalledWith({ audio: true }))
    await waitFor(() => expect(screen.getByLabelText('Stop voice input')).toBeTruthy())
    expect(mockTrackStop).not.toHaveBeenCalled()
    activeRecognition?.onaudiostart?.()
    expect(mockTrackStop).toHaveBeenCalled()
  })

  it('still starts speech recognition when microphone preflight fails', async () => {
    getUserMediaThrows = true
    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    await user.click(screen.getByLabelText('Start voice input'))

    await waitFor(() => expect(mockGetUserMedia).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByLabelText('Stop voice input')).toBeTruthy())
    expect(activeRecognition).not.toBeNull()
    expect(mockPush).not.toHaveBeenCalled()
  })

  it('shows toast when speech recognition cannot start', async () => {
    startThrows = true
    const user = userEvent.setup()
    render(<VoiceMicButton voiceEnabled={true} onTranscript={() => {}} />)

    await user.click(screen.getByLabelText('Start voice input'))

    await waitFor(() => expect(mockPush).toHaveBeenCalled())
    const call = mockPush.mock.calls[0][0] as Toast
    expect(call.title).toBe('Voice input error')
    expect(call.description).toBe('Permission denied')
    expect(screen.getByLabelText('Start voice input')).toBeTruthy()
  })
})
