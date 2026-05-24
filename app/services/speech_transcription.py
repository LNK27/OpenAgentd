"""Local speech transcription service.

Isolates the optional ``faster_whisper`` runtime behind a typed
``SpeechUnavailableError`` so that the FastAPI app can start even on
machines where the bundled native dependencies (e.g. ``onnxruntime``)
cannot load — a common situation on Windows hosts that are missing the
Microsoft Visual C++ runtime or that quarantine bundled ``.pyd`` files.
"""

from __future__ import annotations

import asyncio
import io
import threading
from typing import Any


class SpeechUnavailableError(RuntimeError):
    """Raised when the optional local speech runtime cannot be loaded."""


# Loading model weights is expensive (~seconds). Cache the instance
# process-wide so repeated calls reuse the same loaded model.
# Key: (model_name, device, compute_type).
_whisper_cache: dict[tuple[str, str, str], Any] = {}
_whisper_lock = threading.Lock()  # guards first-load initialisation per key

# Cache the probe result so repeated availability checks (every
# ``GET /api/speech/config`` call) don't keep importing native code.
_availability_cache: tuple[bool, str | None] | None = None
_availability_lock = threading.Lock()


def probe_local_runtime() -> tuple[bool, str | None]:
    """Return ``(available, reason)`` for the bundled local speech runtime.

    The check is performed at most once per process. ``available`` is
    ``True`` when ``faster_whisper`` (and its native dependencies) can be
    imported, ``False`` otherwise. ``reason`` carries the underlying
    error message when unavailable so the UI can surface it.
    """
    global _availability_cache
    if _availability_cache is not None:
        return _availability_cache

    with _availability_lock:
        if _availability_cache is not None:
            return _availability_cache

        try:
            import faster_whisper  # noqa: F401  - import side effects only
        except (ImportError, OSError, RuntimeError) as exc:
            _availability_cache = (False, str(exc))
        else:
            _availability_cache = (True, None)
        return _availability_cache


def reset_availability_cache() -> None:
    """Test helper: clear the cached probe result."""
    global _availability_cache
    _availability_cache = None


async def transcribe_local(audio_bytes: bytes, model: str, language: str) -> str:
    """Transcribe using faster-whisper when the optional runtime is available."""
    cache_key = (model, "cpu", "int8")

    def _run() -> str:
        wmodel = _whisper_cache.get(cache_key)
        if wmodel is None:
            with _whisper_lock:
                # Re-check inside the lock — another thread may have loaded it.
                wmodel = _whisper_cache.get(cache_key)
                if wmodel is None:
                    try:
                        from faster_whisper import WhisperModel

                        wmodel = WhisperModel(model, device="cpu", compute_type="int8")
                    except (ImportError, OSError, RuntimeError) as exc:
                        raise SpeechUnavailableError(str(exc)) from exc
                    _whisper_cache[cache_key] = wmodel

        whisper_language = None if language == "auto" else language
        segments, _ = wmodel.transcribe(
            io.BytesIO(audio_bytes),
            language=whisper_language,
            beam_size=5,
        )
        return "".join(seg.text for seg in segments).strip()

    return await asyncio.to_thread(_run)
