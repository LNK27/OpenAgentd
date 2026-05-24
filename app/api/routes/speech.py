"""``/api/speech`` endpoints — voice input config and transcription."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from loguru import logger

from app.agent.speech._config import (
    get_voice_config,
    load_raw_voice_section,
    save_speech_config,
)
from app.api.schemas.speech import (
    SpeechAvailability,
    SpeechConfigBody,
    SpeechConfigResponse,
    TranscribeResponse,
)
from app.services.speech_transcription import (
    SpeechUnavailableError,
    probe_local_runtime,
    transcribe_local,
)

router = APIRouter()

# Accepted audio MIME type prefixes.
# Chromium MediaRecorder produces audio/webm; Firefox produces audio/ogg.
_ACCEPTED_AUDIO_PREFIXES = ("audio/",)

# Fallback public model name used in the disabled-voice response.
_DISABLED_MODEL = "local:base"


def _current_availability() -> SpeechAvailability:
    """Run the cached local-runtime probe and shape it for the API response."""
    available, reason = probe_local_runtime()
    return SpeechAvailability(
        local="available" if available else "unavailable",
        reason=None if available else reason,
    )


@router.get("/config")
async def get_speech_config() -> SpeechConfigResponse:
    """Return safe UI config from ``speech.yaml`` — no secrets.

    Always returns the persisted values so Settings → Voice can round-trip
    edits even while voice is disabled.  Falls back to defaults only when the
    file or ``voice`` section is absent.  The ``availability`` block lets the
    UI hide or warn about voice when the bundled local runtime cannot load
    on this machine (typical on some Windows hosts).
    """
    availability = _current_availability()
    raw = load_raw_voice_section()
    if raw is None:
        return SpeechConfigResponse(
            enabled=False,
            model=_DISABLED_MODEL,
            language="auto",
            max_file_mb=25,
            availability=availability,
        )
    return SpeechConfigResponse(
        enabled=bool(raw.get("enabled", False)),
        model=str(raw.get("model", _DISABLED_MODEL)),
        language=str(raw.get("language", "auto")),
        max_file_mb=int(raw.get("max_file_mb", 25)) or 25,
        availability=availability,
    )


@router.put("/config")
async def update_speech_config(body: SpeechConfigBody) -> SpeechConfigResponse:
    """Persist the voice config to ``speech.yaml`` and return the saved state."""
    try:
        save_speech_config(
            enabled=body.enabled,
            model=body.model,
            language=body.language,
            max_file_mb=body.max_file_mb,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "speech_config_updated enabled={} model={} language={} max_file_mb={}",
        body.enabled,
        body.model,
        body.language,
        body.max_file_mb,
    )
    return SpeechConfigResponse(
        enabled=body.enabled,
        model=body.model,
        language=body.language,
        max_file_mb=body.max_file_mb,
        availability=_current_availability(),
    )


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)) -> TranscribeResponse:
    """Transcribe one uploaded audio recording.

    Accepts ``multipart/form-data`` with a single ``file`` field containing
    browser ``MediaRecorder`` output (``audio/webm`` Opus in Chromium,
    ``audio/ogg`` in Firefox).

    Returns ``{text: ""}`` for silent recordings so the UI can avoid
    modifying the input.
    """
    cfg = get_voice_config()
    if cfg is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Voice input is disabled. "
                "Enable it in speech.yaml to use voice transcription."
            ),
        )

    # ── Validate MIME type ────────────────────────────────────────────────────
    content_type = (file.content_type or "").lower()
    if not any(content_type.startswith(p) for p in _ACCEPTED_AUDIO_PREFIXES):
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported audio type '{content_type}'. "
                "Upload an audio/webm or audio/ogg file."
            ),
        )

    # ── Read and size-check ───────────────────────────────────────────────────
    max_bytes = cfg.max_file_mb * 1024 * 1024
    audio_bytes = await file.read(max_bytes + 1)
    if len(audio_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Audio file exceeds the {cfg.max_file_mb} MB limit.",
        )

    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    # ── Dispatch to provider ──────────────────────────────────────────────────
    if cfg.provider == "local":
        try:
            text = await transcribe_local(audio_bytes, cfg.model, cfg.language)
        except SpeechUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Local voice transcription is unavailable on this machine. "
                    f"Runtime error: {exc}"
                ),
            ) from exc
    else:
        raise HTTPException(
            status_code=501,
            detail=(
                f"Voice provider '{cfg.provider}' is not supported in V1. "
                "Use 'local:base'."
            ),
        )

    logger.info(
        "speech_transcribed provider={} model={} bytes={} chars={}",
        cfg.provider,
        cfg.model,
        len(audio_bytes),
        len(text),
    )
    return TranscribeResponse(text=text)
