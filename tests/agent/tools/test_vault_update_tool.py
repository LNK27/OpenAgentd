"""Tests for the vault_update built-in tool."""

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

from app.agent.tools.builtin.vault_update import vault_update
from app.services import vault_gatekeeper
from app.services.markdown_text import split_vault_note_frontmatter
from app.services.vault_gatekeeper import (
    VAULT_FOLDERS,
    VaultMalformedNoteError,
    VaultNoteNotFoundError,
    VaultPathError,
    VaultUpdateConflictError,
    VaultUpdateResult,
    VaultWriteError,
    VaultWriteIntent,
    get_vault_gatekeeper,
    vault_note_sha256,
)


@dataclass
class MockState:
    metadata: dict[str, Any]


@pytest.fixture(autouse=True)
def _vault_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from app.core.config import settings

    target = tmp_path / "ObsidianVault"
    for folder in VAULT_FOLDERS:
        folder_path = target / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        (folder_path / "_index.md").write_text(
            f"---\nid: {folder}-index\ntitle: {folder}\ntype: index\n---\n\n## Notes\n",
            encoding="utf-8",
        )
    monkeypatch.setattr(settings, "OPENAGENTD_OBSIDIAN_VAULT_DIR", str(target))
    monkeypatch.setattr(vault_gatekeeper, "_default_gatekeeper", None)
    return target


def test_vault_update_schema_hides_internal_fields() -> None:
    properties = vault_update.definition["function"]["parameters"]["properties"]

    assert "_state" not in properties
    assert "expected_sha256" in properties
    assert "replace_body" in properties
    assert "append_body" in properties


@pytest.mark.asyncio
async def test_vault_update_replaces_body_and_uses_injected_agent_name(
    _vault_dir: Path,
) -> None:
    gatekeeper = get_vault_gatekeeper()
    await gatekeeper.write_note(
        VaultWriteIntent(
            folder="20-topics",
            slug="agent-memory",
            title="Agent Memory",
            note_type="topic",
            body="Original.",
            writer="agent:first",
        )
    )
    path = _vault_dir / "20-topics" / "agent-memory.md"

    result = await vault_update.arun(
        folder="20-topics",
        slug="agent-memory",
        expected_sha256=vault_note_sha256(path.read_text(encoding="utf-8")),
        replace_body="Updated.",
        _injected={"_state": MockState(metadata={"agent_name": "researcher"})},
    )

    assert result == "Vault note updated at 20-topics/agent-memory.md"
    parsed = split_vault_note_frontmatter(path.read_text(encoding="utf-8"))
    assert parsed.body == "\nUpdated.\n"
    assert parsed.metadata["title"] == "Agent Memory"
    assert parsed.metadata["writer"] == "agent:researcher"


@pytest.mark.asyncio
async def test_vault_update_appends_body_and_updates_metadata(_vault_dir: Path) -> None:
    gatekeeper = get_vault_gatekeeper()
    await gatekeeper.write_note(
        VaultWriteIntent(
            folder="30-projects",
            slug="append-target",
            title="Append Target",
            note_type="project",
            body="Original.",
            tags=["old"],
        )
    )
    path = _vault_dir / "30-projects" / "append-target.md"

    result = await vault_update.arun(
        folder="30-projects",
        slug="append-target",
        expected_sha256="sha256:" + vault_note_sha256(path.read_text(encoding="utf-8")),
        append_body="Appended.",
        status="active",
        tags=["new", "new", ""],
        source_refs=["[[10-sources/source-a]]"],
        relations=["[[20-topics/related]]"],
        last_summarized_at="2026-06-02T00:00:00+00:00",
    )

    assert result == "Vault note updated at 30-projects/append-target.md"
    parsed = split_vault_note_frontmatter(path.read_text(encoding="utf-8"))
    assert parsed.body == "\nOriginal.\n\n---\n\nAppended.\n"
    assert parsed.metadata["status"] == "active"
    assert parsed.metadata["tags"] == ["new"]
    assert parsed.metadata["source_refs"] == ["[[10-sources/source-a]]"]
    assert parsed.metadata["relations"] == ["[[20-topics/related]]"]
    assert parsed.metadata["last_summarized_at"] == "2026-06-02T00:00:00+00:00"
    assert parsed.metadata["writer"] == "agent:unknown"


@pytest.mark.asyncio
async def test_vault_update_falls_back_to_unknown_writer(_vault_dir: Path) -> None:
    gatekeeper = get_vault_gatekeeper()
    await gatekeeper.write_note(
        VaultWriteIntent(
            folder="20-topics",
            slug="unknown-writer",
            title="Unknown Writer",
            note_type="topic",
            body="Original.",
        )
    )
    path = _vault_dir / "20-topics" / "unknown-writer.md"

    await vault_update.arun(
        folder="20-topics",
        slug="unknown-writer",
        expected_sha256=vault_note_sha256(path.read_text(encoding="utf-8")),
        append_body="Append.",
        _injected={"_state": MockState(metadata={})},
    )

    parsed = split_vault_note_frontmatter(path.read_text(encoding="utf-8"))
    assert parsed.metadata["writer"] == "agent:unknown"


@pytest.mark.asyncio
async def test_vault_update_error_messages_are_specific() -> None:
    mock_gatekeeper = AsyncMock()
    cases = [
        (
            VaultUpdateConflictError("changed"),
            "Update conflict at vault/20-topics/example.md",
        ),
        (
            VaultNoteNotFoundError("missing"),
            "Note not found at vault/20-topics/example.md",
        ),
        (
            VaultMalformedNoteError("malformed"),
            "Cannot update vault/20-topics/example.md",
        ),
        (VaultPathError("bad path"), "bad path"),
        (
            VaultWriteError("write failed"),
            "Failed to update vault note at vault/20-topics/example.md",
        ),
        (
            ValueError("No vault update changes requested."),
            "Invalid vault update request: No vault update changes requested.",
        ),
    ]

    for exc, expected in cases:
        mock_gatekeeper.update_note.side_effect = exc
        with patch(
            "app.agent.tools.builtin.vault_update.get_vault_gatekeeper",
            return_value=mock_gatekeeper,
        ):
            result = await vault_update.arun(
                folder="20-topics",
                slug="example",
                expected_sha256="sha256:" + ("0" * 64),
                replace_body="Updated.",
            )
        assert expected in result


@pytest.mark.asyncio
async def test_vault_update_records_observability_success() -> None:
    mock_gatekeeper = AsyncMock()
    mock_gatekeeper.update_note.return_value = VaultUpdateResult(
        path="20-topics/example.md",
        note_id="example",
        updated=True,
        content="---\n---\nBody.\n",
        sha256="a" * 64,
    )
    tracer, exporter = _tracer_with_exporter()

    with (
        patch(
            "app.agent.tools.builtin.vault_update.get_vault_gatekeeper",
            return_value=mock_gatekeeper,
        ),
        tracer.start_as_current_span("execute_tool vault_update"),
    ):
        result = await vault_update.arun(
            folder="20-topics",
            slug="example",
            expected_sha256="sha256:" + ("0" * 64),
            replace_body="Updated.",
            tags=["one", "two"],
        )

    assert result == "Vault note updated at 20-topics/example.md"
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.UNSET
    assert span.attributes["openagentd.second_brain.tool"] == "vault_update"
    assert span.attributes["openagentd.second_brain.outcome"] == "updated"
    assert span.attributes["vault.path"] == "20-topics/example.md"
    assert span.attributes["vault.replace_body_length"] == len("Updated.")
    assert span.attributes["vault.metadata_fields_count"] == 1
    assert "vault.expected_sha256" not in span.attributes
    assert "vault.tags" not in span.attributes


@pytest.mark.asyncio
async def test_vault_update_records_observability_error() -> None:
    mock_gatekeeper = AsyncMock()
    mock_gatekeeper.update_note.side_effect = VaultUpdateConflictError("changed")
    tracer, exporter = _tracer_with_exporter()

    with (
        patch(
            "app.agent.tools.builtin.vault_update.get_vault_gatekeeper",
            return_value=mock_gatekeeper,
        ),
        tracer.start_as_current_span("execute_tool vault_update"),
    ):
        await vault_update.arun(
            folder="20-topics",
            slug="example",
            expected_sha256="sha256:" + ("0" * 64),
            append_body="Append.",
        )

    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["openagentd.second_brain.outcome"] == "conflict"


def _tracer_with_exporter():
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter
