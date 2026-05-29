"""Tests for the vault_read built-in tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.tools.builtin.vault_read import vault_read
from app.services import vault_gatekeeper
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


@pytest.mark.asyncio
async def test_vault_read_returns_raw_note(_vault_dir: Path) -> None:
    raw = "---\ntitle: Raw Note\n---\nBody.\n"
    (_vault_dir / "20-topics" / "raw-note.md").write_text(raw, encoding="utf-8")

    result = await vault_read.arun(folder="20-topics", slug="raw-note")

    assert result == raw


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


@pytest.mark.asyncio
async def test_vault_read_missing_note_message() -> None:
    result = await vault_read.arun(folder="20-topics", slug="missing")

    assert result == "Note not found at vault/20-topics/missing.md"
