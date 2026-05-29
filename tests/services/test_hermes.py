"""Tests for the Hermes sidecar proposal adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services import vault_gatekeeper
from app.services.hermes import (
    HermesConnectionError,
    HermesProposalRequest,
    HermesSchemaError,
    HermesTimeoutError,
    HermesUnavailableError,
    HttpHermesClient,
    normalize_hermes_response,
    propose_write_intents,
)
from app.services.vault_gatekeeper import VAULT_FOLDERS


@pytest.fixture(autouse=True)
def _vault_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from app.core.config import settings

    target = tmp_path / "ObsidianVault"
    for folder in VAULT_FOLDERS:
        folder_path = target / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        (folder_path / "_index.md").write_text("## Notes\n", encoding="utf-8")
    monkeypatch.setattr(settings, "OPENAGENTD_OBSIDIAN_VAULT_DIR", str(target))
    monkeypatch.setattr(vault_gatekeeper, "_default_gatekeeper", None)
    return target


class StubHermesClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.health_checked = False
        self.seen_request: HermesProposalRequest | None = None

    async def health(self) -> None:
        self.health_checked = True

    async def propose_write_intents(
        self, request: HermesProposalRequest
    ) -> dict[str, Any]:
        self.seen_request = request
        return self.payload


@pytest.mark.asyncio
async def test_propose_write_intents_validates_and_clamps_request(
    _vault_dir: Path,
) -> None:
    client = StubHermesClient(
        {
            "summary": "Drafted one note.",
            "write_intents": [
                {
                    "folder": "20-topics",
                    "slug": "agent-memory",
                    "title": "Agent Memory",
                    "note_type": "topic",
                    "body": "Body",
                    "tags": ["memory"],
                    "source_refs": ["[[10-sources/source]]"],
                    "relations": ["[[20-topics/ai]]"],
                    "note_id": "hermes-1",
                }
            ],
            "warnings": ["low confidence"],
            "model_info": {"model": "hermes-local"},
        }
    )

    result = await propose_write_intents(
        HermesProposalRequest(
            task="Make memory note",
            context="x" * 20,
            target_folder="20-topics",
            max_intents=99,
        ),
        client=client,
        max_context_chars=5,
        max_body_chars_per_intent=4000,
    )

    assert client.health_checked is True
    assert client.seen_request is not None
    assert client.seen_request.context == "xxxxx"
    assert client.seen_request.max_intents == 20
    assert result.summary == "Drafted one note."
    assert result.warnings == ["low confidence"]
    assert len(result.valid_intents) == 1
    intent = result.valid_intents[0]
    assert intent.folder == "20-topics"
    assert intent.slug == "agent-memory"
    assert intent.status == "draft"
    assert intent.body_truncated is False
    assert result.conflicts == []
    assert result.invalid_intents == []


def test_normalize_marks_existing_path_as_conflict(_vault_dir: Path) -> None:
    (_vault_dir / "20-topics" / "agent-memory.md").write_text(
        "---\ntitle: Existing\n---\n\nBody\n",
        encoding="utf-8",
    )

    result = normalize_hermes_response(
        {
            "summary": "Drafted one note.",
            "write_intents": [
                {
                    "folder": "20-topics",
                    "slug": "agent-memory",
                    "title": "Agent Memory",
                    "note_type": "topic",
                    "body": "New body",
                }
            ],
        }
    )

    assert result.valid_intents == []
    assert len(result.conflicts) == 1
    assert result.conflicts[0].exists_conflict is True
    assert "vault_write will reject" in result.conflicts[0].warning


def test_normalize_rejects_forbidden_internal_fields() -> None:
    with pytest.raises(HermesSchemaError, match="forbidden field"):
        normalize_hermes_response(
            {
                "summary": "Bad",
                "write_intents": [
                    {
                        "folder": "20-topics",
                        "slug": "bad",
                        "title": "Bad",
                        "note_type": "topic",
                        "body": "Body",
                        "overwrite": True,
                    }
                ],
            }
        )


def test_normalize_forces_status_to_draft_and_truncates_body() -> None:
    result = normalize_hermes_response(
        {
            "summary": "Drafted",
            "write_intents": [
                {
                    "folder": "20-topics",
                    "slug": "status-test",
                    "title": "Status Test",
                    "note_type": "topic",
                    "body": "abcdef",
                    "status": "published",
                }
            ],
        },
        max_body_chars_per_intent=3,
    )

    intent = result.valid_intents[0]
    assert intent.status == "draft"
    assert intent.body == "abc"
    assert intent.body_truncated is True
    assert "status 'published' was overridden to 'draft'" in intent.warnings


def test_normalize_reports_invalid_intents_without_raising() -> None:
    result = normalize_hermes_response(
        {
            "summary": "Drafted",
            "write_intents": [
                {
                    "folder": "unknown",
                    "slug": "bad",
                    "title": "Bad",
                    "note_type": "topic",
                    "body": "Body",
                }
            ],
        }
    )

    assert result.valid_intents == []
    assert len(result.invalid_intents) == 1
    assert "Vault folder must be one of" in result.invalid_intents[0].invalid_reason


def test_normalize_does_not_swallow_unexpected_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(rel_path: str) -> Path:
        raise RuntimeError(f"unexpected validator failure: {rel_path}")

    monkeypatch.setattr("app.services.hermes.validate_vault_note_path", boom)

    with pytest.raises(RuntimeError, match="unexpected validator failure"):
        normalize_hermes_response(
            {
                "summary": "Drafted",
                "write_intents": [
                    {
                        "folder": "20-topics",
                        "slug": "runtime-bug",
                        "title": "Runtime Bug",
                        "note_type": "topic",
                        "body": "Body",
                    }
                ],
            }
        )


@pytest.mark.asyncio
async def test_http_client_sends_health_and_token_header() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/v1/write-intents":
            return httpx.Response(
                200,
                json={"summary": "ok", "write_intents": [], "warnings": []},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = HttpHermesClient(
        base_url="http://127.0.0.1:9010",
        token="secret-token",
        timeout_seconds=2.0,
        transport=transport,
    )

    await client.health()
    payload = await client.propose_write_intents(
        HermesProposalRequest(task="Task", context="", max_intents=1)
    )

    assert payload["summary"] == "ok"
    assert [request.url.path for request in requests] == [
        "/v1/health",
        "/v1/write-intents",
    ]
    assert all(
        request.headers.get("X-Hermes-Token") == "secret-token" for request in requests
    )


def test_http_client_rejects_non_loopback_base_url() -> None:
    with pytest.raises(HermesUnavailableError, match="loopback"):
        HttpHermesClient(base_url="https://example.com")


@pytest.mark.asyncio
async def test_http_client_maps_timeout_and_connection_errors() -> None:
    timeout_client = HttpHermesClient(
        base_url="http://127.0.0.1:9010",
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(
                httpx.TimeoutException("slow", request=request)
            )
        ),
    )
    with pytest.raises(HermesTimeoutError):
        await timeout_client.health()

    connection_client = HttpHermesClient(
        base_url="http://127.0.0.1:9010",
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(
                httpx.ConnectError("refused", request=request)
            )
        ),
    )
    with pytest.raises(HermesConnectionError):
        await connection_client.health()
