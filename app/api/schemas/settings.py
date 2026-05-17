"""Request and response schemas for ``/api/settings`` endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SandboxSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    denied_patterns: list[str] = Field(default_factory=list)


# ── Providers (Settings → Providers tab) ────────────────────────────────────


class ProviderInfo(BaseModel):
    """One catalog row enriched with the user's current configuration state."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str
    kind: str  # "api_key" | "oauth" | "local" | "cloud_creds"
    env_var: str = ""
    env_vars: list[str] = Field(default_factory=list)
    default_models: list[str] = Field(default_factory=list)
    oauth_command: str = ""
    docs_url: str = ""
    # State the UI uses to decide whether to render "Connected" or a CTA.
    is_configured: bool = False


class ProvidersListBody(BaseModel):
    """``GET /api/settings/providers`` response."""

    model_config = ConfigDict(extra="forbid")

    providers: list[ProviderInfo]
    has_any_configured: bool


class ModelEntry(BaseModel):
    """One model entry returned by the provider-models endpoint."""

    model_config = ConfigDict(extra="forbid")

    id: str
    # Whether the model accepts image inputs. Resolved from the provider
    # prefix in ``app.agent.providers.capabilities`` — same source as the
    # attachment-upload gate, so what the UI shows matches what the
    # backend actually enforces.
    vision: bool = False


class ProviderModelsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    models: list[ModelEntry] = Field(default_factory=list)
    # ``provider`` = list returned by the live provider API.
    # ``default`` = curated fallback from the catalog (provider unreachable).
    source: Literal["provider", "default"]


class ProviderTestRequest(BaseModel):
    """``POST /api/settings/providers/{id}/test`` request body."""

    model_config = ConfigDict(extra="forbid")

    # ``api_key`` lets the UI verify a key *before* persisting it. Empty
    # string means "use the already-saved key" — useful for re-testing
    # an existing config.
    api_key: str = ""
    model: str
    # Multi-field providers (vertexai) pass their extras here.
    extra: dict[str, str] = Field(default_factory=dict)


class ProviderModelsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = ""
    extra: dict[str, str] = Field(default_factory=dict)


class ProviderTestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    latency_ms: int | None = None
    error: str | None = None


class ProviderSaveRequest(BaseModel):
    """``PUT /api/settings/providers/{id}`` request body."""

    model_config = ConfigDict(extra="forbid")

    api_key: str = ""
    extra: dict[str, str] = Field(default_factory=dict)


class ProviderSaveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    saved: bool
    # Convenience: whether this save call resulted in the first
    # configured provider (frontend uses this to decide whether to
    # trigger the seed installer afterward).
    is_first_provider: bool = False


class SeedInstallRequest(BaseModel):
    """``POST /api/settings/seed`` request body."""

    model_config = ConfigDict(extra="forbid")

    # ``provider:model`` string that substitutes for ``__PROVIDER_MODEL__``
    # in every seeded agent .md.
    provider_model: str = Field(min_length=1)


class SeedInstallResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents_written: list[str] = Field(default_factory=list)
    skills_written: list[str] = Field(default_factory=list)
    configs_written: list[str] = Field(default_factory=list)
    source: str  # "local", "tag:v0.x.y", or "branch:main"
