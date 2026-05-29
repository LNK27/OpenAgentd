"""Tests for human Obsidian vault ingest/reconcile."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.services import vault_gatekeeper
from app.services.vault_gatekeeper import VAULT_FOLDERS
from app.services.vault_ingest import ingest_vault


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
    (target / "MAP_OF_CONTENT.md").write_text("static map\n", encoding="utf-8")
    monkeypatch.setattr(settings, "OPENAGENTD_OBSIDIAN_VAULT_DIR", str(target))
    monkeypatch.setattr(vault_gatekeeper, "_default_gatekeeper", None)
    return target


def _frontmatter(raw: str) -> dict[str, Any]:
    assert raw.startswith("---\n")
    block = raw.split("---", 2)[1]
    data = yaml.safe_load(block)
    assert isinstance(data, dict)
    return data


def _standard_note(slug: str, title: str) -> str:
    return (
        "---\n"
        f"id: {slug}\n"
        f"title: {title}\n"
        "type: note\n"
        "status: draft\n"
        "tags: []\n"
        "created_at: '2026-05-24T00:00:00+00:00'\n"
        "updated_at: '2026-05-24T00:00:00+00:00'\n"
        "source_refs: []\n"
        "relations: []\n"
        "last_summarized_at: null\n"
        "writer: human\n"
        "---\n"
        f"# {title}\n"
    )


@pytest.mark.asyncio
async def test_scan_empty_vault_reports_zero_notes() -> None:
    result = await ingest_vault(apply=False)

    assert result.scanned == 0
    assert result.normalized == 0
    assert result.skipped_ok == 0
    assert result.errors == []


@pytest.mark.asyncio
async def test_standard_note_is_noop_when_index_is_current(_vault_dir: Path) -> None:
    note = _vault_dir / "20-topics" / "complete-note.md"
    content = _standard_note("complete-note", "Complete Note")
    note.write_text(content, encoding="utf-8")
    (_vault_dir / "20-topics" / "_index.md").write_text(
        "## Notes\n- [[complete-note|Complete Note]] - note\n",
        encoding="utf-8",
    )

    result = await ingest_vault(apply=True)

    assert result.scanned == 1
    assert result.skipped_ok == 1
    assert result.normalized == 0
    assert note.read_text(encoding="utf-8") == content


@pytest.mark.asyncio
async def test_note_without_frontmatter_gets_metadata_and_preserves_body(
    _vault_dir: Path,
) -> None:
    raw_body = "# Human Heading\n\nBody stays exactly.\n"
    note = _vault_dir / "00-inbox" / "raw-human-note.md"
    note.write_text(raw_body, encoding="utf-8")

    result = await ingest_vault(apply=True)
    content = note.read_text(encoding="utf-8")
    metadata = _frontmatter(content)

    assert result.scanned == 1
    assert result.normalized == 1
    assert metadata["id"] == "raw-human-note"
    assert metadata["title"] == "Human Heading"
    assert metadata["type"] == "note"
    assert metadata["writer"] == "human"
    assert metadata["last_summarized_at"] is None
    assert content.endswith(raw_body)


@pytest.mark.asyncio
async def test_missing_frontmatter_fields_are_added_without_overwriting_existing(
    _vault_dir: Path,
) -> None:
    note = _vault_dir / "10-sources" / "partial-note.md"
    body = "Body text.\n"
    note.write_text(
        "---\n"
        "title: Existing Title\n"
        "status: active\n"
        "tags:\n"
        "  - kept\n"
        "created_at: '2026-01-01T00:00:00+00:00'\n"
        "updated_at: '2026-01-02T00:00:00+00:00'\n"
        "source_refs: []\n"
        "relations: []\n"
        "last_summarized_at: null\n"
        "custom_field: value\n"
        "---\n"
        f"{body}",
        encoding="utf-8",
    )

    await ingest_vault(apply=True)
    content = note.read_text(encoding="utf-8")
    metadata = _frontmatter(content)

    assert metadata["title"] == "Existing Title"
    assert metadata["status"] == "active"
    assert metadata["custom_field"] == "value"
    assert metadata["id"] == "partial-note"
    assert metadata["type"] == "note"
    assert metadata["writer"] == "human"
    assert content.endswith(body)


@pytest.mark.asyncio
async def test_title_falls_back_to_humanized_slug_when_no_heading(
    _vault_dir: Path,
) -> None:
    note = _vault_dir / "20-topics" / "plain-human-note.md"
    note.write_text("No heading here.\n", encoding="utf-8")

    await ingest_vault(apply=True)

    assert _frontmatter(note.read_text(encoding="utf-8"))["title"] == (
        "Plain Human Note"
    )


@pytest.mark.asyncio
async def test_malformed_frontmatter_is_skipped_and_not_rewritten(
    _vault_dir: Path,
) -> None:
    note = _vault_dir / "20-topics" / "bad-yaml.md"
    bad = "---\ntitle: [broken\n---\nBody\n"
    note.write_text(bad, encoding="utf-8")

    result = await ingest_vault(apply=True)

    assert result.scanned == 1
    assert result.normalized == 0
    assert result.errors
    assert note.read_text(encoding="utf-8") == bad


@pytest.mark.asyncio
async def test_non_utf8_file_is_skipped_with_warning(_vault_dir: Path) -> None:
    (_vault_dir / "20-topics" / "latin1.md").write_bytes(b"\xff\xfe\xfd")

    result = await ingest_vault(apply=True)

    assert result.scanned == 0
    assert result.warnings
    assert "non-UTF-8" in result.warnings[0]


@pytest.mark.asyncio
async def test_subfolder_is_skipped_with_warning(_vault_dir: Path) -> None:
    nested = _vault_dir / "20-topics" / "nested"
    nested.mkdir()
    (nested / "inside.md").write_text("Nested note\n", encoding="utf-8")

    result = await ingest_vault(apply=True)

    assert result.skipped_subfolders == 1
    assert result.warnings
    assert "subfolder not supported" in result.warnings[0]


@pytest.mark.asyncio
async def test_index_missing_link_is_appended_when_apply_true(_vault_dir: Path) -> None:
    (_vault_dir / "30-projects" / "new-project.md").write_text(
        "# New Project\n",
        encoding="utf-8",
    )

    result = await ingest_vault(apply=True)
    index = (_vault_dir / "30-projects" / "_index.md").read_text(encoding="utf-8")

    assert result.indexed == 1
    assert "- [[new-project|New Project]] - note" in index


@pytest.mark.asyncio
async def test_stale_index_link_is_removed_when_apply_true(_vault_dir: Path) -> None:
    (_vault_dir / "40-people" / "_index.md").write_text(
        "## Notes\n- [[missing-person|Missing Person]] - note\n",
        encoding="utf-8",
    )

    result = await ingest_vault(apply=True)
    index = (_vault_dir / "40-people" / "_index.md").read_text(encoding="utf-8")

    assert result.stale_removed == 1
    assert "missing-person" not in index


@pytest.mark.asyncio
async def test_dry_run_does_not_modify_notes_or_index(_vault_dir: Path) -> None:
    note = _vault_dir / "50-decisions" / "dry-run-note.md"
    index = _vault_dir / "50-decisions" / "_index.md"
    note_before = "# Dry Run\n\nBody\n"
    index_before = index.read_text(encoding="utf-8")
    note.write_text(note_before, encoding="utf-8")

    result = await ingest_vault(apply=False)

    assert result.normalized == 1
    assert result.indexed == 1
    assert note.read_text(encoding="utf-8") == note_before
    assert index.read_text(encoding="utf-8") == index_before


@pytest.mark.asyncio
async def test_ingest_uses_singleton_gatekeeper_lock(
    _vault_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import vault_ingest

    class TrackingLock:
        def __init__(self) -> None:
            self.enter_count = 0

        async def __aenter__(self) -> None:
            self.enter_count += 1

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeGatekeeper:
        def __init__(self) -> None:
            self._lock = TrackingLock()

    fake = FakeGatekeeper()
    monkeypatch.setattr(vault_ingest, "get_vault_gatekeeper", lambda: fake)
    (_vault_dir / "90-archive" / "locked-note.md").write_text(
        "# Locked Note\n",
        encoding="utf-8",
    )

    await ingest_vault(apply=True)

    assert fake._lock.enter_count >= 1


@pytest.mark.asyncio
async def test_one_bad_note_does_not_stop_other_notes(_vault_dir: Path) -> None:
    bad = _vault_dir / "20-topics" / "bad.md"
    good = _vault_dir / "20-topics" / "good.md"
    bad.write_text("---\ntitle: [broken\n---\nBad\n", encoding="utf-8")
    good.write_text("# Good Note\n", encoding="utf-8")

    result = await ingest_vault(apply=True)

    assert result.errors
    assert result.normalized == 1
    assert _frontmatter(good.read_text(encoding="utf-8"))["title"] == "Good Note"
