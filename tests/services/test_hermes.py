"""Tests for the Hermes sidecar proposal adapter."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services import vault_gatekeeper
from app.services.hermes import (
    HermesConnectionError,
    HermesProposalRequest,
    HermesQueryRequest,
    HermesSchemaError,
    HermesSkillDraftRequest,
    HermesTimeoutError,
    HermesUnavailableError,
    HttpHermesClient,
    normalize_hermes_query_response,
    normalize_hermes_response,
    normalize_hermes_skill_draft_response,
    query_recall,
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
        self.seen_query_request: HermesQueryRequest | None = None

    async def health(self) -> None:
        self.health_checked = True

    async def propose_write_intents(
        self, request: HermesProposalRequest
    ) -> dict[str, Any]:
        self.seen_request = request
        return self.payload

    async def query_recall(self, request: HermesQueryRequest) -> dict[str, Any]:
        self.seen_query_request = request
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


@pytest.mark.asyncio
async def test_query_recall_validates_and_clamps_request() -> None:
    client = StubHermesClient(
        {
            "answer": "Use the vault gatekeeper for durable writes.",
            "items": [
                {
                    "path": "20-topics/vault-gatekeeper.md",
                    "title": "Vault Gatekeeper",
                    "excerpt": "The gatekeeper is the only write path.",
                    "score": 0.91,
                    "tags": ["vault", "safety"],
                }
            ],
            "warnings": ["partial recall"],
            "model_info": {"model": "hermes-local"},
        }
    )

    result = await query_recall(
        HermesQueryRequest(
            query="How should agents write vault notes?",
            context="x" * 20,
            max_results=99,
        ),
        client=client,
        max_context_chars=5,
    )

    assert client.health_checked is True
    assert client.seen_query_request is not None
    assert client.seen_query_request.context == "xxxxx"
    assert client.seen_query_request.max_results == 20
    assert result.answer == "Use the vault gatekeeper for durable writes."
    assert result.warnings == ["partial recall"]
    assert result.model_info == {"model": "hermes-local"}
    assert len(result.items) == 1
    item = result.items[0]
    assert item.path == "20-topics/vault-gatekeeper.md"
    assert item.title == "Vault Gatekeeper"
    assert item.excerpt == "The gatekeeper is the only write path."
    assert item.score == 0.91
    assert item.tags == ["vault", "safety"]


def test_normalize_query_response_rejects_non_list_items() -> None:
    with pytest.raises(HermesSchemaError, match="items must be a list"):
        normalize_hermes_query_response({"answer": "Bad", "items": "not-a-list"})


def test_normalize_query_response_rejects_forbidden_write_fields() -> None:
    with pytest.raises(HermesSchemaError, match="forbidden field"):
        normalize_hermes_query_response(
            {
                "answer": "Bad",
                "items": [
                    {
                        "title": "Bad",
                        "excerpt": "Should not carry write controls.",
                        "vault_write_params": {"folder": "20-topics"},
                    }
                ],
            }
        )


def test_normalize_query_response_clamps_non_finite_scores() -> None:
    result = normalize_hermes_query_response(
        {
            "answer": "Scores should remain JSON-safe.",
            "items": [
                {"title": "NaN", "excerpt": "Bad score.", "score": math.nan},
                {"title": "Infinity", "excerpt": "Bad score.", "score": math.inf},
                {
                    "title": "Negative Infinity",
                    "excerpt": "Bad score.",
                    "score": -math.inf,
                },
            ],
        }
    )

    assert [item.score for item in result.items] == [0.0, 0.0, 0.0]


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


def test_normalize_skill_draft_response_partitions_valid_invalid_and_conflicts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import agent_fs

    monkeypatch.setattr(agent_fs.settings, "SKILLS_DIR", str(tmp_path))
    agent_fs.write_skill(
        "existing-skill",
        "---\nname: existing-skill\ndescription: Existing\n---\nBody\n",
        create=True,
    )

    result = normalize_hermes_skill_draft_response(
        {
            "summary": "done",
            "skill_drafts": [
                {
                    "name": "new-skill",
                    "description": "Draft helper",
                    "body": "Use this when drafting.",
                    "rationale": "Useful.",
                },
                {
                    "name": "existing-skill",
                    "description": "Existing helper",
                    "body": "Should conflict.",
                },
                {"name": "-bad", "description": "Bad", "body": "Bad"},
            ],
            "warnings": ["top warning"],
            "model_info": {"model": "hermes-test"},
        }
    )

    assert result.summary == "done"
    assert [draft.name for draft in result.valid_drafts] == ["new-skill"]
    assert [draft.name for draft in result.conflicts] == ["existing-skill"]
    assert result.invalid_drafts[0].invalid_reason
    assert "top warning" in result.warnings
    assert result.model_info == {"model": "hermes-test"}


def test_normalize_skill_draft_response_rejects_forbidden_fields() -> None:
    with pytest.raises(HermesSchemaError, match="forbidden field"):
        normalize_hermes_skill_draft_response(
            {
                "skill_drafts": [
                    {
                        "name": "bad",
                        "description": "Bad",
                        "body": "Bad",
                        "frontmatter": "---",
                    }
                ]
            }
        )


def test_normalize_skill_draft_response_truncates_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import agent_fs

    monkeypatch.setattr(agent_fs.settings, "SKILLS_DIR", str(tmp_path))

    result = normalize_hermes_skill_draft_response(
        {
            "skill_drafts": [
                {
                    "name": "long-skill",
                    "description": "Long helper",
                    "body": "x" * 12,
                }
            ]
        },
        max_body_chars_per_draft=5,
    )

    draft = result.valid_drafts[0]
    assert draft.body == "x" * 5
    assert draft.body_truncated is True
    assert any("truncated" in warning for warning in draft.warnings)


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
        if request.url.path == "/v1/query":
            return httpx.Response(
                200,
                json={"answer": "ok", "items": [], "warnings": []},
            )
        if request.url.path == "/v1/skill-drafts":
            return httpx.Response(
                200,
                json={"summary": "skills", "skill_drafts": [], "warnings": []},
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
    query_payload = await client.query_recall(
        HermesQueryRequest(query="Question", context="", max_results=1)
    )
    skill_payload = await client.draft_skills(
        HermesSkillDraftRequest(task="Draft", context="", max_drafts=1)
    )

    assert payload["summary"] == "ok"
    assert query_payload["answer"] == "ok"
    assert skill_payload["summary"] == "skills"
    assert [request.url.path for request in requests] == [
        "/v1/health",
        "/v1/write-intents",
        "/v1/query",
        "/v1/skill-drafts",
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
