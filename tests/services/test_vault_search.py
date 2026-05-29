"""Tests for Obsidian vault search/read service."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services import vault_gatekeeper
from app.services.vault_gatekeeper import VAULT_FOLDERS
from app.services.vault_search import (
    _VAULT_CACHE,
    clear_vault_search_cache,
    read_note,
    search_notes,
)


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


def _note(
    title: str, body: str, *, tags: object = None, note_type: str = "note"
) -> str:
    tags_block = "[]"
    if isinstance(tags, list):
        tags_block = "[" + ", ".join(tags) + "]"
    elif isinstance(tags, str):
        tags_block = tags
    return f"---\ntitle: {title}\ntype: {note_type}\ntags: {tags_block}\n---\n{body}"


@pytest.mark.asyncio
async def test_search_matches_vietnamese_without_diacritics(_vault_dir: Path) -> None:
    (_vault_dir / "20-topics" / "doc-tai-lieu.md").write_text(
        _note("Đọc tài liệu", "Ghi chú về tổng hợp tri thức.\n"),
        encoding="utf-8",
    )

    results = await search_notes("doc tai lieu", limit=5)

    assert results
    assert results[0][0].path == "20-topics/doc-tai-lieu.md"


@pytest.mark.asyncio
async def test_exact_match_bonus_prefers_diacritic_match(_vault_dir: Path) -> None:
    (_vault_dir / "20-topics" / "accent.md").write_text(
        _note("Đọc", "Body.\n"),
        encoding="utf-8",
    )
    (_vault_dir / "20-topics" / "plain.md").write_text(
        _note("Doc", "Body.\n"),
        encoding="utf-8",
    )

    results = await search_notes("đọc", limit=2)

    assert [note.slug for note, _, _ in results] == ["accent", "plain"]
    assert results[0][1] > results[1][1]


@pytest.mark.asyncio
async def test_search_filters_folder_tags_and_string_tags(_vault_dir: Path) -> None:
    (_vault_dir / "30-projects" / "project-a.md").write_text(
        _note("Project A", "Body.\n", tags=["work/project-a"]),
        encoding="utf-8",
    )
    (_vault_dir / "20-topics" / "work-topic.md").write_text(
        _note("Work Topic", "Body.\n", tags="work"),
        encoding="utf-8",
    )

    results = await search_notes("", folder="30-projects", tags=["#work"], limit=5)

    assert [note.path for note, _, _ in results] == ["30-projects/project-a.md"]


@pytest.mark.asyncio
async def test_empty_query_sorts_deterministically_and_applies_limit(
    _vault_dir: Path,
) -> None:
    (_vault_dir / "20-topics" / "b-note.md").write_text(
        _note("B", "Body.\n"),
        encoding="utf-8",
    )
    (_vault_dir / "10-sources" / "a-note.md").write_text(
        _note("A", "Body.\n"),
        encoding="utf-8",
    )

    results = await search_notes(None, limit=1)

    assert len(results) == 1
    assert results[0][0].path == "10-sources/a-note.md"
    assert results[0][1] == 0.0


@pytest.mark.asyncio
async def test_cache_updates_and_prunes_deleted_files(_vault_dir: Path) -> None:
    note = _vault_dir / "20-topics" / "cached.md"
    note.write_text(_note("Old Title", "Old body.\n"), encoding="utf-8")

    first = await search_notes("old", limit=5)
    assert first[0][0].title == "Old Title"
    assert _VAULT_CACHE

    note.write_text(_note("New Title", "New body.\n"), encoding="utf-8")
    os.utime(note, None)
    second = await search_notes("new", limit=5)
    assert second[0][0].title == "New Title"

    note.unlink()
    third = await search_notes("", limit=5)
    assert all(result[0].slug != "cached" for result in third)
    assert not _VAULT_CACHE


@pytest.mark.asyncio
async def test_malformed_frontmatter_is_skipped_and_not_cached(
    _vault_dir: Path,
) -> None:
    note = _vault_dir / "20-topics" / "broken.md"
    note.write_text("---\ntitle: [broken\n---\nBody\n", encoding="utf-8")

    assert await search_notes("broken", limit=5) == []
    assert _VAULT_CACHE == {}

    note.write_text(_note("Recovered", "Recovered body.\n"), encoding="utf-8")
    results = await search_notes("recovered", limit=5)

    assert results[0][0].title == "Recovered"


@pytest.mark.asyncio
async def test_read_note_reads_directly_and_validates_path(_vault_dir: Path) -> None:
    note = _vault_dir / "20-topics" / "direct.md"
    note.write_text("first\n", encoding="utf-8")

    assert await read_note("20-topics", "direct") == "first\n"

    note.write_text("second\n", encoding="utf-8")
    assert await read_note("20-topics", "direct") == "second\n"

    with pytest.raises(ValueError):
        await read_note("20-topics", "../direct")
