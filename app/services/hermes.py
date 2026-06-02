"""Hermes sidecar proposal adapter.

Hermes v1 is a proposal-only boundary. This service accepts structured
write-intents from a sidecar, validates them against the vault contract, and
returns proposals for the agent to review. It does not write to the vault.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.vault_gatekeeper import VaultPathError, validate_vault_note_path

_MAX_INTENTS = 20
_MAX_RESULTS = 20
_DEFAULT_MAX_CONTEXT_CHARS = 8000
_DEFAULT_MAX_BODY_CHARS_PER_INTENT = 4000
_FORBIDDEN_INTENT_FIELDS = {"writer", "overwrite", "last_summarized_at"}
_FORBIDDEN_QUERY_ITEM_FIELDS = {
    "writer",
    "overwrite",
    "last_summarized_at",
    "vault_write_params",
    "write_intents",
    "pending_id",
}
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class HermesError(Exception):
    """Base exception for Hermes connector failures."""


class HermesUnavailableError(HermesError):
    """Raised when Hermes is disabled, misconfigured, or unhealthy."""


class HermesConnectionError(HermesError):
    """Raised when OpenAgentd cannot connect to the Hermes sidecar."""


class HermesTimeoutError(HermesError):
    """Raised when a Hermes sidecar request times out."""


class HermesSchemaError(HermesError):
    """Raised when Hermes returns data outside the v1 proposal contract."""


@dataclass(frozen=True)
class HermesProposalRequest:
    """Request sent to the Hermes sidecar."""

    task: str
    context: str = ""
    target_folder: str | None = None
    max_intents: int = 5


@dataclass(frozen=True)
class HermesQueryRequest:
    """Read-only recall/query request sent to the Hermes sidecar."""

    query: str
    context: str = ""
    max_results: int = 5


@dataclass(frozen=True)
class HermesIntentProposal:
    """Validated proposal for one future vault_write call."""

    folder: str
    slug: str
    title: str
    note_type: str
    body: str
    status: str = "draft"
    tags: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)
    note_id: str | None = None
    body_truncated: bool = False
    exists_conflict: bool = False
    warning: str | None = None
    invalid_reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    def as_vault_write_params(self) -> dict[str, Any]:
        """Return the public vault_write-compatible parameter shape."""
        result: dict[str, Any] = {
            "folder": self.folder,
            "slug": self.slug,
            "title": self.title,
            "note_type": self.note_type,
            "body": self.body,
            "status": self.status,
            "tags": self.tags,
            "source_refs": self.source_refs,
            "relations": self.relations,
        }
        if self.note_id:
            result["note_id"] = self.note_id
        return result


@dataclass(frozen=True)
class HermesProposal:
    """Normalized proposal returned to the agent layer."""

    summary: str = ""
    valid_intents: list[HermesIntentProposal] = field(default_factory=list)
    conflicts: list[HermesIntentProposal] = field(default_factory=list)
    invalid_intents: list[HermesIntentProposal] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model_info: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HermesQueryItem:
    """One read-only recall result returned by Hermes."""

    title: str = ""
    path: str = ""
    excerpt: str = ""
    score: float = 0.0
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HermesQueryResult:
    """Normalized read-only recall result from Hermes."""

    answer: str = ""
    items: list[HermesQueryItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model_info: dict[str, Any] = field(default_factory=dict)


class HermesClient(Protocol):
    """Protocol for swappable Hermes sidecar clients."""

    async def health(self) -> None:
        """Raise if the sidecar is unavailable."""

    async def propose_write_intents(
        self,
        request: HermesProposalRequest,
    ) -> dict[str, Any]:
        """Return the raw Hermes proposal payload."""

    async def query_recall(self, request: HermesQueryRequest) -> dict[str, Any]:
        """Return the raw Hermes read-only query payload."""


class HttpHermesClient:
    """HTTP JSON implementation of the Hermes client protocol."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = _normalize_loopback_url(base_url)
        self.token = token.strip() if token else None
        self.timeout_seconds = float(timeout_seconds)
        self.transport = transport

    async def health(self) -> None:
        """Check sidecar availability."""
        await self._request("GET", "/v1/health")

    async def propose_write_intents(
        self,
        request: HermesProposalRequest,
    ) -> dict[str, Any]:
        """Request write-intent proposals from Hermes."""
        response = await self._request(
            "POST",
            "/v1/write-intents",
            json={
                "task": request.task,
                "context": request.context,
                "target_folder": request.target_folder,
                "max_intents": request.max_intents,
            },
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise HermesSchemaError("Hermes response must be a JSON object.")
        return payload

    async def query_recall(self, request: HermesQueryRequest) -> dict[str, Any]:
        """Request read-only recall/query results from Hermes."""
        response = await self._request(
            "POST",
            "/v1/query",
            json={
                "query": request.query,
                "context": request.context,
                "max_results": request.max_results,
            },
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise HermesSchemaError("Hermes response must be a JSON object.")
        return payload

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        if self.token:
            headers["X-Hermes-Token"] = self.token
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    **kwargs,
                )
                response.raise_for_status()
                return response
        except httpx.TimeoutException as exc:
            raise HermesTimeoutError("Hermes sidecar request timed out.") from exc
        except httpx.ConnectError as exc:
            raise HermesConnectionError("Could not connect to Hermes sidecar.") from exc
        except httpx.HTTPStatusError as exc:
            raise HermesUnavailableError(
                f"Hermes sidecar returned HTTP {exc.response.status_code}."
            ) from exc
        except ValueError as exc:
            raise HermesSchemaError("Hermes sidecar returned invalid JSON.") from exc


async def propose_write_intents(
    request: HermesProposalRequest,
    *,
    client: HermesClient | None = None,
    max_context_chars: int | None = None,
    max_body_chars_per_intent: int | None = None,
) -> HermesProposal:
    """Call Hermes and normalize its write-intent proposal response."""
    hermes_client = client or _client_from_settings()
    prepared = _prepare_request(
        request,
        max_context_chars=max_context_chars,
    )
    await hermes_client.health()
    payload = await hermes_client.propose_write_intents(prepared)
    return normalize_hermes_response(
        payload,
        max_body_chars_per_intent=max_body_chars_per_intent,
    )


async def query_recall(
    request: HermesQueryRequest,
    *,
    client: HermesClient | None = None,
    max_context_chars: int | None = None,
) -> HermesQueryResult:
    """Call Hermes for read-only recall/query results."""
    hermes_client = client or _client_from_settings()
    prepared = _prepare_query_request(
        request,
        max_context_chars=max_context_chars,
    )
    await hermes_client.health()
    payload = await hermes_client.query_recall(prepared)
    return normalize_hermes_query_response(payload)


def normalize_hermes_response(
    payload: dict[str, Any],
    *,
    max_body_chars_per_intent: int | None = None,
) -> HermesProposal:
    """Validate and partition a raw Hermes proposal payload."""
    if not isinstance(payload, dict):
        raise HermesSchemaError("Hermes response must be a JSON object.")
    summary = _optional_string(payload.get("summary"), field_name="summary")
    raw_warnings = payload.get("warnings", [])
    if raw_warnings is None:
        raw_warnings = []
    if not isinstance(raw_warnings, list):
        raise HermesSchemaError("Hermes response warnings must be a list.")
    warnings = [str(item) for item in raw_warnings if str(item).strip()]
    raw_model_info = payload.get("model_info", {})
    model_info = raw_model_info if isinstance(raw_model_info, dict) else {}
    raw_intents = payload.get("write_intents", [])
    if not isinstance(raw_intents, list):
        raise HermesSchemaError("Hermes response write_intents must be a list.")

    valid_intents: list[HermesIntentProposal] = []
    conflicts: list[HermesIntentProposal] = []
    invalid_intents: list[HermesIntentProposal] = []
    body_limit = _positive_int(
        max_body_chars_per_intent,
        fallback=_DEFAULT_MAX_BODY_CHARS_PER_INTENT,
    )

    for raw in raw_intents:
        intent = _normalize_intent(raw, body_limit=body_limit)
        if intent.invalid_reason:
            invalid_intents.append(intent)
        elif intent.exists_conflict:
            conflicts.append(intent)
        else:
            valid_intents.append(intent)
        warnings.extend(intent.warnings)

    return HermesProposal(
        summary=summary,
        valid_intents=valid_intents,
        conflicts=conflicts,
        invalid_intents=invalid_intents,
        warnings=_dedupe(warnings),
        model_info=model_info,
    )


def normalize_hermes_query_response(payload: dict[str, Any]) -> HermesQueryResult:
    """Validate and normalize a raw Hermes read-only query payload."""
    if not isinstance(payload, dict):
        raise HermesSchemaError("Hermes response must be a JSON object.")
    answer = _optional_string(payload.get("answer"), field_name="answer")
    raw_warnings = payload.get("warnings", [])
    if raw_warnings is None:
        raw_warnings = []
    if not isinstance(raw_warnings, list):
        raise HermesSchemaError("Hermes response warnings must be a list.")
    warnings = [str(item) for item in raw_warnings if str(item).strip()]
    raw_model_info = payload.get("model_info", {})
    model_info = raw_model_info if isinstance(raw_model_info, dict) else {}
    raw_items = payload.get("items", [])
    if raw_items is None:
        raw_items = []
    if not isinstance(raw_items, list):
        raise HermesSchemaError("Hermes response items must be a list.")

    items = [_normalize_query_item(raw) for raw in raw_items]
    return HermesQueryResult(
        answer=answer,
        items=items,
        warnings=_dedupe(warnings),
        model_info=model_info,
    )


def _client_from_settings() -> HttpHermesClient:
    if not settings.OPENAGENTD_HERMES_ENABLED:
        raise HermesUnavailableError("Hermes connector is disabled.")
    if not settings.OPENAGENTD_HERMES_BASE_URL.strip():
        raise HermesUnavailableError("OPENAGENTD_HERMES_BASE_URL is not configured.")
    token = (
        settings.OPENAGENTD_HERMES_TOKEN.get_secret_value()
        if settings.OPENAGENTD_HERMES_TOKEN is not None
        else None
    )
    return HttpHermesClient(
        base_url=settings.OPENAGENTD_HERMES_BASE_URL,
        token=token,
        timeout_seconds=settings.OPENAGENTD_HERMES_TIMEOUT_SECONDS,
    )


def _prepare_request(
    request: HermesProposalRequest,
    *,
    max_context_chars: int | None,
) -> HermesProposalRequest:
    return replace(
        request,
        context=request.context[
            : _positive_int(
                max_context_chars,
                fallback=settings.OPENAGENTD_HERMES_MAX_CONTEXT_CHARS,
            )
        ],
        max_intents=_clamp_int(request.max_intents, minimum=1, maximum=_MAX_INTENTS),
    )


def _prepare_query_request(
    request: HermesQueryRequest,
    *,
    max_context_chars: int | None,
) -> HermesQueryRequest:
    return replace(
        request,
        query=request.query.strip(),
        context=request.context[
            : _positive_int(
                max_context_chars,
                fallback=settings.OPENAGENTD_HERMES_MAX_CONTEXT_CHARS,
            )
        ],
        max_results=_clamp_int(request.max_results, minimum=1, maximum=_MAX_RESULTS),
    )


def _normalize_intent(raw: Any, *, body_limit: int) -> HermesIntentProposal:
    if not isinstance(raw, dict):
        return _invalid_stub("Hermes write_intent must be an object.")
    forbidden = sorted(_FORBIDDEN_INTENT_FIELDS.intersection(raw))
    if forbidden:
        raise HermesSchemaError(
            f"Hermes write_intent contains forbidden field: {', '.join(forbidden)}"
        )

    status_warnings: list[str] = []
    raw_status = raw.get("status")
    if raw_status is not None and str(raw_status).strip() != "draft":
        status_warnings.append(f"status '{raw_status}' was overridden to 'draft'")

    try:
        folder = _required_string(raw, "folder")
        slug = _required_string(raw, "slug")
        title = _required_string(raw, "title")
        note_type = _required_string(raw, "note_type")
        body = _required_string(raw, "body")
    except HermesSchemaError as exc:
        return _invalid_stub(str(exc), raw=raw)

    body_truncated = False
    if len(body) > body_limit:
        body = body[:body_limit]
        body_truncated = True

    intent = HermesIntentProposal(
        folder=folder,
        slug=slug,
        title=title,
        note_type=note_type,
        body=body,
        status="draft",
        tags=_string_list(raw.get("tags")),
        source_refs=_string_list(raw.get("source_refs")),
        relations=_string_list(raw.get("relations")),
        note_id=_optional_string(raw.get("note_id"), field_name="note_id") or None,
        body_truncated=body_truncated,
        warnings=status_warnings,
    )

    try:
        path = validate_vault_note_path(f"{folder}/{slug}.md")
    except VaultPathError as exc:
        return replace(intent, invalid_reason=str(exc))
    if path.exists():
        rel_path = f"{folder}/{slug}.md"
        return replace(
            intent,
            exists_conflict=True,
            warning=(
                f"note already exists at vault/{rel_path}; "
                "vault_write will reject without overwrite"
            ),
        )
    return intent


def _normalize_query_item(raw: Any) -> HermesQueryItem:
    if not isinstance(raw, dict):
        raise HermesSchemaError("Hermes query item must be an object.")
    forbidden = sorted(_FORBIDDEN_QUERY_ITEM_FIELDS.intersection(raw))
    if forbidden:
        raise HermesSchemaError(
            f"Hermes query item contains forbidden field: {', '.join(forbidden)}"
        )
    return HermesQueryItem(
        title=_optional_string(raw.get("title"), field_name="title"),
        path=_optional_string(raw.get("path"), field_name="path"),
        excerpt=_optional_string(raw.get("excerpt"), field_name="excerpt"),
        score=_optional_float(raw.get("score")),
        tags=_string_list(raw.get("tags")),
    )


def _invalid_stub(
    reason: str, *, raw: dict[str, Any] | None = None
) -> HermesIntentProposal:
    raw = raw or {}
    return HermesIntentProposal(
        folder=str(raw.get("folder") or ""),
        slug=str(raw.get("slug") or ""),
        title=str(raw.get("title") or ""),
        note_type=str(raw.get("note_type") or ""),
        body=str(raw.get("body") or ""),
        invalid_reason=reason,
    )


def _normalize_loopback_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise HermesUnavailableError("Hermes base URL must use http or https.")
    if parsed.hostname not in _LOOPBACK_HOSTS:
        raise HermesUnavailableError("Hermes base URL must point to loopback/local.")
    return base_url.rstrip("/")


def _required_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HermesSchemaError(f"Hermes write_intent missing required field: {key}")
    return value.strip()


def _optional_string(value: Any, *, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HermesSchemaError(f"Hermes response field must be a string: {field_name}")
    return value.strip()


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = [str(item) for item in value]
    else:
        return []
    return _dedupe([item.strip() for item in values if item.strip()])


def _optional_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else 0.0
    return 0.0


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _positive_int(value: int | None, *, fallback: int) -> int:
    if value is None:
        return fallback
    return max(1, int(value))


def _clamp_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(int(value), maximum))
