"""Tests for the vault_write built-in tool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace.status import StatusCode

from app.agent.tools.builtin.vault_write import VALID_VAULT_FOLDERS, vault_write
from app.services.vault_gatekeeper import (
    VaultDuplicateError,
    VaultIndexUpdateError,
    VaultPathError,
    VaultWriteResult,
)


@dataclass
class MockState:
    metadata: dict[str, Any]


@pytest.fixture(autouse=True)
def _vault_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from app.core.config import settings

    target = tmp_path / "ObsidianVault"
    for folder in VALID_VAULT_FOLDERS:
        folder_path = target / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        (folder_path / "_index.md").write_text(
            f"---\nid: {folder}-index\ntitle: {folder}\ntype: index\n---\n\n## Notes\n",
            encoding="utf-8",
        )
    monkeypatch.setattr(settings, "OPENAGENTD_OBSIDIAN_VAULT_DIR", str(target))
    return target


def test_vault_write_schema_hides_internal_fields() -> None:
    properties = vault_write.definition["function"]["parameters"]["properties"]

    assert "writer" not in properties
    assert "overwrite" not in properties
    assert "last_summarized_at" not in properties


@pytest.mark.asyncio
async def test_vault_write_rejects_invalid_folder() -> None:
    result = await vault_write.arun(
        folder="invalid-folder",
        slug="note-a",
        title="Note A",
        note_type="topic",
        body="Hello",
    )

    assert "Invalid folder: 'invalid-folder'" in result


@pytest.mark.asyncio
async def test_vault_write_success_uses_injected_agent_name(
    _vault_dir: Path,
) -> None:
    result = await vault_write.arun(
        folder="20-topics",
        slug="agent-memory",
        title="Agent Memory",
        note_type="topic",
        body="Persistent memory.",
        _injected={"_state": MockState(metadata={"agent_name": "researcher"})},
    )

    assert "Vault note written to 20-topics/agent-memory.md" == result
    note = (_vault_dir / "20-topics" / "agent-memory.md").read_text(encoding="utf-8")
    assert "writer: agent:researcher" in note
    assert "last_summarized_at: null" in note


@pytest.mark.asyncio
async def test_vault_write_records_success_observability(_vault_dir: Path) -> None:
    tracer, exporter = _tracer_with_exporter()

    with tracer.start_as_current_span("execute_tool vault_write"):
        result = await vault_write.arun(
            folder="20-topics",
            slug="agent-memory",
            title="Agent Memory",
            note_type="topic",
            body="Persistent memory.",
            tags=["memory", "agent"],
        )

    assert result == "Vault note written to 20-topics/agent-memory.md"
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.UNSET
    assert span.attributes["openagentd.second_brain.tool"] == "vault_write"
    assert span.attributes["openagentd.second_brain.outcome"] == "written"
    assert span.attributes["vault.folder"] == "20-topics"
    assert span.attributes["vault.path"] == "20-topics/agent-memory.md"
    assert span.attributes["vault.body_length"] == len("Persistent memory.")
    assert span.attributes["vault.tags_count"] == 2


@pytest.mark.asyncio
async def test_vault_write_falls_back_to_unknown_writer(_vault_dir: Path) -> None:
    result = await vault_write.arun(
        folder="20-topics",
        slug="unknown-writer",
        title="Unknown Writer",
        note_type="topic",
        body="Fallback writer.",
        _injected={"_state": MockState(metadata={})},
    )

    assert "Vault note written to 20-topics/unknown-writer.md" == result
    note = (_vault_dir / "20-topics" / "unknown-writer.md").read_text(encoding="utf-8")
    assert "writer: agent:unknown" in note


@pytest.mark.asyncio
async def test_vault_write_duplicate_path_message() -> None:
    mock_gatekeeper = AsyncMock()
    mock_gatekeeper.write_note.side_effect = VaultDuplicateError(
        "Vault note already exists: 20-topics/existing.md"
    )

    tracer, exporter = _tracer_with_exporter()

    with (
        patch(
            "app.agent.tools.builtin.vault_write.get_vault_gatekeeper",
            return_value=mock_gatekeeper,
        ),
        tracer.start_as_current_span("execute_tool vault_write"),
    ):
        result = await vault_write.arun(
            folder="20-topics",
            slug="existing",
            title="Existing",
            note_type="topic",
            body="Duplicate.",
        )

    assert result == "Note already exists at vault/20-topics/existing.md"
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["openagentd.second_brain.outcome"] == "duplicate"
    assert span.attributes["vault.path"] == "20-topics/existing.md"


@pytest.mark.asyncio
async def test_vault_write_invalid_slug_message() -> None:
    mock_gatekeeper = AsyncMock()
    mock_gatekeeper.write_note.side_effect = VaultPathError(
        "Vault slug uses a reserved Windows filename: 'CON'"
    )

    with patch(
        "app.agent.tools.builtin.vault_write.get_vault_gatekeeper",
        return_value=mock_gatekeeper,
    ):
        result = await vault_write.arun(
            folder="20-topics",
            slug="CON",
            title="Reserved",
            note_type="topic",
            body="Reserved slug.",
        )

    assert result == "Invalid slug: 'CON' is reserved on Windows"


@pytest.mark.asyncio
async def test_vault_write_index_failure_messages() -> None:
    mock_gatekeeper = AsyncMock()
    mock_gatekeeper.write_note.side_effect = VaultIndexUpdateError(
        path="20-topics/index-failure.md",
        rollback_succeeded=True,
        message="index write failed",
    )

    with patch(
        "app.agent.tools.builtin.vault_write.get_vault_gatekeeper",
        return_value=mock_gatekeeper,
    ):
        result = await vault_write.arun(
            folder="20-topics",
            slug="index-failure",
            title="Index Failure",
            note_type="topic",
            body="Needs retry.",
        )

    assert (
        result == "Note created but index update failed; note was rolled back. Retry."
    )


@pytest.mark.asyncio
async def test_vault_write_index_failure_with_failed_rollback_message() -> None:
    mock_gatekeeper = AsyncMock()
    mock_gatekeeper.write_note.side_effect = VaultIndexUpdateError(
        path="20-topics/manual-fix.md",
        rollback_succeeded=False,
        message="index write failed",
    )

    with patch(
        "app.agent.tools.builtin.vault_write.get_vault_gatekeeper",
        return_value=mock_gatekeeper,
    ):
        result = await vault_write.arun(
            folder="20-topics",
            slug="manual-fix",
            title="Manual Fix",
            note_type="topic",
            body="Needs manual repair.",
        )

    assert (
        result
        == "CRITICAL: Note written but index inconsistent. Manual fix needed at 20-topics/manual-fix.md."
    )


@pytest.mark.asyncio
async def test_vault_write_passes_note_id_without_using_it_for_routing() -> None:
    mock_gatekeeper = AsyncMock()
    mock_gatekeeper.write_note.return_value = VaultWriteResult(
        path="20-topics/agent-memory.md",
        note_id="external-id",
        created=True,
        content="---\n---\n",
    )

    with patch(
        "app.agent.tools.builtin.vault_write.get_vault_gatekeeper",
        return_value=mock_gatekeeper,
    ):
        result = await vault_write.arun(
            folder="20-topics",
            slug="agent-memory",
            title="Agent Memory",
            note_type="topic",
            body="Persistent memory.",
            note_id="external-id",
            _injected={"_state": MockState(metadata={"agent_name": "researcher"})},
        )

    assert result == "Vault note written to 20-topics/agent-memory.md"
    call = mock_gatekeeper.write_note.await_args
    assert call is not None
    assert call.args[0].slug == "agent-memory"
    assert call.args[0].note_id == "external-id"


def _tracer_with_exporter():
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter
