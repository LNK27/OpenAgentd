"""Tests for the Obsidian vault gatekeeper service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.services.markdown_text import split_vault_note_frontmatter
from app.services.vault_gatekeeper import (
    VAULT_FOLDERS,
    VaultDuplicateError,
    VaultGatekeeper,
    VaultIndexUpdateError,
    VaultMalformedNoteError,
    VaultNoteNotFoundError,
    VaultPathError,
    VaultUpdateConflictError,
    VaultUpdateIntent,
    VaultWriteIntent,
    find_note_by_id,
    render_vault_note,
    validate_vault_note_path,
    vault_note_sha256,
    vault_root,
)


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
    return target


def _frontmatter(raw: str) -> dict[str, Any]:
    assert raw.startswith("---\n")
    block = raw.split("---", 2)[1]
    data = yaml.safe_load(block)
    assert isinstance(data, dict)
    return data


def test_vault_root_creates_configured_dir(_vault_dir: Path) -> None:
    root = vault_root()

    assert root == _vault_dir
    assert root.exists()


def test_validate_vault_note_path_accepts_standard_v7_note(_vault_dir: Path) -> None:
    path = validate_vault_note_path("20-topics/agent-memory.md")

    assert path == _vault_dir / "20-topics" / "agent-memory.md"


@pytest.mark.parametrize(
    "rel_path",
    [
        "../outside.md",
        "20-topics/../outside.md",
        "20-topics/agent-memory.txt",
        "unknown/agent-memory.md",
        "20-topics/nested/agent-memory.md",
        "20-topics/_index.md",
        "/20-topics/agent-memory.md",
        "20-topics/CON.md",
        "20-topics/com1.md",
    ],
)
def test_validate_vault_note_path_rejects_unsafe_paths(rel_path: str) -> None:
    with pytest.raises(VaultPathError):
        validate_vault_note_path(rel_path)


@pytest.mark.asyncio
async def test_write_intent_rejects_reserved_windows_slug() -> None:
    gatekeeper = VaultGatekeeper()

    with pytest.raises(VaultPathError):
        await gatekeeper.write_note(
            VaultWriteIntent(
                folder="00-inbox",
                slug="NUL",
                title="Bad Slug",
                note_type="inbox",
                body="This should not be written.",
            )
        )


def test_render_vault_note_normalizes_v7_frontmatter() -> None:
    content = render_vault_note(
        VaultWriteIntent(
            folder="10-sources",
            slug="browser-research",
            title=" Browser Research ",
            note_type=" source ",
            status=" active ",
            tags=["ai", " ai ", "", "research"],
            source_refs=[" [[00-inbox/raw]] ", ""],
            relations=["[[20-topics/second-brain]]"],
            writer=" codex ",
            body="  Body text  ",
        ),
        now=datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
    )

    metadata = _frontmatter(content)
    assert metadata == {
        "id": "browser-research",
        "title": "Browser Research",
        "type": "source",
        "status": "active",
        "tags": ["ai", "research"],
        "created_at": "2026-05-22T12:00:00+00:00",
        "updated_at": "2026-05-22T12:00:00+00:00",
        "source_refs": ["[[00-inbox/raw]]"],
        "relations": ["[[20-topics/second-brain]]"],
        "last_summarized_at": None,
        "writer": "codex",
    }
    assert content.endswith("Body text\n")


@pytest.mark.asyncio
async def test_write_note_creates_note_and_updates_folder_index(
    _vault_dir: Path,
) -> None:
    gatekeeper = VaultGatekeeper()

    result = await gatekeeper.write_note(
        VaultWriteIntent(
            folder="20-topics",
            slug="agent-memory",
            title="Agent Memory",
            note_type="topic",
            body="Persistent memory notes.",
            tags=["second-brain"],
            writer="codex",
        )
    )

    assert result.path == "20-topics/agent-memory.md"
    assert result.note_id == "agent-memory"
    assert result.created is True
    note = (_vault_dir / result.path).read_text(encoding="utf-8")
    assert _frontmatter(note)["writer"] == "codex"
    index = (_vault_dir / "20-topics" / "_index.md").read_text(encoding="utf-8")
    assert "- [[agent-memory|Agent Memory]] - topic" in index


@pytest.mark.asyncio
async def test_write_note_rejects_existing_path_without_overwrite() -> None:
    gatekeeper = VaultGatekeeper()
    intent = VaultWriteIntent(
        folder="30-projects",
        slug="second-brain",
        title="Second Brain",
        note_type="project",
        body="First version.",
    )
    await gatekeeper.write_note(intent)

    with pytest.raises(VaultDuplicateError):
        await gatekeeper.write_note(intent)


@pytest.mark.asyncio
async def test_update_note_replaces_body_with_matching_hash(_vault_dir: Path) -> None:
    gatekeeper = VaultGatekeeper()
    await gatekeeper.write_note(
        VaultWriteIntent(
            folder="20-topics",
            slug="agent-memory",
            title="Agent Memory",
            note_type="topic",
            body="Original body.",
            tags=["memory"],
            writer="agent:first",
        )
    )
    path = _vault_dir / "20-topics" / "agent-memory.md"
    expected_hash = vault_note_sha256(path.read_text(encoding="utf-8"))

    result = await gatekeeper.update_note(
        VaultUpdateIntent(
            folder="20-topics",
            slug="agent-memory",
            expected_sha256=expected_hash,
            replace_body="Updated body.",
            writer="agent:editor",
        )
    )

    assert result.path == "20-topics/agent-memory.md"
    assert result.updated is True
    raw = path.read_text(encoding="utf-8")
    assert "\n---\n\nUpdated body.\n" in raw
    parsed = split_vault_note_frontmatter(raw)
    assert parsed.body == "\nUpdated body.\n"
    assert parsed.metadata["title"] == "Agent Memory"
    assert parsed.metadata["type"] == "topic"
    assert parsed.metadata["created_at"] != parsed.metadata["updated_at"]
    assert parsed.metadata["writer"] == "agent:editor"


@pytest.mark.asyncio
async def test_update_note_rejects_stale_hash(_vault_dir: Path) -> None:
    gatekeeper = VaultGatekeeper()
    await gatekeeper.write_note(
        VaultWriteIntent(
            folder="20-topics",
            slug="stale",
            title="Stale",
            note_type="topic",
            body="Original.",
        )
    )
    path = _vault_dir / "20-topics" / "stale.md"
    stale_hash = vault_note_sha256(path.read_text(encoding="utf-8"))
    path.write_text(
        path.read_text(encoding="utf-8") + "\nHuman edit.\n",
        encoding="utf-8",
    )

    with pytest.raises(VaultUpdateConflictError):
        await gatekeeper.update_note(
            VaultUpdateIntent(
                folder="20-topics",
                slug="stale",
                expected_sha256=stale_hash,
                replace_body="Agent update.",
            )
        )

    assert "Human edit." in path.read_text(encoding="utf-8")
    assert "Agent update." not in path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_update_note_preserves_custom_frontmatter(_vault_dir: Path) -> None:
    path = _vault_dir / "20-topics" / "custom.md"
    path.write_text(
        "---\n"
        "id: custom\n"
        "title: Custom\n"
        "type: topic\n"
        "status: draft\n"
        "tags:\n"
        "  - old\n"
        "created_at: 2026-06-01T00:00:00+00:00\n"
        "updated_at: 2026-06-01T00:00:00+00:00\n"
        "source_refs: []\n"
        "relations: []\n"
        "last_summarized_at: null\n"
        "writer: human\n"
        "custom_key: custom-value\n"
        "---\n"
        "Body.\n",
        encoding="utf-8",
    )
    gatekeeper = VaultGatekeeper()

    result = await gatekeeper.update_note(
        VaultUpdateIntent(
            folder="20-topics",
            slug="custom",
            expected_sha256=vault_note_sha256(path.read_text(encoding="utf-8")),
            status="active",
            tags=["new", "new", ""],
            source_refs=["[[10-sources/source-a]]"],
            relations=["[[20-topics/related]]"],
            last_summarized_at="2026-06-02T00:00:00+00:00",
            writer="agent:editor",
        )
    )

    assert result.updated is True
    parsed = split_vault_note_frontmatter(path.read_text(encoding="utf-8"))
    assert parsed.metadata["custom_key"] == "custom-value"
    assert parsed.metadata["title"] == "Custom"
    assert parsed.metadata["type"] == "topic"
    assert parsed.metadata["status"] == "active"
    assert parsed.metadata["tags"] == ["new"]
    assert parsed.metadata["source_refs"] == ["[[10-sources/source-a]]"]
    assert parsed.metadata["relations"] == ["[[20-topics/related]]"]
    assert parsed.metadata["last_summarized_at"] == "2026-06-02T00:00:00+00:00"
    assert parsed.metadata["writer"] == "agent:editor"


@pytest.mark.asyncio
async def test_update_note_appends_body_with_separator(_vault_dir: Path) -> None:
    gatekeeper = VaultGatekeeper()
    await gatekeeper.write_note(
        VaultWriteIntent(
            folder="30-projects",
            slug="append-target",
            title="Append Target",
            note_type="project",
            body="Existing body.\n",
        )
    )
    path = _vault_dir / "30-projects" / "append-target.md"

    await gatekeeper.update_note(
        VaultUpdateIntent(
            folder="30-projects",
            slug="append-target",
            expected_sha256=f"sha256:{vault_note_sha256(path.read_text(encoding='utf-8'))}",
            append_body="Appended body.",
        )
    )

    parsed = split_vault_note_frontmatter(path.read_text(encoding="utf-8"))
    assert parsed.body == "\nExisting body.\n\n---\n\nAppended body.\n"


@pytest.mark.asyncio
async def test_update_note_rejects_invalid_requests(_vault_dir: Path) -> None:
    gatekeeper = VaultGatekeeper()
    await gatekeeper.write_note(
        VaultWriteIntent(
            folder="20-topics",
            slug="invalid-update",
            title="Invalid Update",
            note_type="topic",
            body="Body.",
        )
    )
    raw = (_vault_dir / "20-topics" / "invalid-update.md").read_text(encoding="utf-8")
    token = vault_note_sha256(raw)

    with pytest.raises(ValueError, match="expected_sha256"):
        await gatekeeper.update_note(
            VaultUpdateIntent(
                folder="20-topics",
                slug="invalid-update",
                expected_sha256="",
            )
        )
    with pytest.raises(ValueError, match="replace_body and append_body"):
        await gatekeeper.update_note(
            VaultUpdateIntent(
                folder="20-topics",
                slug="invalid-update",
                expected_sha256=token,
                replace_body="A",
                append_body="B",
            )
        )
    with pytest.raises(ValueError, match="No vault update changes"):
        await gatekeeper.update_note(
            VaultUpdateIntent(
                folder="20-topics",
                slug="invalid-update",
                expected_sha256=token,
            )
        )
    with pytest.raises(ValueError, match="body must not be empty"):
        await gatekeeper.update_note(
            VaultUpdateIntent(
                folder="20-topics",
                slug="invalid-update",
                expected_sha256=token,
                replace_body="  ",
            )
        )


@pytest.mark.asyncio
async def test_update_note_rejects_missing_and_malformed_notes(
    _vault_dir: Path,
) -> None:
    gatekeeper = VaultGatekeeper()

    with pytest.raises(VaultNoteNotFoundError):
        await gatekeeper.update_note(
            VaultUpdateIntent(
                folder="20-topics",
                slug="missing",
                expected_sha256="sha256:" + ("0" * 64),
                replace_body="Body.",
            )
        )

    malformed = _vault_dir / "20-topics" / "malformed.md"
    malformed.write_text("---\ntitle: [broken\n---\nBody.\n", encoding="utf-8")
    with pytest.raises(VaultMalformedNoteError):
        await gatekeeper.update_note(
            VaultUpdateIntent(
                folder="20-topics",
                slug="malformed",
                expected_sha256=vault_note_sha256(
                    malformed.read_text(encoding="utf-8")
                ),
                replace_body="Body.",
            )
        )

    no_frontmatter = _vault_dir / "20-topics" / "no-frontmatter.md"
    no_frontmatter.write_text("Body only.\n", encoding="utf-8")
    with pytest.raises(VaultMalformedNoteError):
        await gatekeeper.update_note(
            VaultUpdateIntent(
                folder="20-topics",
                slug="no-frontmatter",
                expected_sha256=vault_note_sha256(
                    no_frontmatter.read_text(encoding="utf-8")
                ),
                replace_body="Body.",
            )
        )


@pytest.mark.asyncio
async def test_update_note_allows_one_concurrent_writer(_vault_dir: Path) -> None:
    gatekeeper = VaultGatekeeper()
    await gatekeeper.write_note(
        VaultWriteIntent(
            folder="20-topics",
            slug="race",
            title="Race",
            note_type="topic",
            body="Original.",
        )
    )
    path = _vault_dir / "20-topics" / "race.md"
    token = vault_note_sha256(path.read_text(encoding="utf-8"))

    results = await asyncio.gather(
        gatekeeper.update_note(
            VaultUpdateIntent(
                folder="20-topics",
                slug="race",
                expected_sha256=token,
                replace_body="First.",
            )
        ),
        gatekeeper.update_note(
            VaultUpdateIntent(
                folder="20-topics",
                slug="race",
                expected_sha256=token,
                replace_body="Second.",
            )
        ),
        return_exceptions=True,
    )

    successes = [item for item in results if not isinstance(item, Exception)]
    conflicts = [item for item in results if isinstance(item, VaultUpdateConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1


@pytest.mark.asyncio
async def test_write_note_allows_same_note_id_across_different_paths(
    _vault_dir: Path,
) -> None:
    gatekeeper = VaultGatekeeper()
    first = await gatekeeper.write_note(
        VaultWriteIntent(
            folder="10-sources",
            slug="source-a",
            note_id="shared-id",
            title="Source A",
            note_type="source",
            body="First note.",
        )
    )

    second = await gatekeeper.write_note(
        VaultWriteIntent(
            folder="20-topics",
            slug="topic-b",
            note_id="shared-id",
            title="Topic B",
            note_type="topic",
            body="Duplicate id allowed across paths.",
        )
    )

    assert first.path == "10-sources/source-a.md"
    assert second.path == "20-topics/topic-b.md"
    assert _frontmatter((_vault_dir / first.path).read_text(encoding="utf-8"))[
        "id"
    ] == ("shared-id")
    assert (
        _frontmatter((_vault_dir / second.path).read_text(encoding="utf-8"))["id"]
        == "shared-id"
    )


@pytest.mark.asyncio
async def test_write_note_allows_overwrite_same_path(_vault_dir: Path) -> None:
    gatekeeper = VaultGatekeeper()
    first = VaultWriteIntent(
        folder="50-decisions",
        slug="adr-002",
        note_id="ADR-002",
        title="ADR 002",
        note_type="decision",
        body="Initial decision.",
    )
    await gatekeeper.write_note(first)

    result = await gatekeeper.write_note(
        VaultWriteIntent(
            folder="50-decisions",
            slug="adr-002",
            note_id="ADR-002",
            title="ADR 002",
            note_type="decision",
            body="Updated decision.",
            overwrite=True,
        )
    )

    assert result.created is False
    assert "Updated decision." in (_vault_dir / result.path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_write_note_serializes_concurrent_writes_to_same_index(
    _vault_dir: Path,
) -> None:
    gatekeeper = VaultGatekeeper()

    await asyncio.gather(
        gatekeeper.write_note(
            VaultWriteIntent(
                folder="00-inbox",
                slug="raw-a",
                title="Raw A",
                note_type="inbox",
                body="First raw note.",
            )
        ),
        gatekeeper.write_note(
            VaultWriteIntent(
                folder="00-inbox",
                slug="raw-b",
                title="Raw B",
                note_type="inbox",
                body="Second raw note.",
            )
        ),
    )

    index = (_vault_dir / "00-inbox" / "_index.md").read_text(encoding="utf-8")
    assert "- [[raw-a|Raw A]] - inbox" in index
    assert "- [[raw-b|Raw B]] - inbox" in index


@pytest.mark.asyncio
async def test_write_note_rejects_concurrent_same_path() -> None:
    gatekeeper = VaultGatekeeper()

    results = await asyncio.gather(
        gatekeeper.write_note(
            VaultWriteIntent(
                folder="00-inbox",
                slug="same-note",
                title="Same Note",
                note_type="inbox",
                body="First writer.",
            )
        ),
        gatekeeper.write_note(
            VaultWriteIntent(
                folder="00-inbox",
                slug="same-note",
                title="Same Note",
                note_type="inbox",
                body="Second writer.",
            )
        ),
        return_exceptions=True,
    )

    successes = [item for item in results if not isinstance(item, Exception)]
    failures = [item for item in results if isinstance(item, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], VaultDuplicateError)


@pytest.mark.asyncio
async def test_find_note_by_id_returns_relative_path() -> None:
    gatekeeper = VaultGatekeeper()
    await gatekeeper.write_note(
        VaultWriteIntent(
            folder="40-people",
            slug="person-a",
            note_id="person:alice",
            title="Alice",
            note_type="person",
            body="Contact note.",
        )
    )

    assert find_note_by_id("person:alice") == "40-people/person-a.md"


@pytest.mark.asyncio
async def test_write_note_rolls_back_created_note_when_index_update_fails(
    _vault_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gatekeeper = VaultGatekeeper()

    def _boom(root: Path, intent: VaultWriteIntent) -> None:
        raise OSError("index write failed")

    monkeypatch.setattr(
        "app.services.vault_gatekeeper._update_folder_index",
        _boom,
    )

    with pytest.raises(VaultIndexUpdateError, match="index write failed"):
        await gatekeeper.write_note(
            VaultWriteIntent(
                folder="20-topics",
                slug="broken-index",
                title="Broken Index",
                note_type="topic",
                body="Should be rolled back.",
            )
        )

    assert not (_vault_dir / "20-topics" / "broken-index.md").exists()


@pytest.mark.asyncio
async def test_write_note_preserves_index_error_when_rollback_also_fails(
    _vault_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gatekeeper = VaultGatekeeper()
    original_unlink = Path.unlink
    logged: list[str] = []

    def _boom(root: Path, intent: VaultWriteIntent) -> None:
        raise OSError("index write failed")

    def _unlink_fail(self: Path, missing_ok: bool = False) -> None:
        if self.name == "broken-rollback.md":
            raise OSError("rollback delete failed")
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(
        "app.services.vault_gatekeeper._update_folder_index",
        _boom,
    )
    monkeypatch.setattr(Path, "unlink", _unlink_fail)
    monkeypatch.setattr(
        "app.services.vault_gatekeeper.logger.error",
        lambda message, path, err: logged.append(message.format(path, err)),
    )

    with pytest.raises(VaultIndexUpdateError, match="index write failed"):
        await gatekeeper.write_note(
            VaultWriteIntent(
                folder="20-topics",
                slug="broken-rollback",
                title="Broken Rollback",
                note_type="topic",
                body="Leaves note behind on rollback failure.",
            )
        )

    assert (_vault_dir / "20-topics" / "broken-rollback.md").exists()
    assert any("vault_write_rollback_failed" in line for line in logged)
