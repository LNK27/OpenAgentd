"""Tests for the vault_search built-in tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.tools.builtin.vault_search import vault_search
from app.services import vault_gatekeeper
from app.services.vault_gatekeeper import VAULT_FOLDERS
from app.services.vault_search import clear_vault_search_cache


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
    clear_vault_search_cache()
    return target


@pytest.mark.asyncio
async def test_vault_search_formats_results_with_snippet(_vault_dir: Path) -> None:
    (_vault_dir / "20-topics" / "memory.md").write_text(
        "---\ntitle: Memory Note\ntype: topic\ntags: [memory]\n---\n"
        "# Memory Note\n\nPersistent memory body.\n",
        encoding="utf-8",
    )

    result = await vault_search.arun(query="memory", limit=5)

    assert "Path: 20-topics/memory" in result
    assert "Title: Memory Note" in result
    assert "Tags: memory" in result
    assert "Snippet: Memory Note Persistent memory body." in result


@pytest.mark.asyncio
async def test_vault_search_empty_vault_message() -> None:
    result = await vault_search.arun(query="anything")

    assert result == "No notes found matching your query."


@pytest.mark.asyncio
async def test_vault_search_rejects_invalid_folder() -> None:
    result = await vault_search.arun(query="", folder="unknown")

    assert "Vault folder must be one of" in result
