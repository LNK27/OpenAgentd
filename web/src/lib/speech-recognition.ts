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

export interface SpeechRecognitionLike {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
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

export function startClientSpeechRecognition(options: ClientSpeechOptions): ClientSpeechSession {
  const Recognition = getSpeechRecognitionConstructor()
  if (!Recognition) {
    throw new Error('Speech recognition is not supported in this browser or WebView.')
  }

  const recognition = new Recognition()
  recognition.continuous = false
  recognition.interimResults = false
  recognition.lang = ''

  recognition.onresult = (event) => {
    let transcript = ''
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i]
      if (result.isFinal) transcript += result[0]?.transcript ?? ''
    }
    const trimmed = transcript.trim()
    if (trimmed) options.onFinal(trimmed)
  }

  recognition.onerror = (event) => {
    options.onError(speechErrorMessage(event))
  }

  recognition.onend = () => {
    options.onEnd()
  }

  recognition.start()

  return {
    stop: () => recognition.stop(),
  }
}
