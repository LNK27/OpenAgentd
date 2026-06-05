"""Tests for the vault_read built-in tool."""

from __future__ import annotations

from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace.status import StatusCode

from app.agent.tools.builtin.vault_read import vault_read
from app.services import vault_gatekeeper
from app.services.vault_gatekeeper import VAULT_FOLDERS, vault_note_sha256


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


@pytest.mark.asyncio
async def test_vault_read_returns_raw_note(_vault_dir: Path) -> None:
    raw = "---\ntitle: Raw Note\n---\nBody.\n"
    (_vault_dir / "20-topics" / "raw-note.md").write_text(raw, encoding="utf-8")

    result = await vault_read.arun(folder="20-topics", slug="raw-note")

    assert result == raw


@pytest.mark.asyncio
async def test_vault_read_can_include_update_token(_vault_dir: Path) -> None:
    raw = "---\ntitle: Token Note\n---\nBody.\n"
    (_vault_dir / "20-topics" / "token-note.md").write_text(raw, encoding="utf-8")

    result = await vault_read.arun(
        folder="20-topics",
        slug="token-note",
        include_update_token=True,
    )

    assert result == f"{raw}\n[vault_update_token: sha256:{vault_note_sha256(raw)}]"


@pytest.mark.asyncio
async def test_vault_read_update_token_uses_full_raw_note_when_body_only(
    _vault_dir: Path,
) -> None:
    raw = "---\ntitle: Body Only\n---\nVisible body.\n"
    (_vault_dir / "20-topics" / "body-token.md").write_text(raw, encoding="utf-8")

    result = await vault_read.arun(
        folder="20-topics",
        slug="body-token",
        include_frontmatter=False,
        include_update_token=True,
    )

    assert (
        result
        == f"Visible body.\n\n[vault_update_token: sha256:{vault_note_sha256(raw)}]"
    )


@pytest.mark.asyncio
async def test_vault_read_records_read_observability(_vault_dir: Path) -> None:
    raw = "---\ntitle: Raw Note\n---\nBody.\n"
    (_vault_dir / "20-topics" / "raw-note.md").write_text(raw, encoding="utf-8")
    tracer, exporter = _tracer_with_exporter()

    with tracer.start_as_current_span("execute_tool vault_read"):
        result = await vault_read.arun(folder="20-topics", slug="raw-note")

    assert result == raw
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.UNSET
    assert span.attributes["openagentd.second_brain.tool"] == "vault_read"
    assert span.attributes["openagentd.second_brain.outcome"] == "read"
    assert span.attributes["vault.path"] == "20-topics/raw-note.md"
    assert span.attributes["vault.result_length"] == len(raw)
    assert span.attributes["vault.truncated"] is False


@pytest.mark.asyncio
async def test_vault_read_can_hide_frontmatter(_vault_dir: Path) -> None:
    (_vault_dir / "20-topics" / "body-only.md").write_text(
        "---\ntitle: Body Only\n---\nVisible body.\n",
        encoding="utf-8",
    )

    result = await vault_read.arun(
        folder="20-topics",
        slug="body-only",
        include_frontmatter=False,
    )

    assert result == "Visible body.\n"


@pytest.mark.asyncio
async def test_vault_read_malformed_frontmatter_falls_back_with_truncation(
    _vault_dir: Path,
) -> None:
    (_vault_dir / "20-topics" / "broken.md").write_text(
        "---\ntitle: [broken\n---\n" + ("x" * 2000),
        encoding="utf-8",
    )

    result = await vault_read.arun(
        folder="20-topics",
        slug="broken",
        include_frontmatter=False,
        max_chars=1000,
    )

    assert result.startswith("[Warning: Note has malformed frontmatter.")
    assert "[truncated at 1000 characters]" in result
    assert len(result) > 1000
    tracer, exporter = _tracer_with_exporter()
    with tracer.start_as_current_span("execute_tool vault_read"):
        await vault_read.arun(
            folder="20-topics",
            slug="broken",
            include_frontmatter=False,
            max_chars=1000,
        )
    span = exporter.get_finished_spans()[0]
    assert span.attributes["openagentd.second_brain.outcome"] == "malformed_frontmatter"
    assert span.attributes["vault.truncated"] is True


@pytest.mark.asyncio
async def test_vault_read_missing_note_message() -> None:
    tracer, exporter = _tracer_with_exporter()

    with tracer.start_as_current_span("execute_tool vault_read"):
        result = await vault_read.arun(folder="20-topics", slug="missing")

    assert result == "Note not found at vault/20-topics/missing.md"
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["openagentd.second_brain.outcome"] == "not_found"


def _tracer_with_exporter():
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter
