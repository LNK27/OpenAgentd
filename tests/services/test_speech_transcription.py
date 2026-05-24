from __future__ import annotations

import builtins
import importlib
import sys
from types import ModuleType

import pytest


def test_speech_transcription_service_does_not_import_faster_whisper_on_import() -> (
    None
):
    """Backend startup must not depend on optional native speech packages."""
    sys.modules.pop("faster_whisper", None)

    import app.services.speech_transcription as speech_transcription

    importlib.reload(speech_transcription)

    assert "faster_whisper" not in sys.modules


@pytest.mark.asyncio
async def test_transcribe_local_wraps_missing_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native import failures become a typed availability error."""
    import app.services.speech_transcription as speech_transcription

    speech_transcription._whisper_cache.clear()
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals_: dict | None = None,
        locals_: dict | None = None,
        fromlist: tuple | list = (),
        level: int = 0,
    ) -> ModuleType:
        if name == "faster_whisper":
            raise ImportError("DLL load failed")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(speech_transcription.SpeechUnavailableError):
        await speech_transcription.transcribe_local(b"audio", "base", "auto")
