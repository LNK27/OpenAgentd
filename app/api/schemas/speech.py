"""Request and response schemas for ``/api/speech`` endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SpeechAvailability(BaseModel):
    """Probe-result for the optional local speech runtime."""

    model_config = ConfigDict(extra="forbid")

    local: Literal["available", "unavailable", "unknown"]
    reason: str | None = None


class SpeechConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    model: str
    language: str
    max_file_mb: int
    availability: SpeechAvailability


class SpeechConfigBody(BaseModel):
    """Request body for ``PUT /api/speech/config``."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    model: str = Field(min_length=3)  # must contain ":"
    language: str = Field(min_length=1)
    max_file_mb: int = Field(gt=0)


class TranscribeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
