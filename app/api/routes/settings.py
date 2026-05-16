"""Generic ``/api/settings`` endpoints.

Exposes the user-editable sandbox deny-list and the provider catalog.

Application updates are deliberately not served here. Desktop bundle users
trigger updates from the native menu bar (``tauri-plugin-updater``); CLI
users run ``openagentd update`` (see ``app/cli/commands/update.py``).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from loguru import logger

from app.agent.sandbox_config import SandboxFileConfig, load_config, save_config
from app.core.config import settings

if TYPE_CHECKING:
    from app.agent.providers.catalog import ProviderEntry
from app.api.schemas.settings import (
    ProviderInfo,
    ProviderSaveRequest,
    ProviderSaveResponse,
    ProviderTestRequest,
    ProviderTestResponse,
    ProvidersListBody,
    SandboxSettingsBody,
    SeedInstallRequest,
    SeedInstallResponse,
)

router = APIRouter()


@router.get("/sandbox")
async def get_sandbox_settings() -> SandboxSettingsBody:
    """Return the current sandbox deny-list.

    On first run this seeds ``sandbox.yaml`` with sensible defaults
    (``**/.env``, ``**/.env.*``).
    """
    try:
        cfg = load_config()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SandboxSettingsBody(denied_patterns=list(cfg.denied_patterns))


@router.put("/sandbox")
async def update_sandbox_settings(body: SandboxSettingsBody) -> SandboxSettingsBody:
    """Replace the sandbox deny-list with the supplied glob patterns."""
    cleaned = [p.strip() for p in body.denied_patterns if p.strip()]
    save_config(SandboxFileConfig(denied_patterns=cleaned))
    return SandboxSettingsBody(denied_patterns=cleaned)


# ── Providers (Settings → Providers tab) ────────────────────────────────────


def _env_has_provider_key(env_file: "Path") -> bool:
    """Return True if ``.env`` already contains *any* known API-key env var.

    Used by ``save_provider`` to decide whether this save is the user's
    first credential and the frontend should kick off seed installation
    afterward. OAuth tokens (which live in CACHE_DIR, not .env) and the
    Ollama local default don't count — the seed installer needs a
    chat-capable provider:model string, which OAuth providers without a
    saved model don't yet have.
    """
    from app.agent.providers.catalog import PROVIDER_KEY_VAR

    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        return False
    keys = {key for key in PROVIDER_KEY_VAR.values() if key}
    for line in text.splitlines():
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() in keys and value.strip():
            return True
    return False


def _provider_is_configured(entry: "ProviderEntry") -> bool:
    """Return True if the user's .env has credentials for this provider.

    OAuth providers (copilot, codex) check for the presence of the OAuth
    token file under OPENAGENTD_CACHE_DIR — that's where the auth flow
    persists tokens. Local providers (ollama) are always considered
    configured because they need no credentials.
    """
    kind = entry.get("kind")
    if kind == "local":
        return True
    if kind == "oauth":
        cache_dir = Path(settings.OPENAGENTD_CACHE_DIR or "")
        token_files = {
            "codex": cache_dir / "codex_oauth.json",
            "copilot": cache_dir / "copilot_oauth.json",
        }
        token_file = token_files.get(entry["id"])
        return bool(token_file and token_file.is_file())
    if kind == "cloud_creds":
        # Vertex AI: need project + location *and* gcloud ADC. We can't
        # check gcloud from here without shelling out, so the UI's
        # "Test connection" button is the source of truth.
        names = entry.get("env_vars") or []
        return all(os.environ.get(name) for name in names)
    # api_key
    env_var = entry.get("env_var") or ""
    if not env_var:
        return False
    # Check both os.environ (mutated by recent saves) and settings
    # (loaded once at startup) so freshly-saved keys show as configured
    # immediately.
    return bool(os.environ.get(env_var))


@router.get("/providers")
async def list_providers() -> ProvidersListBody:
    """Return the provider catalog enriched with per-provider configuration state."""
    from app.agent.providers.catalog import all_providers

    out: list[ProviderInfo] = []
    for entry in all_providers():
        out.append(
            ProviderInfo(
                id=entry["id"],
                label=entry["label"],
                description=entry.get("description", ""),
                kind=entry["kind"],
                env_var=entry.get("env_var", ""),
                env_vars=list(entry.get("env_vars", [])),
                default_models=list(entry.get("default_models", [])),
                oauth_command=entry.get("oauth_command", ""),
                docs_url=entry.get("docs_url", ""),
                is_configured=_provider_is_configured(entry),
            )
        )
    has_any = any(p.is_configured for p in out)
    return ProvidersListBody(providers=out, has_any_configured=has_any)


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: str, body: ProviderTestRequest
) -> ProviderTestResponse:
    """Run a one-token completion to verify the supplied credentials."""
    from app.agent.providers.catalog import find
    from app.agent.providers.factory import build_provider

    entry = find(provider_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")

    # Temporarily inject the candidate key into os.environ so build_provider
    # picks it up without persisting it. The restoration step rolls back
    # mutations on every exit path.
    overrides: dict[str, str | None] = {}
    if body.api_key and entry.get("env_var"):
        env_var = entry["env_var"]
        overrides[env_var] = os.environ.get(env_var)
        os.environ[env_var] = body.api_key
    for name, value in body.extra.items():
        overrides[name] = os.environ.get(name)
        os.environ[name] = value

    started = time.perf_counter()
    try:
        provider = build_provider(f"{provider_id}:{body.model}")
        from app.agent.schemas.chat import HumanMessage

        await provider.chat(
            messages=[HumanMessage(content="ping")],
            max_tokens=1,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return ProviderTestResponse(ok=True, latency_ms=latency_ms)
    except Exception as exc:
        logger.warning("provider_test_failed provider={} error={}", provider_id, exc)
        return ProviderTestResponse(ok=False, error=str(exc))
    finally:
        # Roll back env mutations. ``None`` means the var didn't exist
        # before, so we delete it; otherwise restore the previous value.
        for name, prev in overrides.items():
            if prev is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = prev


@router.put("/providers/{provider_id}")
async def save_provider(
    provider_id: str, body: ProviderSaveRequest
) -> ProviderSaveResponse:
    """Persist provider credentials to ``$OPENAGENTD_CONFIG_DIR/.env``.

    Side effects:

    - Updates ``os.environ`` so the next ``build_provider`` call sees the
      new value without restarting the server.
    - On first-ever provider save, returns ``is_first_provider=True`` so
      the frontend knows to trigger seed installation afterward.
    """
    from app.agent.providers.catalog import find
    from app.cli.seed import write_env_credentials

    entry = find(provider_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")

    creds: dict[str, str] = {}
    if entry.get("kind") == "api_key" and entry.get("env_var"):
        creds[entry["env_var"]] = body.api_key
    elif entry.get("kind") == "cloud_creds":
        for name in entry.get("env_vars") or []:
            if name in body.extra:
                creds[name] = body.extra[name]
    # OAuth/local providers don't write env vars from this endpoint — OAuth
    # uses the auth route, local needs no credentials.

    if not creds:
        # Nothing to write, but report success so the UI can proceed to
        # seed materialisation.
        return ProviderSaveResponse(saved=False)

    # "First provider" = no .env yet (or .env exists but contains no
    # API keys). OAuth-only and local-only states don't count: the seed
    # installer needs a chat-capable model in OPENAGENTD_MODEL or in a
    # provider env var, which a bare Copilot OAuth token doesn't satisfy.
    env_file = Path(settings.OPENAGENTD_CONFIG_DIR) / ".env"
    is_first = not env_file.exists() or not _env_has_provider_key(env_file)

    write_env_credentials(env_file, creds)

    # Mirror writes into os.environ so build_provider sees them now.
    # ``settings`` is a frozen Pydantic instance — it doesn't refresh,
    # but the providers read from os.environ via require_api_key.
    for key, val in creds.items():
        if val:
            os.environ[key] = val
        else:
            os.environ.pop(key, None)

    logger.info(
        "provider_credentials_saved provider={} env_vars={}",
        provider_id,
        list(creds.keys()),
    )

    return ProviderSaveResponse(
        saved=True,
        is_first_provider=is_first,
    )


@router.post("/seed")
async def install_seed_defaults(body: SeedInstallRequest) -> SeedInstallResponse:
    """Install bundled first-run agents/skills into the user's config dir."""
    from app.cli.seed import SeedDownloadError, install_seed

    try:
        result = install_seed(
            Path(settings.OPENAGENTD_CONFIG_DIR),
            provider_model=body.provider_model.strip(),
        )
    except SeedDownloadError as exc:
        logger.warning("seed_install_failed error={}", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SeedInstallResponse(
        agents_written=result.agents_written,
        skills_written=result.skills_written,
        configs_written=result.configs_written,
        source=result.source,
    )
