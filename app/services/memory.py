"""Memory v2 service — editable markdown memory plus deterministic search."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession, SessionMessage
from app.services.wiki import (
    INDEX_FILE,
    LOG_FILE,
    NOTES_DIR,
    WikiFileContent,
    WikiFileInfo,
    WikiPathError,
    parse_frontmatter,
    wiki_root,
)

SCHEMA_FILE = "SCHEMA.md"
IMPORTS_DIR = "imports"
WIKI_DIR = "wiki"
MEMORY_ROOT_FILES: tuple[str, ...] = (SCHEMA_FILE, INDEX_FILE, LOG_FILE)
MEMORY_SUBDIRS: tuple[str, ...] = (NOTES_DIR, IMPORTS_DIR, WIKI_DIR)
_SEARCH_ROOT_FILES: tuple[str, ...] = (INDEX_FILE, SCHEMA_FILE, LOG_FILE)
_SEARCH_DIRS: tuple[str, ...] = (WIKI_DIR, NOTES_DIR, IMPORTS_DIR)
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_./:-]*")

DEFAULT_SCHEMA = """# Memory Schema\n\nDream maintains `wiki/*.md` from canonical raw sources.\n\nRules:\n- Keep `notes/` and `imports/` as raw sources; do not rewrite them.\n- Prefer updating existing `wiki/*.md` pages over creating duplicates.\n- Cite stable source refs such as `session:<uuid>`, `message:<uuid>`, `note:<file>#<entry>`, `import:<slug>`, and `wiki:<slug>`.\n- Do not store secrets, credentials, private keys, or temporary noise.\n- Respect explicit “do not remember this” requests.\n"""
DEFAULT_INDEX = """# Memory Index\n\n- `SCHEMA.md` — maintainer rules and conventions.\n- `LOG.md` — chronological Dream activity.\n- `notes/` — raw user/agent notes.\n- `imports/` — raw imported documents.\n- `wiki/` — compiled memory pages.\n"""
DEFAULT_LOG = (
    """# Memory Log\n\nChronological append-only record of Dream memory activity.\n"""
)


@dataclass(frozen=True)
class MemoryTree:
    system: list[WikiFileInfo] = field(default_factory=list)
    notes: list[WikiFileInfo] = field(default_factory=list)
    imports: list[WikiFileInfo] = field(default_factory=list)
    wiki: list[WikiFileInfo] = field(default_factory=list)


@dataclass(frozen=True)
class MemorySearchResult:
    source_ref: str
    path: str | None
    title: str
    excerpt: str
    score: float


def memory_root() -> Path:
    """Return the memory root, currently backed by OPENAGENTD_WIKI_DIR."""
    return wiki_root()


def seed_memory() -> None:
    """Create the memory v2 directory layout and default root files."""
    root = memory_root()
    for subdir in MEMORY_SUBDIRS:
        (root / subdir).mkdir(parents=True, exist_ok=True)

    defaults = {
        SCHEMA_FILE: DEFAULT_SCHEMA,
        INDEX_FILE: DEFAULT_INDEX,
        LOG_FILE: DEFAULT_LOG,
    }
    created: list[str] = []
    for filename, content in defaults.items():
        path = root / filename
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created.append(filename)
    if created:
        logger.info("memory_seeded root={} created={}", root, created)


def validate_memory_path(rel_path: str) -> Path:
    """Validate a memory v2 path and return its resolved absolute path."""
    if not rel_path:
        raise WikiPathError("Memory path must not be empty.")
    if rel_path.startswith(("/", "~")):
        raise WikiPathError(f"Memory path must be relative: {rel_path}")
    if "\\" in rel_path:
        raise WikiPathError(f"Memory path must use forward slashes: {rel_path}")

    raw_parts = rel_path.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        raise WikiPathError(
            f"Memory path may not contain empty, '..', or '.': {rel_path}"
        )
    p = Path(rel_path)
    if p.suffix != ".md":
        raise WikiPathError(f"Memory files must be Markdown (.md): {rel_path}")

    if len(p.parts) == 1:
        if rel_path not in MEMORY_ROOT_FILES:
            allowed = ", ".join(MEMORY_ROOT_FILES)
            raise WikiPathError(f"Only {allowed} are valid at memory root: {rel_path}")
    elif len(p.parts) == 2:
        if p.parts[0] not in MEMORY_SUBDIRS:
            allowed = ", ".join(MEMORY_SUBDIRS)
            raise WikiPathError(
                f"Memory subdir must be one of [{allowed}]: {p.parts[0]}"
            )
    else:
        raise WikiPathError(f"Memory path too deep (max 2 components): {rel_path}")

    root = memory_root()
    resolved = (root / p).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WikiPathError(f"Memory path escapes root: {rel_path}") from exc
    return resolved


def _file_info(rel_path: str, path: Path) -> WikiFileInfo:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("memory_read_failed path={} error={}", rel_path, exc)
        raw = ""
    parsed = parse_frontmatter(raw)
    return WikiFileInfo(
        path=rel_path,
        description=parsed.description,
        updated=parsed.updated,
        tags=parsed.tags,
        confidence=parsed.confidence,
        sources=parsed.sources,
    )


def _list_dir(subdir: str) -> list[WikiFileInfo]:
    root = memory_root() / subdir
    if not root.is_dir():
        return []
    return [
        _file_info(f"{subdir}/{entry.name}", entry)
        for entry in sorted(root.iterdir())
        if entry.is_file() and entry.suffix == ".md"
    ]


def list_memory_tree() -> MemoryTree:
    """Return the memory v2 tree grouped by system/raw/wiki buckets."""
    root = memory_root()
    system = [
        _file_info(filename, root / filename)
        for filename in MEMORY_ROOT_FILES
        if (root / filename).is_file()
    ]
    return MemoryTree(
        system=system,
        notes=_list_dir(NOTES_DIR),
        imports=_list_dir(IMPORTS_DIR),
        wiki=_list_dir(WIKI_DIR),
    )


def read_memory_file(rel_path: str) -> WikiFileContent:
    resolved = validate_memory_path(rel_path)
    if not resolved.is_file():
        raise FileNotFoundError(f"Memory file not found: {rel_path}")
    raw = resolved.read_text(encoding="utf-8")
    parsed = parse_frontmatter(raw)
    return WikiFileContent(
        path=rel_path,
        content=raw,
        description=parsed.description,
        updated=parsed.updated,
        tags=parsed.tags,
        confidence=parsed.confidence,
        sources=parsed.sources,
    )


def write_memory_file(rel_path: str, content: str) -> WikiFileContent:
    resolved = validate_memory_path(rel_path)
    parsed = parse_frontmatter(content)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    logger.info(
        "memory_file_written path={} bytes={}",
        rel_path,
        len(content.encode("utf-8")),
    )
    return WikiFileContent(
        path=rel_path,
        content=content,
        description=parsed.description,
        updated=parsed.updated,
        tags=parsed.tags,
        confidence=parsed.confidence,
        sources=parsed.sources,
    )


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _score(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    tokens = _tokens(text)
    if not tokens:
        return 0.0
    counts = {token: tokens.count(token) for token in query_tokens}
    overlap = sum(counts.values())
    if overlap == 0:
        return 0.0
    coverage = sum(1 for token in query_tokens if counts[token] > 0) / len(query_tokens)
    return (overlap * coverage) / math.log(len(tokens) + 10)


def _excerpt(text: str, query_tokens: set[str], limit: int = 500) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    lower = clean.lower()
    positions = [lower.find(token) for token in query_tokens if lower.find(token) >= 0]
    start = max(min(positions) - 120, 0) if positions else 0
    end = min(start + limit, len(clean))
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(clean) else ""
    return f"{prefix}{clean[start:end]}{suffix}"


def _source_ref_for_file(rel_path: str) -> str:
    path = Path(rel_path)
    if rel_path == INDEX_FILE:
        return "wiki:index"
    if rel_path == SCHEMA_FILE:
        return "wiki:schema"
    if rel_path == LOG_FILE:
        return "wiki:log"
    if path.parts[0] == WIKI_DIR:
        return f"wiki:{path.stem}"
    if path.parts[0] == IMPORTS_DIR:
        return f"import:{path.stem}"
    return f"note:{path.name}"


def search_memory_files(
    query: str, *, limit: int = 8, scope: str = "all"
) -> list[MemorySearchResult]:
    """Search memory markdown files deterministically by token overlap."""
    limit = max(1, limit)
    query_tokens = set(_tokens(query))
    root = memory_root()
    candidates: list[tuple[str, Path]] = []

    if scope not in {"all", "compiled"}:
        raise ValueError(f"Unknown memory file search scope: {scope}")
    if scope == "all":
        candidates.extend((name, root / name) for name in _SEARCH_ROOT_FILES)
        search_dirs = _SEARCH_DIRS
    else:
        search_dirs = (WIKI_DIR,)

    for subdir in search_dirs:
        dir_path = root / subdir
        if dir_path.is_dir():
            candidates.extend(
                (f"{subdir}/{entry.name}", entry)
                for entry in sorted(dir_path.iterdir())
                if entry.is_file() and entry.suffix == ".md"
            )

    results: list[MemorySearchResult] = []
    for rel_path, path in candidates:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        score = _score(query_tokens, f"{rel_path}\n{text}")
        if score <= 0:
            continue
        results.append(
            MemorySearchResult(
                source_ref=_source_ref_for_file(rel_path),
                path=rel_path,
                title=rel_path,
                excerpt=_excerpt(text, query_tokens),
                score=score,
            )
        )
    return sorted(results, key=lambda r: (-r.score, r.source_ref))[:limit]


async def search_memory_messages(
    db: AsyncSession, query: str, *, limit: int = 5
) -> list[MemorySearchResult]:
    """Search visible DB session messages deterministically by token overlap."""
    limit = max(1, limit)
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return []
    stmt = (
        select(SessionMessage, ChatSession)
        .join(ChatSession, col(SessionMessage.session_id) == col(ChatSession.id))
        .where(col(SessionMessage.exclude_from_context).is_(False))
        .where(col(SessionMessage.content).is_not(None))
        .order_by(col(SessionMessage.created_at).desc())
        .limit(500)
    )
    rows = (await db.exec(stmt)).all()
    results: list[MemorySearchResult] = []
    for message, session in rows:
        content = message.content or ""
        title = session.title or session.agent_name or str(session.id)
        text = f"{title}\n{message.role}\n{content}"
        score = _score(query_tokens, text)
        if score <= 0:
            continue
        results.append(
            MemorySearchResult(
                source_ref=f"message:{message.id}",
                path=None,
                title=f"{title} ({message.role})",
                excerpt=_excerpt(content, query_tokens),
                score=score,
            )
        )
    return sorted(results, key=lambda r: (-r.score, r.source_ref))[:limit]


async def memory_search(
    query: str, *, db: AsyncSession | None = None, limit: int = 8
) -> list[MemorySearchResult]:
    """Search wiki, raw files, and optionally DB messages."""
    limit = max(1, limit)
    results = search_memory_files(query, limit=limit)
    if db is not None:
        results.extend(await search_memory_messages(db, query, limit=limit))
    return sorted(results, key=lambda r: (-r.score, r.source_ref))[:limit]
