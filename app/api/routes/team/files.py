"""Uploads, workspace media proxy, and flat workspace file listing.

Two endpoints, one root (see :mod:`app.core.paths`):

- ``GET /api/team/{sid}/uploads/{filename}`` →
  ``{OPENAGENTD_WORKSPACE_DIR}/{sid}/uploads/{filename}``
  User-uploaded attachments. Flat namespace (UUID-named by the uploader).

- ``GET /api/team/{sid}/media/{path}`` → ``{OPENAGENTD_WORKSPACE_DIR}/{sid}/{path}``
  Agent workspace output (files written by the write/shell tools). Nested
  paths allowed. Target of bare markdown image refs rendered by the
  assistant: ``![alt](chart.png)`` → ``/api/team/{sid}/media/chart.png``.

``GET /api/team/{sid}/files`` provides a flat recursive listing of the
agent workspace — powers the "Artifacts" panel in the web UI.
"""

from __future__ import annotations

import asyncio
import difflib
import mimetypes
import os
import subprocess
import uuid
from fnmatch import fnmatchcase
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.schemas.team import (
    CodingWorkspaceFilesResponse,
    WorkspaceFileInfo,
    WorkspaceFilesResponse,
)
from app.core.db import async_session_factory
from app.core.paths import session_workspace_dir, uploads_dir, workspace_dir
from app.models.chat import ChatSession
from app.services import team_manager

router = APIRouter()


# ── Path-safety helpers ───────────────────────────────────────────────────────


def _safe_resolve(root: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``root`` with traversal protection.

    Raises ``HTTPException(400)`` on traversal attempts (``..``, absolute
    paths, symlink escapes) and on empty paths.  Raises ``HTTPException(404)``
    when the resolved target does not exist or is not a regular file.
    """
    if not rel or rel.strip() == "":
        raise HTTPException(status_code=400, detail="Empty media path.")

    # Reject absolute paths and Windows drive letters early.
    candidate = Path(rel)
    if candidate.is_absolute() or (len(rel) >= 2 and rel[1] == ":"):
        raise HTTPException(status_code=400, detail="Absolute media paths rejected.")

    try:
        resolved = (root / candidate).resolve(strict=False)
        root_resolved = root.resolve(strict=False)
    except (OSError, RuntimeError):
        raise HTTPException(status_code=400, detail="Invalid media path.")

    # Containment check — fails on ``..`` escapes and symlinks pointing outside.
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise HTTPException(status_code=400, detail="Media path escapes session root.")

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Media file not found.")

    return resolved


def _guess_media_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


async def _session_workspace(session_id: str) -> Path:
    """Resolve a session's workspace root, tolerating absent DB rows.

    Coding-mode sessions stash an absolute project path in
    ``ChatSession.workspace``; normal sessions leave it ``NULL`` and fall
    back to the per-session sandbox directory under
    ``OPENAGENTD_WORKSPACE_DIR``. The fallback uses this module's local
    ``workspace_dir`` reference so tests can monkey-patch it.
    """
    row = None
    try:
        async with async_session_factory() as db:
            row = await db.get(ChatSession, uuid.UUID(session_id))
    except Exception:
        row = None
    if row is not None and row.workspace:
        return session_workspace_dir(session_id, row.workspace)
    return workspace_dir(session_id)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/{session_id}/uploads/{filename}")
async def get_uploaded_file(session_id: str, filename: str) -> FileResponse:
    """Serve a user-uploaded attachment from the session's uploads dir.

    Flat namespace — ``filename`` must not contain path separators.
    """
    # Reject anything that looks like a path — uploads are flat.
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="Invalid upload filename.")

    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id.")

    resolved = _safe_resolve(uploads_dir(session_id), filename)
    return FileResponse(
        path=str(resolved),
        media_type=_guess_media_type(resolved),
        filename=resolved.name,
    )


@router.get("/{session_id}/media/{file_path:path}")
async def get_workspace_media(session_id: str, file_path: str) -> FileResponse:
    """Serve a file from the session's agent workspace.

    Supports nested subpaths (e.g. ``output/chart.png``).  Path traversal is
    rejected; symlink escapes outside the workspace root are rejected via
    containment check on the resolved path.
    """
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id.")

    # Workspace state is authoritative — when the session is in a reverted
    # tail, :mod:`app.services.snapshot_service` has already restored the
    # filesystem to the boundary's snapshot, so files that should be
    # hidden simply do not exist on disk and ``_safe_resolve`` 404s.
    resolved = _safe_resolve(await _session_workspace(session_id), file_path)

    return FileResponse(
        path=str(resolved),
        media_type=_guess_media_type(resolved),
        filename=resolved.name,
    )


# ── Workspace file listing ────────────────────────────────────────────────────
#
# Flat recursive listing of the agent workspace.
# Design choices:
#   - Flat list (not tree) — the UI groups by directory, keeps payload simple.
#   - Regular files only (no dirs, no symlinks leaving the root).
#   - Paths are relative (POSIX separators) — safe to pass back to ``/media/``.
#   - Size cap on the walk to avoid pathological workspaces blowing up the
#     response.  Beyond the cap we truncate and flag it.

_MAX_FILES_LISTED = 500
_MAX_GIT_DIFF_CHARS = 512 * 1024
_MAX_UNTRACKED_DIFF_BYTES = 256 * 1024
_SKIPPED_DIR_NAMES = frozenset(
    {"node_modules", "dist", "build", ".venv", "venv", "__pycache__"}
)


def _load_gitignore_rules(root: Path) -> list[tuple[str, bool]]:
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return []
    try:
        lines = gitignore.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    rules: list[tuple[str, bool]] = []
    for line in lines:
        pattern = line.strip()
        if not pattern or pattern.startswith("#"):
            continue
        include = pattern.startswith("!")
        if include:
            pattern = pattern[1:].strip()
        if pattern:
            rules.append((pattern, include))
    return rules


def _matches_gitignore_pattern(pattern: str, rel: str, *, is_dir: bool) -> bool:
    directory_only = pattern.endswith("/")
    pattern = pattern.strip("/") if directory_only else pattern.lstrip("/")
    if not pattern:
        return False

    if directory_only:
        return rel == pattern if is_dir else rel.startswith(f"{pattern}/")

    if "/" in pattern:
        return fnmatchcase(rel, pattern) or fnmatchcase(rel, f"{pattern}/*")

    parts = rel.split("/")
    return any(fnmatchcase(part, pattern) for part in parts)


def _is_gitignored(rel: str, *, is_dir: bool, rules: list[tuple[str, bool]]) -> bool:
    ignored = False
    for pattern, include in rules:
        if _matches_gitignore_pattern(pattern, rel, is_dir=is_dir):
            ignored = not include
    return ignored


@router.get("/{session_id}/files", response_model=WorkspaceFilesResponse)
async def list_workspace_files(session_id: str) -> WorkspaceFilesResponse:
    """List every file under the session's agent workspace, recursively.

    Returns an empty list when the workspace directory does not yet exist
    (fresh session — no tool has written anything).  Hidden dotfiles are
    skipped; symlinks pointing outside the workspace root are skipped.
    """
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id.")

    # No boundary filtering needed — snapshot_service has restored the
    # workspace to the reverted-boundary state, so the on-disk file set
    # already reflects what should be visible.
    return _list_workspace_files(
        await _session_workspace(session_id),
        session_id,
    )


def _list_workspace_files(root: Path, session_id: str) -> WorkspaceFilesResponse:
    if not root.exists() or not root.is_dir():
        return WorkspaceFilesResponse(session_id=session_id, files=[], truncated=False)

    root_resolved = root.resolve(strict=False)
    gitignore_rules = _load_gitignore_rules(root)
    files: list[WorkspaceFileInfo] = []
    truncated = False

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".")
            and name not in _SKIPPED_DIR_NAMES
            and not _is_gitignored(
                (current / name).relative_to(root).as_posix(),
                is_dir=True,
                rules=gitignore_rules,
            )
        )

        for filename in sorted(filenames):
            if len(files) >= _MAX_FILES_LISTED:
                truncated = True
                break
            if filename.startswith("."):
                continue
            entry = current / filename
            rel = entry.relative_to(root).as_posix()
            if _is_gitignored(rel, is_dir=False, rules=gitignore_rules):
                continue
            try:
                resolved = entry.resolve(strict=False)
                resolved.relative_to(root_resolved)
            except (OSError, ValueError):
                continue
            if not entry.is_file():
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            mime, _ = mimetypes.guess_type(str(entry))
            files.append(
                WorkspaceFileInfo(
                    path=rel,
                    name=entry.name,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    mime=mime or "application/octet-stream",
                )
            )
        if truncated:
            break

    return WorkspaceFilesResponse(
        session_id=session_id, files=files, truncated=truncated
    )


@router.get("/workspace/files/list", response_model=CodingWorkspaceFilesResponse)
async def list_coding_workspace_files(workspace: str) -> CodingWorkspaceFilesResponse:
    try:
        resolved = team_manager.validate_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    listing = _list_workspace_files(Path(resolved), "workspace")
    return CodingWorkspaceFilesResponse(
        workspace=resolved,
        files=listing.files,
        truncated=listing.truncated,
    )


@router.get("/workspace/git-diff/view")
async def get_coding_workspace_git_diff(workspace: str) -> dict:
    try:
        resolved = team_manager.validate_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    root = Path(resolved)
    if not (root / ".git").exists():
        return {"workspace": resolved, "is_git_repo": False, "diff": ""}

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", resolved, "diff", "--", "."],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=500, detail=f"git diff failed: {exc}") from exc

    if result.returncode != 0:
        raise HTTPException(
            status_code=500, detail=result.stderr.strip() or "git diff failed"
        )
    untracked_out = await _run_git(
        resolved, "ls-files", "--others", "--exclude-standard"
    )
    untracked = untracked_out.splitlines() if untracked_out is not None else []
    tracked_diff = str(result.stdout)
    full_diff = tracked_diff + _untracked_diff(root, untracked)
    truncated = len(full_diff) > _MAX_GIT_DIFF_CHARS
    diff = full_diff[:_MAX_GIT_DIFF_CHARS]
    return {
        "workspace": resolved,
        "is_git_repo": True,
        "diff": diff,
        "untracked": untracked,
        "truncated": truncated,
    }


def _untracked_diff(root: Path, paths: list[str]) -> str:
    chunks: list[str] = []
    for path in paths:
        file_path = root / path
        try:
            if (
                not file_path.is_file()
                or file_path.stat().st_size > _MAX_UNTRACKED_DIFF_BYTES
            ):
                chunks.append(
                    f"\ndiff --git a/{path} b/{path}\n"
                    "new file mode 100644\n"
                    f"Binary or large file not shown: {path}\n"
                )
                continue
            lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        except (OSError, UnicodeDecodeError):
            chunks.append(
                f"\ndiff --git a/{path} b/{path}\n"
                "new file mode 100644\n"
                f"Binary or unreadable file not shown: {path}\n"
            )
            continue

        body = "".join(
            difflib.unified_diff(
                [],
                lines,
                fromfile="/dev/null",
                tofile=f"b/{path}",
            )
        )
        chunks.append(f"\ndiff --git a/{path} b/{path}\nnew file mode 100644\n{body}")
    return "".join(chunks)


async def _run_git(cwd: str, *args: str, timeout: float = 5.0) -> str | None:
    """Run a git command, returning stdout on success or None on any failure."""
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    # ``text=True`` above guarantees a str
    return str(result.stdout)


def _parse_porcelain_v2(stdout: str) -> tuple[str | None, dict[str, int]]:
    """Parse ``git status --porcelain=v2 --branch`` output.

    Returns ``(branch, counts)`` where ``counts`` has keys ``staged``,
    ``unstaged``, ``untracked``. ``branch`` is ``None`` for detached HEAD.
    """
    branch: str | None = None
    staged = unstaged = untracked = 0
    for line in stdout.splitlines():
        if line.startswith("# branch.head "):
            head = line[len("# branch.head ") :].strip()
            branch = None if head == "(detached)" else head
        elif line.startswith(("1 ", "2 ")):
            # XY status code in field 2 (e.g. "M.", ".M", "MM")
            parts = line.split(" ", 2)
            if len(parts) >= 2 and len(parts[1]) == 2:
                if parts[1][0] != ".":
                    staged += 1
                if parts[1][1] != ".":
                    unstaged += 1
        elif line.startswith("? "):
            untracked += 1
    return branch, {"staged": staged, "unstaged": unstaged, "untracked": untracked}


@router.get("/workspace/status")
async def get_coding_workspace_status(workspace: str) -> dict:
    """Lightweight workspace overview for the coding-mode empty state.

    Returns workspace path + name (always), and git metadata (branch, dirty
    counts, last commit) when the folder is a git repo. Failures degrade
    gracefully — missing git / dirty parse errors yield ``is_git_repo: false``
    rather than 500.
    """
    try:
        resolved = team_manager.validate_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    root = Path(resolved)
    name = root.name or resolved
    payload: dict = {"workspace": resolved, "name": name, "is_git_repo": False}

    if not (root / ".git").exists():
        return payload

    status_out = await _run_git(resolved, "status", "--porcelain=v2", "--branch")
    if status_out is None:
        return payload
    branch, counts = _parse_porcelain_v2(status_out)

    head: dict | None = None
    log_out = await _run_git(resolved, "log", "-1", "--format=%h%x00%s%x00%ct")
    if log_out:
        parts = log_out.rstrip("\n").split("\x00")
        if len(parts) == 3:
            try:
                head = {
                    "sha": parts[0],
                    "subject": parts[1],
                    "timestamp": int(parts[2]),
                }
            except ValueError:
                head = None

    payload.update(
        {
            "is_git_repo": True,
            "branch": branch,
            "dirty": counts,
            "head": head,
        }
    )
    return payload
