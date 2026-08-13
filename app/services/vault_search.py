"""Search and read support for the Obsidian vault."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

from app.services.markdown_text import (
    ParsedVaultNote,
    VaultFrontmatterParseError,
    extract_title_from_body_or_slug,
    get_token_sets,
    score_token_overlap,
    split_vault_note_frontmatter,
    strip_markdown_for_snippet,
)
from app.services.vault_gatekeeper import (
    VAULT_FOLDERS,
    validate_vault_note_path,
    vault_root,
)

_READ_RETRIES = 3
_READ_RETRY_DELAY_SECONDS = 0.01
_SNIPPET_CHARS = 500
_MAX_LIMIT = 20


@dataclass(frozen=True)
class VaultNoteInfo:
    """Parsed note information used by vault search."""

    folder: str
    slug: str
    path: str
    metadata: dict[str, Any]
    title: str
    note_type: str
    tags: list[str]
    body: str


_VAULT_CACHE: dict[Path, tuple[int, int, VaultNoteInfo]] = {}
_CACHE_LOCK = asyncio.Lock()


def clear_vault_search_cache() -> None:
    """Clear cached vault search entries."""
    _VAULT_CACHE.clear()


async def read_note(folder: str, slug: str, *, root: Path | None = None) -> str:
    """Read a vault note directly from disk after path validation."""
    path = validate_vault_note_path(f"{folder}/{slug}.md", root=root)
    return await _read_text_with_retry(path)


async def search_notes(
    query: str | None,
    *,
    folder: str | None = None,
    tags: list[str] | None = None,
    limit: int = 5,
    root: Path | None = None,
) -> list[tuple[VaultNoteInfo, float, str]]:
    """Search vault notes using token overlap with exact-match bonus."""
    resolved_root = vault_root(root)
    if folder is not None and folder not in VAULT_FOLDERS:
        validate_vault_note_path(f"{folder}/placeholder.md", root=resolved_root)

    requested_tags = [_normalize_tag(tag) for tag in tags or []]
    requested_tags = [tag for tag in requested_tags if tag]
    max_results = _clamp_limit(limit)
    notes = await _scan_all_notes(resolved_root, folder=folder)
    filtered = [
        note for note in notes if _matches_requested_tags(note.tags, requested_tags)
    ]

    query_text = (query or "").strip()
    if not query_text:
        scored = [(note, 0.0, _snippet(note.body)) for note in filtered]
    else:
        query_tokens = get_token_sets(query_text)
        scored = [
            (note, _score_note(query_tokens, note), _snippet(note.body))
            for note in filtered
        ]
        scored = [item for item in scored if item[1] > 0.0]

    scored.sort(key=lambda item: (-item[1], item[0].path))
    return scored[:max_results]


async def _scan_all_notes(
    root: Path,
    *,
    folder: str | None,
) -> list[VaultNoteInfo]:
    notes: list[VaultNoteInfo] = []
    actual_paths: set[Path] = set()
    folders = [folder] if folder else sorted(VAULT_FOLDERS)
    scanned_roots = {(root / folder_name).resolve() for folder_name in folders}

    for folder_name in folders:
        folder_path = root / folder_name
        if not folder_path.is_dir():
            continue
        for entry in sorted(folder_path.iterdir(), key=lambda path: path.name.lower()):
            if not entry.is_file() or entry.suffix.lower() != ".md":
                continue
            if entry.name == "_index.md":
                continue
            resolved = entry.resolve()
            actual_paths.add(resolved)
            note = await _note_from_cache_or_disk(
                resolved,
                folder=folder_name,
                slug=entry.stem,
            )
            if note is not None:
                notes.append(note)

    async with _CACHE_LOCK:
        stale = [
            path
            for path in _VAULT_CACHE
            if _is_under_scanned_roots(path, scanned_roots) and path not in actual_paths
        ]
        for path in stale:
            _VAULT_CACHE.pop(path, None)
    return notes


async def _note_from_cache_or_disk(
    path: Path,
    *,
    folder: str,
    slug: str,
) -> VaultNoteInfo | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    async with _CACHE_LOCK:
        cached = _VAULT_CACHE.get(path)
    if (
        sys.platform != "win32"
        and cached is not None
        and cached[0] == stat.st_mtime_ns
        and cached[1] == stat.st_size
    ):
        return cached[2]

    stat_before = (stat.st_mtime_ns, stat.st_size)
    try:
        raw = await _read_text_with_retry(path)
        parsed = split_vault_note_frontmatter(raw)
    except (
        FileNotFoundError,
        PermissionError,
        UnicodeDecodeError,
        VaultFrontmatterParseError,
        OSError,
    ):
        return None

    note = _build_note_info(folder=folder, slug=slug, parsed=parsed)
    try:
        stat_after_result = path.stat()
    except FileNotFoundError:
        return note
    stat_after = (stat_after_result.st_mtime_ns, stat_after_result.st_size)
    if stat_before == stat_after:
        async with _CACHE_LOCK:
            _VAULT_CACHE[path] = (stat_after[0], stat_after[1], note)
    return note


def _build_note_info(
    *,
    folder: str,
    slug: str,
    parsed: ParsedVaultNote,
) -> VaultNoteInfo:
    metadata = dict(parsed.metadata)
    title = str(
        metadata.get("title") or extract_title_from_body_or_slug(parsed.body, slug)
    )
    note_type = str(metadata.get("type") or "note")
    return VaultNoteInfo(
        folder=folder,
        slug=slug,
        path=f"{folder}/{slug}.md",
        metadata=metadata,
        title=title,
        note_type=note_type,
        tags=_normalize_tags(metadata.get("tags")),
        body=parsed.body,
    )


def _score_note(query_tokens, note: VaultNoteInfo) -> float:
    return (
        score_token_overlap(query_tokens, get_token_sets(note.title), 2.0)
        + score_token_overlap(query_tokens, get_token_sets(" ".join(note.tags)), 1.5)
        + score_token_overlap(query_tokens, get_token_sets(note.slug), 1.0)
        + score_token_overlap(query_tokens, get_token_sets(note.body), 0.5)
    )


async def _read_text_with_retry(path: Path) -> str:
    last_exc: Exception | None = None
    for attempt in range(_READ_RETRIES):
        try:
            return path.read_text(encoding="utf-8")
        except (PermissionError, FileNotFoundError) as exc:
            last_exc = exc
            if attempt == _READ_RETRIES - 1:
                raise
            await asyncio.sleep(_READ_RETRY_DELAY_SECONDS)
    if last_exc is not None:
        raise last_exc
    raise FileNotFoundError(path)


def _normalize_tags(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_values = [value] if value.strip() else []
    elif isinstance(value, list):
        raw_values = [str(item) for item in value]
    else:
        raw_values = []
    seen: set[str] = set()
    result: list[str] = []
    for raw in raw_values:
        tag = _normalize_tag(raw)
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return result


def _normalize_tag(value: str) -> str:
    return str(value).strip().lower().lstrip("#")


def _matches_requested_tags(note_tags: list[str], requested_tags: list[str]) -> bool:
    if not requested_tags:
        return True
    for requested in requested_tags:
        if not any(
            tag == requested or tag.startswith(f"{requested}/") for tag in note_tags
        ):
            return False
    return True


def _snippet(body: str) -> str:
    cleaned = strip_markdown_for_snippet(body)
    if len(cleaned) <= _SNIPPET_CHARS:
        return cleaned
    return cleaned[:_SNIPPET_CHARS].rstrip() + "..."


def _clamp_limit(limit: int) -> int:
    return max(1, min(int(limit), _MAX_LIMIT))


def _is_under_scanned_roots(path: Path, scanned_roots: set[Path]) -> bool:
    return any(path.parent == folder_path for folder_path in scanned_roots)
