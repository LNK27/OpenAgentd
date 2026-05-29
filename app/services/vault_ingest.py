"""Human Obsidian vault ingest/reconcile service.

This service normalizes hand-written Obsidian notes into the same v7
frontmatter shape used by agent-created vault notes, while preserving user
content and custom metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from app.services.markdown_text import (
    extract_title_from_body_or_slug,
    split_vault_note_frontmatter,
)
from app.services.vault_gatekeeper import (
    VAULT_FOLDERS,
    _atomic_write,
    get_vault_gatekeeper,
    validate_vault_note_path,
    vault_root,
)

_REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "type",
    "status",
    "tags",
    "created_at",
    "updated_at",
    "source_refs",
    "relations",
    "last_summarized_at",
    "writer",
)

_INDEX_LINK_RE = re.compile(r"\[\[([^]|\r\n]+)\|")


@dataclass
class IngestResult:
    """Summary report for a vault ingest run."""

    scanned: int = 0
    normalized: int = 0
    indexed: int = 0
    stale_removed: int = 0
    skipped_ok: int = 0
    skipped_subfolders: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _ReconcilePlan:
    content: str
    metadata: dict[str, Any]
    changed: bool


async def ingest_vault(
    *, apply: bool = False, root: Path | None = None
) -> IngestResult:
    """Scan and reconcile human-created notes in the configured vault."""
    result = IngestResult()
    resolved_root = vault_root(root)
    gatekeeper = get_vault_gatekeeper()

    for folder in sorted(VAULT_FOLDERS):
        folder_path = resolved_root / folder
        if not folder_path.is_dir():
            continue
        folder_slugs = _scan_existing_slugs(folder_path)
        for entry in sorted(folder_path.iterdir(), key=lambda item: item.name.lower()):
            if entry.is_dir():
                result.skipped_subfolders += 1
                result.warnings.append(
                    f"{folder}/{entry.name}/ — skipped (subfolder not supported in v1)"
                )
                continue
            if not entry.is_file() or entry.suffix.lower() != ".md":
                continue
            if entry.name == "_index.md":
                continue
            try:
                raw = entry.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                result.warnings.append(
                    f"{folder}/{entry.name} — skipped (non-UTF-8 file)"
                )
                continue
            except OSError as exc:
                result.errors.append(f"{folder}/{entry.name} — read failed: {exc}")
                continue

            result.scanned += 1
            rel_path = f"{folder}/{entry.name}"
            try:
                validate_vault_note_path(rel_path, root=resolved_root)
                plan = _build_reconcile_plan(
                    raw=raw,
                    slug=entry.stem,
                    mtime=_mtime_utc(entry),
                )
            except Exception as exc:
                result.errors.append(f"{rel_path} — {exc}")
                logger.warning(
                    "vault_ingest_note_failed path={} error={}", rel_path, exc
                )
                continue

            if not plan.changed:
                result.skipped_ok += 1
            else:
                result.normalized += 1

            if apply:
                async with gatekeeper._lock:
                    if plan.changed:
                        _atomic_write(entry, plan.content)
                    if _ensure_index_link(
                        resolved_root,
                        folder=folder,
                        slug=entry.stem,
                        title=str(plan.metadata["title"]),
                        note_type=str(plan.metadata["type"]),
                        apply=True,
                    ):
                        result.indexed += 1
            elif _ensure_index_link(
                resolved_root,
                folder=folder,
                slug=entry.stem,
                title=str(plan.metadata["title"]),
                note_type=str(plan.metadata["type"]),
                apply=False,
            ):
                result.indexed += 1

        if apply:
            async with gatekeeper._lock:
                result.stale_removed += _remove_stale_index_links(
                    resolved_root,
                    folder=folder,
                    existing_slugs=folder_slugs,
                    apply=True,
                )
        else:
            result.stale_removed += _remove_stale_index_links(
                resolved_root,
                folder=folder,
                existing_slugs=folder_slugs,
                apply=False,
            )

    return result


def _scan_existing_slugs(folder_path: Path) -> set[str]:
    slugs: set[str] = set()
    for entry in folder_path.iterdir():
        if (
            entry.is_file()
            and entry.suffix.lower() == ".md"
            and entry.name != "_index.md"
        ):
            slugs.add(entry.stem)
    return slugs


def _build_reconcile_plan(*, raw: str, slug: str, mtime: str) -> _ReconcilePlan:
    parsed = split_vault_note_frontmatter(raw)
    metadata = dict(parsed.metadata)
    before = dict(metadata)
    defaults = _default_metadata(slug=slug, body=parsed.body, mtime=mtime)
    for field_name in _REQUIRED_FIELDS:
        if field_name not in metadata:
            metadata[field_name] = defaults[field_name]
    changed = metadata != before or not parsed.had_frontmatter
    if not changed:
        return _ReconcilePlan(content=raw, metadata=metadata, changed=False)
    return _ReconcilePlan(
        content=_render_note(metadata=metadata, body=parsed.body),
        metadata=metadata,
        changed=True,
    )


def _default_metadata(*, slug: str, body: str, mtime: str) -> dict[str, Any]:
    return {
        "id": slug,
        "title": extract_title_from_body_or_slug(body=body, slug=slug),
        "type": "note",
        "status": "draft",
        "tags": [],
        "created_at": mtime,
        "updated_at": mtime,
        "source_refs": [],
        "relations": [],
        "last_summarized_at": None,
        "writer": "human",
    }


def _mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def _render_note(*, metadata: dict[str, Any], body: str) -> str:
    yaml_block = yaml.safe_dump(
        metadata,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    return f"---\n{yaml_block}\n---\n{body}"


def _ensure_index_link(
    root: Path,
    *,
    folder: str,
    slug: str,
    title: str,
    note_type: str,
    apply: bool,
) -> bool:
    index_path = root / folder / "_index.md"
    if not index_path.exists():
        return False
    text = index_path.read_text(encoding="utf-8")
    if f"[[{slug}|" in text or f"[[{slug}]]" in text:
        return False
    line = f"- [[{slug}|{title.strip()}]] - {note_type.strip()}\n"
    updated = text.rstrip() + "\n" + line
    if apply:
        _atomic_write(index_path, updated)
    return True


def _remove_stale_index_links(
    root: Path,
    *,
    folder: str,
    existing_slugs: set[str],
    apply: bool,
) -> int:
    index_path = root / folder / "_index.md"
    if not index_path.exists():
        return 0
    text = index_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    removed = 0
    for line in lines:
        match = _INDEX_LINK_RE.search(line)
        if match and match.group(1) not in existing_slugs:
            removed += 1
            continue
        kept.append(line)
    if removed and apply:
        _atomic_write(index_path, "".join(kept))
    return removed
