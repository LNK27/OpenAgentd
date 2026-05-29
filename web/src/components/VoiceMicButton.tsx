/**
 * VoiceMicButton — microphone button for voice input.
 *
 * States:
 * - disabled     : voice not configured; button visible but disabled with tooltip
 * - idle         : click to request mic permission and start recording
 * - recording    : click to stop recording and start transcription
 * - transcribing : upload in progress; button disabled/loading
 *
 * On success the transcript is delivered via `onTranscript`. Errors show as
 * toasts (useToastStore) and leave any existing input text unchanged.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, Mic, MicOff, AudioWaveform } from 'lucide-react'
import { postTranscribe } from '@/api/client'
import { getPlatform } from '@/hooks/use-platform'
import { useToastStore } from '@/stores/useToastStore'

export type VoiceState = 'idle' | 'recording' | 'transcribing'

interface VoiceMicButtonProps {
  /** Whether voice input is enabled (from /api/speech/config). */
  voiceEnabled: boolean
  /** Called with the transcript text on success (only when text is non-empty). */
  onTranscript: (text: string) => void
  /** Whether the rest of the input bar is disabled. */
  disabled?: boolean
  /**
   * When set, the bundled speech runtime can't load on this host (common
   * on some Windows machines where ``onnxruntime`` DLLs fail to initialise).
   * Voice input is forced off and the tooltip surfaces the underlying
   * reason so users can fix it (see Settings → Voice for guidance).
   */
  unavailableReason?: string | null
}

const DISABLED_TOOLTIP =
  'Voice mode is disabled. Enable it in settings to use voice input.'

const UNAVAILABLE_TOOLTIP =
  'Voice runtime unavailable on this machine. See Settings → Voice for help.'

const RECORDING_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/mpeg',
] as const

function getSupportedRecordingMimeType(): string | undefined {
  if (typeof MediaRecorder.isTypeSupported !== 'function') return undefined
  return RECORDING_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type))
}

function recordingFilename(mimeType: string): string {
  const normalized = mimeType.toLowerCase()
  if (normalized.includes('mp4')) return 'recording.m4a'
  if (normalized.includes('mpeg')) return 'recording.mp3'
  return 'recording.webm'
}

function mobileMicrophoneMessage(): string {
  const platform = getPlatform()
  if (platform.isTauri && (platform.os === 'ios' || platform.os === 'android')) {
    return 'Microphone access is blocked for OpenAgentd. Enable microphone permission in system settings, then reopen the app.'
  }
  return 'Microphone access denied.'
}

async function handleDesktopMicrophoneDenied(): Promise<void> {
  const { ask } = await import('@tauri-apps/plugin-dialog')
  const shouldOpen = await ask(
    'Microphone access is blocked for OpenAgentd. Enable OpenAgentd in macOS System Settings → Privacy & Security → Microphone, then restart the app.',
    {
      title: 'Microphone Access Required',
      kind: 'warning',
      okLabel: 'Open System Settings',
      cancelLabel: 'Not Now',
    }
  )
  if (shouldOpen) {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('open_macos_microphone_settings')
  }
}

function isDesktopMicrophoneDenied(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'NotAllowedError' && getPlatform().isMacOverlay
}

export function VoiceMicButton({
  voiceEnabled,
  onTranscript,
  disabled = false,
  unavailableReason = null,
}: VoiceMicButtonProps) {
  // Treat an unavailable runtime as "not enabled" for all interaction logic;
  // only the tooltip changes so the user knows *why*.
  const effectiveEnabled = voiceEnabled && !unavailableReason
  const [voiceState, setVoiceState] = useState<VoiceState>('idle')
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const mountedRef = useRef(true)
  const pushToast = useToastStore((s) => s.push)

  // Track mount state so async callbacks don't update state after unmount.
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      // Stop any in-progress recording on unmount to release the mic.
      if (mediaRecorderRef.current?.state === 'recording') {
        mediaRecorderRef.current.stop()
      }
      mediaRecorderRef.current = null
    }
  }, [])

  const startRecording = useCallback(async () => {
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        pushToast({
          tone: 'error',
          title: 'Microphone unavailable',
          description: 'This browser or WebView does not expose microphone recording.',
        })
        return
      }
      if (typeof MediaRecorder === 'undefined') {
        pushToast({
          tone: 'error',
          title: 'Voice input unsupported',
          description: 'This browser or WebView does not support audio recording for transcription.',
        })
        return
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mimeType = getSupportedRecordingMimeType()
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
      chunksRef.current = []

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      // onstop is synchronous — kick off the async transcription from it
      // rather than assigning an async function directly to the handler.
      recorder.onstop = () => {
        // Release mic tracks immediately when recording stops.
        stream.getTracks().forEach((t) => t.stop())

        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || 'audio/webm',
        })
        chunksRef.current = []

        if (!mountedRef.current) return

        setVoiceState('transcribing')

        postTranscribe(blob, recordingFilename(blob.type))
          .then((result) => {
            if (!mountedRef.current) return
            if (result.text) onTranscript(result.text)
          })
          .catch((err: unknown) => {
            if (!mountedRef.current) return
            const msg = err instanceof Error ? err.message : 'Transcription failed.'
            pushToast({ tone: 'error', title: 'Voice input error', description: msg })
          })
          .finally(() => {
            if (mountedRef.current) setVoiceState('idle')
          })
      }

      recorder.start()
      mediaRecorderRef.current = recorder
      setVoiceState('recording')
    } catch (err) {
      // Permission denied or device unavailable — preserve existing input.
      if (!mountedRef.current) return
      if (isDesktopMicrophoneDenied(err)) {
        void handleDesktopMicrophoneDenied().catch(() => {
          pushToast({
            tone: 'error',
            title: 'Microphone error',
            description: 'Open macOS System Settings → Privacy & Security → Microphone, enable OpenAgentd, then restart the app.',
          })
        })
      } else {
        const msg = err instanceof Error ? err.message : mobileMicrophoneMessage()
        pushToast({ tone: 'error', title: 'Microphone error', description: msg })
      }
      setVoiceState('idle')
    }
  }, [onTranscript, pushToast])

  const stopRecording = useCallback(() => {
    mediaRecorderRef.current?.stop()
    mediaRecorderRef.current = null
  }, [])

  const handleClick = useCallback(() => {
    if (voiceState === 'idle') {
      void startRecording()
    } else if (voiceState === 'recording') {
      stopRecording()
    }
    // transcribing: button is disabled — click unreachable
  }, [voiceState, startRecording, stopRecording])

  // ── Render ────────────────────────────────────────────────────────────────

  const isEffectivelyDisabled = !effectiveEnabled || disabled || voiceState === 'transcribing'

  let icon: React.ReactNode
  let label: string
  let title: string

  if (!effectiveEnabled) {
    icon = <MicOff size={14} />
    if (unavailableReason) {
      label = 'Voice runtime unavailable'
      title = `${UNAVAILABLE_TOOLTIP}\n\n${unavailableReason}`
    } else {
      label = 'Voice input disabled'
      title = DISABLED_TOOLTIP
    }
  } else if (voiceState === 'transcribing') {
    icon = <Loader2 size={14} className="animate-spin" />
    label = 'Transcribing…'
    title = 'Transcribing audio…'
  } else if (voiceState === 'recording') {
    icon = <AudioWaveform size={14} />
    label = 'Stop recording'
    title = 'Click to stop recording'
  } else {
    icon = <Mic size={14} />
    label = 'Start voice input'
    title = 'Click to start recording'
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={isEffectivelyDisabled}
      aria-label={label}
      title={title}
      data-recording={voiceState === 'recording' ? 'true' : undefined}
      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md border transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        voiceState === 'recording'
          ? 'border-(--color-error) bg-(--color-error)/15 text-(--color-error) hover:bg-(--color-error)/25'
          : 'border-(--color-border) bg-(--color-surface) text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)'
      }`}
    >
      {icon}
    </button>
  )
}
