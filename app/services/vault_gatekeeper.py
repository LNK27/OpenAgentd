"""Obsidian vault gatekeeper.

This module is the single in-process writer for the user's Obsidian vault.
It keeps agent writes narrow: validate a v7 vault path, normalize required
frontmatter, write atomically, and update the containing folder index.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from app.core.config import settings
from app.services.wiki import parse_frontmatter

VAULT_FOLDERS: frozenset[str] = frozenset(
    {
        "00-inbox",
        "10-sources",
        "20-topics",
        "30-projects",
        "40-people",
        "50-decisions",
        "90-archive",
    }
)

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_WINDOWS_RESERVED_NAMES: frozenset[str] = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
)


class VaultPathError(ValueError):
    """Raised when a vault path is invalid or unsafe."""


class VaultDuplicateError(ValueError):
    """Raised when a write would duplicate an existing note."""


class VaultWriteError(OSError):
    """Raised when the note file itself could not be written."""


class VaultIndexUpdateError(OSError):
    """Raised when note creation succeeded but index maintenance failed."""

    def __init__(
        self,
        *,
        path: str,
        rollback_succeeded: bool,
        message: str,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.rollback_succeeded = rollback_succeeded


@dataclass(frozen=True)
class VaultWriteIntent:
    """Structured write request accepted by the gatekeeper."""

    folder: str
    slug: str
    title: str
    note_type: str
    body: str
    status: str = "draft"
    tags: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)
    writer: str = "agent"
    note_id: str | None = None
    last_summarized_at: str | None = None
    overwrite: bool = False


@dataclass(frozen=True)
class VaultWriteResult:
    """Result of a committed vault write."""

    path: str
    note_id: str
    created: bool
    content: str


def vault_root(root: Path | None = None) -> Path:
    """Return the configured Obsidian vault root, creating it if missing."""
    resolved = (root or Path(settings.OPENAGENTD_OBSIDIAN_VAULT_DIR)).resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def validate_vault_note_path(rel_path: str, *, root: Path | None = None) -> Path:
    """Validate an agent-writable note path under the Obsidian vault."""
    if not rel_path:
        raise VaultPathError("Vault path must not be empty.")
    if rel_path.startswith(("/", "~")):
        raise VaultPathError(f"Vault path must be relative: {rel_path}")

    path = Path(rel_path)
    if path.is_absolute():
        raise VaultPathError(f"Vault path must be relative: {rel_path}")
    if path.suffix != ".md":
        raise VaultPathError(f"Vault files must be Markdown (.md): {rel_path}")

    raw_parts = rel_path.replace("\\", "/").split("/")
    if any(part in ("..", ".") for part in raw_parts):
        raise VaultPathError(f"Vault path may not contain '..' or '.': {rel_path}")

    parts = path.parts
    if len(parts) != 2:
        raise VaultPathError(f"Vault notes must be exactly folder/file.md: {rel_path}")
    if parts[0] not in VAULT_FOLDERS:
        allowed = ", ".join(sorted(VAULT_FOLDERS))
        raise VaultPathError(f"Vault folder must be one of [{allowed}]: {parts[0]!r}")
    if parts[1] == "_index.md":
        raise VaultPathError("Agents may not write vault index files directly.")
    _validate_windows_safe_stem(Path(parts[1]).stem)

    resolved_root = vault_root(root)
    candidate = (resolved_root / path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise VaultPathError(f"Vault path escapes root: {rel_path}") from exc
    return candidate


def render_vault_note(intent: VaultWriteIntent, *, now: datetime | None = None) -> str:
    """Render an intent to Markdown with normalized v7 frontmatter."""
    timestamp = (now or datetime.now(UTC)).isoformat()
    note_id = intent.note_id or intent.slug
    metadata: dict[str, Any] = {
        "id": note_id,
        "title": intent.title.strip(),
        "type": intent.note_type.strip(),
        "status": intent.status.strip(),
        "tags": _normalize_list(intent.tags),
        "created_at": timestamp,
        "updated_at": timestamp,
        "source_refs": _normalize_list(intent.source_refs),
        "relations": _normalize_list(intent.relations),
        "last_summarized_at": intent.last_summarized_at,
        "writer": intent.writer.strip() or "agent",
    }
    yaml_block = yaml.safe_dump(
        metadata,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    body = intent.body.strip()
    return f"---\n{yaml_block}\n---\n\n{body}\n"


class VaultGatekeeper:
    """Sequential writer for Obsidian vault notes."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root
        self._lock = asyncio.Lock()

    async def write_note(self, intent: VaultWriteIntent) -> VaultWriteResult:
        """Serialize, validate, and commit a note write."""
        async with self._lock:
            return await asyncio.to_thread(self._write_note_sync, intent)

    def _write_note_sync(self, intent: VaultWriteIntent) -> VaultWriteResult:
        _validate_intent(intent)
        rel_path = f"{intent.folder}/{intent.slug}.md"
        target = validate_vault_note_path(rel_path, root=self._root)
        root = vault_root(self._root)
        note_id = intent.note_id or intent.slug

        created = not target.exists()
        if target.exists() and not intent.overwrite:
            raise VaultDuplicateError(f"Vault note already exists: {rel_path}")

        content = render_vault_note(intent)
        try:
            _atomic_write(target, content)
        except OSError as exc:
            raise VaultWriteError(f"Failed to write vault note: {rel_path}") from exc
        try:
            _update_folder_index(root, intent)
        except Exception as exc:
            rollback_succeeded = False
            if created:
                try:
                    target.unlink()
                    rollback_succeeded = True
                except OSError as rollback_exc:
                    logger.error(
                        "vault_write_rollback_failed path={} err={}",
                        rel_path,
                        rollback_exc,
                    )
            raise VaultIndexUpdateError(
                path=rel_path,
                rollback_succeeded=rollback_succeeded,
                message=str(exc),
            ) from exc
        logger.info("vault_note_written path={} created={}", rel_path, created)
        return VaultWriteResult(
            path=rel_path,
            note_id=note_id,
            created=created,
            content=content,
        )


def find_note_by_id(note_id: str, *, root: Path | None = None) -> str | None:
    """Return the relative path of the first note with *note_id*, if any."""
    resolved_root = vault_root(root)
    for folder in sorted(VAULT_FOLDERS):
        folder_path = resolved_root / folder
        if not folder_path.is_dir():
            continue
        for path in sorted(folder_path.glob("*.md")):
            if path.name == "_index.md":
                continue
            try:
                parsed = parse_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if _frontmatter_id(parsed.raw) == note_id:
                return f"{folder}/{path.name}"
    return None


_default_gatekeeper: VaultGatekeeper | None = None


def get_vault_gatekeeper() -> VaultGatekeeper:
    """Return the process-wide vault gatekeeper."""
    global _default_gatekeeper
    if _default_gatekeeper is None:
        _default_gatekeeper = VaultGatekeeper()
    return _default_gatekeeper


def _validate_intent(intent: VaultWriteIntent) -> None:
    if intent.folder not in VAULT_FOLDERS:
        allowed = ", ".join(sorted(VAULT_FOLDERS))
        raise VaultPathError(
            f"Vault folder must be one of [{allowed}]: {intent.folder!r}"
        )
    if not _SLUG_RE.match(intent.slug):
        raise VaultPathError(f"Vault slug is invalid: {intent.slug!r}")
    _validate_windows_safe_stem(intent.slug)
    if not intent.title.strip():
        raise ValueError("Vault note title must not be empty.")
    if not intent.note_type.strip():
        raise ValueError("Vault note type must not be empty.")
    if not intent.body.strip():
        raise ValueError("Vault note body must not be empty.")
    if intent.note_id is not None and not intent.note_id.strip():
        raise ValueError("Vault note id must not be empty when provided.")


def _validate_windows_safe_stem(stem: str) -> None:
    base = stem.split(".", 1)[0].upper()
    if base in _WINDOWS_RESERVED_NAMES:
        raise VaultPathError(f"Vault slug uses a reserved Windows filename: {stem!r}")


def _normalize_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _frontmatter_id(raw: str) -> str | None:
    if not raw.startswith("---"):
        return None
    try:
        block = raw.split("---", 2)[1]
        data = yaml.safe_load(block) or {}
    except (IndexError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    note_id = data.get("id")
    return str(note_id).strip() if note_id else None


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _update_folder_index(root: Path, intent: VaultWriteIntent) -> None:
    index_path = root / intent.folder / "_index.md"
    if not index_path.exists():
        return
    text = index_path.read_text(encoding="utf-8")
    link = f"[[{intent.slug}|{intent.title.strip()}]]"
    if link in text or f"[[{intent.slug}]]" in text:
        return
    line = f"- {link} - {intent.note_type.strip()}\n"
    marker = "## "
    if "Danh" in text and marker in text:
        text = text.rstrip() + "\n" + line
    else:
        text = text.rstrip() + "\n\n## Notes\n" + line
    _atomic_write(index_path, text)
