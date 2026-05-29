---
title: Voice input
description: Client-side speech recognition and transcript insertion contract.
status: stable
updated: 2026-05-28
---

# Voice input

Voice input uses the speech-recognition capability provided by the current
browser or app WebView. OpenAgentd no longer records microphone audio for backend
transcription, does not expose `/api/speech/*`, and does not bundle
`faster-whisper` in the server or sidecar.

## User flow

1. The chat input shows a mic button when the runtime supports speech recognition.
2. Click the mic to start listening.
3. Grant microphone / speech-recognition permission when the OS or browser asks.
4. Click again, or wait for the recognizer to end.
5. Final transcript text is inserted into the composer for review before sending.

If speech recognition is unavailable, the mic button is disabled with an
explanatory tooltip. There is no Settings → Voice page and no backend toggle.

## Runtime support

- Desktop/mobile Tauri and browsers use the Web Speech-compatible recognition
  object exposed by the WebView (`SpeechRecognition` or `webkitSpeechRecognition`).
- Platform privacy and cloud/local processing semantics are controlled by the
  operating system or browser speech service, not by OpenAgentd.
- iOS mobile builds declare microphone and speech-recognition usage descriptions
  in `mobile/src-tauri/Info.ios.plist`.

## Frontend contract

- `web/src/lib/speech-recognition.ts` owns capability detection and recognition
  session lifecycle.
- `VoiceMicButton` never uploads audio. It receives final transcript text from
  the client recognizer and calls `onTranscript(text)`.
- `InputBar` appends transcript text to the current draft, preserving the normal
  send/edit flow.
