export interface SpeechRecognitionAlternativeLike {
  transcript: string
}

export interface SpeechRecognitionResultLike {
  isFinal: boolean
  0: SpeechRecognitionAlternativeLike
}

export interface SpeechRecognitionResultListLike {
  length: number
  [index: number]: SpeechRecognitionResultLike
}

export interface SpeechRecognitionEventLike {
  resultIndex: number
  results: SpeechRecognitionResultListLike
}

export interface SpeechRecognitionErrorEventLike {
  error?: string
  message?: string
}

interface SpeechRecognitionAudioEventLike {
  type?: string
}

export interface SpeechRecognitionLike {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
  onaudiostart?: ((event: SpeechRecognitionAudioEventLike) => void) | null
  onspeechstart?: ((event: SpeechRecognitionAudioEventLike) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
}

export type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

interface SpeechRecognitionWindow extends Window {
  SpeechRecognition?: SpeechRecognitionConstructor
  webkitSpeechRecognition?: SpeechRecognitionConstructor
}

export interface ClientSpeechSession {
  stop: () => void
}

export interface ClientSpeechOptions {
  onFinal: (text: string) => void
  onError: (message: string) => void
  onEnd: () => void
}

async function requestMicrophonePermission(): Promise<MediaStream | null> {
  if (typeof navigator === 'undefined') return null
  if (!navigator.mediaDevices?.getUserMedia) return null
  return navigator.mediaDevices.getUserMedia({ audio: true })
}

function stopMicrophonePermissionStream(stream: MediaStream | null): void {
  stream?.getTracks().forEach((track) => track.stop())
}

export function getSpeechRecognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === 'undefined') return null
  const speechWindow = window as SpeechRecognitionWindow
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null
}

export function isClientSpeechRecognitionSupported(): boolean {
  return getSpeechRecognitionConstructor() !== null
}

function speechErrorMessage(event: SpeechRecognitionErrorEventLike): string {
  if (event.message) return event.message
  if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
    return 'Microphone or speech recognition permission was denied.'
  }
  if (event.error === 'no-speech') return 'No speech was detected.'
  if (event.error === 'audio-capture') return 'No microphone was found.'
  if (event.error) return `Speech recognition failed: ${event.error}`
  return 'Speech recognition failed.'
}

export async function startClientSpeechRecognition(options: ClientSpeechOptions): Promise<ClientSpeechSession> {
  const Recognition = getSpeechRecognitionConstructor()
  if (!Recognition) {
    throw new Error('Speech recognition is not supported in this browser or WebView.')
  }

  let permissionStream: MediaStream | null = null
  try {
    permissionStream = await requestMicrophonePermission()
  } catch (err) {
    console.warn('speech recognition microphone preflight failed; trying recognizer directly', err)
  }

  const recognition = new Recognition()
  recognition.continuous = false
  recognition.interimResults = true
  recognition.lang = ''
  let latestTranscript = ''
  let emittedFinal = false

  const emitFinal = (text: string): void => {
    const trimmed = text.trim()
    if (!trimmed || emittedFinal) return
    emittedFinal = true
    options.onFinal(trimmed)
  }

  recognition.onresult = (event) => {
    let transcript = ''
    let hasFinal = false
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i]
      transcript += result[0]?.transcript ?? ''
      hasFinal = hasFinal || result.isFinal
    }
    latestTranscript = transcript.trim() || latestTranscript
    if (hasFinal) emitFinal(latestTranscript)
  }

  recognition.onerror = (event) => {
    stopMicrophonePermissionStream(permissionStream)
    permissionStream = null
    options.onError(speechErrorMessage(event))
  }

  recognition.onaudiostart = () => {
    stopMicrophonePermissionStream(permissionStream)
    permissionStream = null
  }

  recognition.onspeechstart = () => {
    stopMicrophonePermissionStream(permissionStream)
    permissionStream = null
  }

  recognition.onend = () => {
    stopMicrophonePermissionStream(permissionStream)
    permissionStream = null
    emitFinal(latestTranscript)
    options.onEnd()
  }

  try {
    recognition.start()
  } catch (err) {
    stopMicrophonePermissionStream(permissionStream)
    throw err
  }

  return {
    stop: () => {
      stopMicrophonePermissionStream(permissionStream)
      permissionStream = null
      recognition.stop()
    },
  }
}
