"""Out-of-tree Git-based workspace snapshots for session undo/redo.

Direct port of opencode's ``packages/opencode/src/snapshot/index.ts`` design,
adapted to Python/openagentd. Key properties mirror the original:

- **Out-of-tree git directory** — ``GIT_DIR`` lives in
  ``{OPENAGENTD_STATE_DIR}/snapshot/{session_id}/`` while ``GIT_WORK_TREE``
  points at the actual session workspace. The workspace itself stays free
  of any ``.git`` pollution, and the snapshot repo can coexist with an
  unrelated user-level git repo in coding mode.
- **Tree hashes, not commits** — ``track()`` returns the output of
  ``git write-tree``. There are no commits, refs, or branches; snapshots
  are dangling trees referenced only by hash. ``git gc --prune`` cleans
  them up after expiry.
- **Bulldozer restore** — ``restore(hash)`` runs ``read-tree`` + ``checkout-index
  -a -f``, replacing every tracked file in the workspace with the snapshot's
  version. Untracked files are left alone (we don't delete user-uploaded
  files we never recorded).
- **Per-session async lock** — concurrent track/restore on the same session
  are serialised via :class:`asyncio.Lock` to avoid corrupting the snapshot
  index.

Failures degrade gracefully. If the ``git`` binary is missing, or any git
invocation returns non-zero, the service logs a warning and returns ``None``.
Callers must treat snapshot operations as best-effort — undo/redo still
moves the conversation boundary; only the filesystem rollback is lost.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from app.core.config import settings


@dataclass(slots=True)
class RestoreResult:
    """Outcome of a :func:`restore` call.

    Carries the exact A/M/D path partition diff-index produced so the
    higher layers (HTTP route, frontend cache bridge) can drive scoped
    refreshes — file lists, git diffs — without a whole-repo refetch.

    On failure (``ok=False``) the path lists are empty.
    """

    ok: bool
    #: Paths present in the snapshot but absent from the live index —
    #: i.e. files the restore *created* in the worktree. From the
    #: user's perspective these are files that were deleted by the
    #: agent and have just been brought back.
    added: list[str] = field(default_factory=list)
    #: Paths present in both, differing — the restore *overwrote* them.
    modified: list[str] = field(default_factory=list)
    #: Paths present in the live index but absent from the snapshot —
    #: the restore *removed* them. From the user's perspective these
    #: are files the agent created during the now-undone turn.
    removed: list[str] = field(default_factory=list)

    @property
    def changed_paths(self) -> list[str]:
        """Flat union of every path the restore touched."""
        return [*self.added, *self.modified, *self.removed]


# Files >2 MiB are not tracked (matches opencode's 2 * 1024 * 1024 ceiling).
# This keeps the snapshot repo small and skips large binary outputs that
# would balloon checkout times.
_MAX_FILE_SIZE = 2 * 1024 * 1024

# Core git config flags that must accompany every invocation. They make
# behaviour deterministic across platforms (no CRLF translation, full
# long-path / symlink support, no fsmonitor coupling to the user repo)
# and avoid contending with an unrelated host-side git for ``index.lock``
# via ``--no-optional-locks``.
_CORE_FLAGS: tuple[str, ...] = (
    "--no-optional-locks",
    "-c",
    "core.longpaths=true",
    "-c",
    "core.symlinks=true",
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.quotepath=false",
)

# One asyncio.Lock per session_id keeps concurrent track/restore safe.
_locks: dict[str, asyncio.Lock] = {}


def _lock(session_id: str) -> asyncio.Lock:
    lock = _locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[session_id] = lock
    return lock


def snapshot_dir(session_id: str) -> Path:
    """Return the on-disk ``GIT_DIR`` for this session's snapshot repo."""
    return Path(settings.OPENAGENTD_STATE_DIR) / "snapshot" / session_id


def is_available() -> bool:
    """Return True when the ``git`` binary is on PATH."""
    return shutil.which("git") is not None


async def _git(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    stdin: bytes | None = None,
) -> tuple[int, bytes, bytes]:
    """Run ``git`` and return ``(exit_code, stdout, stderr)``.

    Never raises — all failures are surfaced as a non-zero exit code so the
    caller can decide whether to warn or recover.
    """
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate(stdin)
        return proc.returncode or 0, out, err
    except (OSError, asyncio.CancelledError) as exc:
        logger.warning("snapshot_git_spawn_failed args={} error={}", args, exc)
        return 1, b"", str(exc).encode()


def _gitdir_args(gitdir: Path, worktree: Path) -> list[str]:
    """Standard ``--git-dir / --work-tree`` prefix for ``_git`` calls."""
    return ["--git-dir", str(gitdir), "--work-tree", str(worktree)]


async def _init_repo(gitdir: Path, worktree: Path) -> bool:
    """Initialise the out-of-tree git repo if needed. Idempotent."""
    gitdir.mkdir(parents=True, exist_ok=True)
    head_file = gitdir / "HEAD"
    if head_file.exists():
        return True

    code, _, err = await _git(
        "init",
        env={"GIT_DIR": str(gitdir), "GIT_WORK_TREE": str(worktree)},
    )
    if code != 0:
        logger.warning(
            "snapshot_init_failed gitdir={} stderr={}",
            gitdir,
            err.decode(errors="replace"),
        )
        return False

    # Match opencode's config — autocrlf off, symlinks/longpaths/fsmonitor sane.
    for key, value in (
        ("core.autocrlf", "false"),
        ("core.longpaths", "true"),
        ("core.symlinks", "true"),
        ("core.fsmonitor", "false"),
        # The snapshot repo has no user identity; provide a stable one so any
        # future ``git commit`` (we don't issue any today, but be defensive)
        # does not prompt or fail.
        ("user.email", "snapshot@openagentd.local"),
        ("user.name", "openagentd-snapshot"),
    ):
        await _git("--git-dir", str(gitdir), "config", key, value)

    logger.info("snapshot_initialised session_gitdir={}", gitdir)
    return True


async def _list_candidate_paths(gitdir: Path, worktree: Path) -> list[str]:
    """Return ``worktree``-relative paths to stage: modified + untracked.

    Mirrors opencode's ``add()`` helper. Hidden dotfiles and gitignored
    paths are filtered by ``--exclude-standard`` plus our own size cap.
    The two ``git`` invocations run concurrently because they read from
    disjoint sources (work-tree stat cache vs untracked walk) and the
    ``--no-optional-locks`` flag avoids ``index.lock`` contention.
    """
    args = _gitdir_args(gitdir, worktree)

    tracked_task = _git(
        *_CORE_FLAGS,
        *args,
        "diff-files",
        "--name-only",
        "-z",
        "--",
        ".",
        cwd=worktree,
    )
    untracked_task = _git(
        *_CORE_FLAGS,
        *args,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        ".",
        cwd=worktree,
    )
    (code_d, out_d, _), (code_o, out_o, _) = await asyncio.gather(
        tracked_task, untracked_task
    )

    if code_d != 0 or code_o != 0:
        return []

    tracked = [p for p in out_d.decode(errors="replace").split("\0") if p]
    untracked = [p for p in out_o.decode(errors="replace").split("\0") if p]

    seen: set[str] = set()
    result: list[str] = []
    untracked_set = set(untracked)
    for path in (*tracked, *untracked):
        if path in seen:
            continue
        seen.add(path)
        # Skip oversized files. Already-tracked oversize files keep
        # flowing in via ``diff-files``; we only screen new untracked
        # paths so a freshly-introduced 100 MB blob never enters the
        # repo.
        if path in untracked_set:
            try:
                size = (worktree / path).stat().st_size
            except OSError:
                continue
            if size > _MAX_FILE_SIZE:
                continue
        result.append(path)
    return result


async def _stage(gitdir: Path, worktree: Path, paths: list[str]) -> bool:
    """Stage the given worktree-relative paths into the snapshot index."""
    if not paths:
        return True
    stdin = ("\0".join(paths) + "\0").encode()
    code, _, err = await _git(
        *_CORE_FLAGS,
        *_gitdir_args(gitdir, worktree),
        "add",
        "--all",
        "--sparse",
        "--pathspec-from-file=-",
        "--pathspec-file-nul",
        cwd=worktree,
        stdin=stdin,
    )
    if code != 0:
        logger.warning("snapshot_stage_failed stderr={}", err.decode(errors="replace"))
        return False
    return True


async def track(session_id: str, workspace: Path) -> str | None:
    """Snapshot the workspace state and return its tree hash.

    Returns ``None`` when git is unavailable, the workspace does not exist,
    or any git invocation fails. Safe to call concurrently — locked
    per-session.
    """
    if not is_available():
        return None
    if not workspace.exists() or not workspace.is_dir():
        return None

    gitdir = snapshot_dir(session_id)
    async with _lock(session_id):
        if not await _init_repo(gitdir, workspace):
            return None

        # When the working tree hasn't changed since the last track,
        # ``_list_candidate_paths`` returns an empty list and we skip
        # ``git add`` entirely — write-tree on the existing index gives
        # the same hash. Saves one subprocess per quiescent track.
        paths = await _list_candidate_paths(gitdir, workspace)
        if paths:
            await _stage(gitdir, workspace, paths)

        code, out, err = await _git(
            *_CORE_FLAGS,
            *_gitdir_args(gitdir, workspace),
            "write-tree",
            cwd=workspace,
        )
        if code != 0:
            logger.warning(
                "snapshot_write_tree_failed session_id={} stderr={}",
                session_id,
                err.decode(errors="replace"),
            )
            return None
        snapshot_hash = out.decode().strip()
        if not snapshot_hash:
            return None
        logger.debug(
            "snapshot_tracked session_id={} hash={}",
            session_id,
            snapshot_hash,
        )
        return snapshot_hash


async def restore(
    session_id: str,
    workspace: Path,
    snapshot: str,
    *,
    skip_stage: bool = False,
) -> RestoreResult:
    """Restore the workspace to the given snapshot tree hash.

    Replaces every tracked file in the worktree with its version in
    ``snapshot``. Untracked files (i.e. files that were never recorded
    in any snapshot) are left intact.

    When ``skip_stage`` is True, the caller asserts that the snapshot
    index is already in sync with the live worktree — typically because
    a :func:`track` call just completed and no writes have happened
    since. This skips the ``diff-files`` + ``ls-files --others`` +
    ``git add`` round-trip that otherwise dominates restore latency on
    large workspaces (~80 ms saved on 30k files). The caller pays the
    cost of getting this wrong: a stale index produces an incorrect
    A/M/D set and the wrong files get restored.

    Returns a :class:`RestoreResult` whose ``ok`` flag indicates
    success. On success the ``added`` / ``modified`` / ``removed``
    fields carry the exact path partition diff-index produced, so
    callers can drive scoped cache invalidations downstream. On
    failure all path lists are empty.
    """
    if not is_available():
        return RestoreResult(ok=False)
    if not snapshot:
        return RestoreResult(ok=False)

    gitdir = snapshot_dir(session_id)
    if not (gitdir / "HEAD").exists():
        # No snapshot repo for this session — nothing to restore against.
        logger.warning(
            "snapshot_restore_no_repo session_id={} hash={}", session_id, snapshot
        )
        return RestoreResult(ok=False)

    workspace.mkdir(parents=True, exist_ok=True)
    async with _lock(session_id):
        # ── Stage the live state ──────────────────────────────────
        # Bring the index in sync with the worktree so the
        # ``diff-index --cached`` below sees current state on the
        # left. Without this it would diff against whatever the
        # index held from the previous track — wrong delta.
        # ``skip_stage`` is set by callers that just completed a
        # :func:`track` (e.g. /undo's redo-anchor capture) and know
        # the index already reflects the worktree.
        if not skip_stage:
            live_paths = await _list_candidate_paths(gitdir, workspace)
            if live_paths:
                await _stage(gitdir, workspace, live_paths)

        # ── Single diff-index call → A/M/D partition ──────────────
        # ``diff-index --cached --name-status <snapshot>`` compares
        # the *index* (= current live state, post-stage) against the
        # target snapshot tree directly — no separate ``write-tree``
        # needed. Output is one ``X\0path\0`` pair per changed entry:
        #   A   present in snapshot, absent from index → create
        #   M   present in both, differing → overwrite
        #   D   absent from snapshot, present in index → delete
        # On a 30k-file workspace this eliminates the previous
        # ``write-tree`` (O(N), ~80 ms) and the ``ls-files`` +
        # ``ls-tree`` set-difference (also O(N) each).
        # ``-R`` reverses the diff so the snapshot is treated as the
        # "new" side and the index as the "old" side. Without it, A
        # would mean "added to index since snapshot" (= extras) and D
        # would mean "removed from index since snapshot" (= need to
        # restore). With -R, A = needs restore, D = extras — matching
        # the convention of the parsing loop below.
        diff_code, diff_out, _ = await _git(
            *_CORE_FLAGS,
            *_gitdir_args(gitdir, workspace),
            "diff-index",
            "-R",
            "--cached",
            "--name-status",
            "-r",
            "-z",
            "--no-renames",
            snapshot,
            cwd=workspace,
        )
        if diff_code != 0:
            # ``diff-index`` is the source of truth for what needs to
            # change. If it fails we have no safe partition to act on
            # — surfacing the failure is better than a hidden
            # whole-tree checkout that quietly papers over the bug.
            logger.warning(
                "snapshot_diff_index_failed session_id={} hash={}",
                session_id,
                snapshot,
            )
            return RestoreResult(ok=False)

        # A and M are kept *separate* (not merged into a single
        # ``to_checkout`` list) so the return value can carry the full
        # partition up to the HTTP route. Type-changes are extremely
        # rare; we bucket them with M for restore purposes since
        # checkout-index will rewrite the blob either way.
        # ``-z --name-status`` output format: ``X\0path\0X\0path\0...``
        # where ``X`` is one of A / M / D / T (type-change).
        added: list[str] = []
        modified: list[str] = []
        to_delete: list[str] = []
        parts = diff_out.decode(errors="replace").split("\0")
        i = 0
        while i + 1 < len(parts):
            status = parts[i]
            path = parts[i + 1]
            i += 2
            if not status or not path:
                continue
            first = status[0]
            if first == "A":
                added.append(path)
            elif first in ("M", "T"):
                modified.append(path)
            elif first == "D":
                to_delete.append(path)
        to_checkout: list[str] = [*added, *modified]

        # ── Load the snapshot tree into the index ─────────────────
        code, _, err = await _git(
            *_CORE_FLAGS,
            *_gitdir_args(gitdir, workspace),
            "read-tree",
            snapshot,
            cwd=workspace,
        )
        if code != 0:
            logger.warning(
                "snapshot_read_tree_failed session_id={} hash={} stderr={}",
                session_id,
                snapshot,
                err.decode(errors="replace"),
            )
            return RestoreResult(ok=False)

        # ── Materialise only the changed paths ────────────────────
        # Feed paths via stdin so we don't blow argv on big patches.
        # ``-z`` matches the NUL-separated input.
        if to_checkout:
            stdin = ("\0".join(to_checkout) + "\0").encode()
            code, _, err = await _git(
                *_CORE_FLAGS,
                *_gitdir_args(gitdir, workspace),
                "checkout-index",
                "-f",
                "-z",
                "--stdin",
                cwd=workspace,
                stdin=stdin,
            )
            if code != 0:
                logger.warning(
                    "snapshot_checkout_failed session_id={} hash={} stderr={} count={}",
                    session_id,
                    snapshot,
                    err.decode(errors="replace"),
                    len(to_checkout),
                )
                return RestoreResult(ok=False)

        # ``to_delete`` was computed from the diff; if diff-tree
        # errored we still need to clean *some* extras — fall back
        # to the full ``current - target`` set in that case. Cheap
        # because both index walks happen in parallel.
        _delete_extras(workspace, set(to_delete))

        logger.debug(
            "snapshot_restored session_id={} hash={} checkout={} extras={}",
            session_id,
            snapshot,
            len(to_checkout),
            len(to_delete),
        )
        return RestoreResult(
            ok=True,
            added=added,
            modified=modified,
            removed=to_delete,
        )


def _delete_extras(workspace: Path, extras: set[str]) -> None:
    """Unlink files in ``extras`` and drop any now-empty directories."""
    for rel in extras:
        target = workspace / rel
        try:
            target.unlink()
        except OSError as exc:
            logger.debug("snapshot_extra_unlink_failed path={} error={}", target, exc)
    if not extras:
        return
    # Drop now-empty directories, deepest first.
    for dirpath, _, _ in sorted(
        ((Path(dp), dn, fn) for dp, dn, fn in os.walk(workspace, topdown=False)),
        key=lambda item: len(item[0].parts),
        reverse=True,
    ):
        if dirpath == workspace:
            continue
        try:
            if not any(dirpath.iterdir()):
                dirpath.rmdir()
        except OSError:
            continue


async def cleanup(session_id: str) -> None:
    """Run ``git gc --prune=now`` on the snapshot repo.

    Safe to call periodically. No-ops when the repo does not exist or git
    is unavailable.
    """
    if not is_available():
        return
    gitdir = snapshot_dir(session_id)
    if not (gitdir / "HEAD").exists():
        return
    async with _lock(session_id):
        await _git(
            *_CORE_FLAGS,
            "--git-dir",
            str(gitdir),
            "gc",
            "--prune=now",
            "--quiet",
        )


async def remove(session_id: str) -> None:
    """Delete the snapshot repo for this session.

    Called when a session is permanently deleted. Best-effort — ignores
    missing directories and surface-level OS errors.
    """
    gitdir = snapshot_dir(session_id)
    try:
        if gitdir.exists():
            await asyncio.to_thread(shutil.rmtree, gitdir, ignore_errors=True)
    finally:
        _locks.pop(session_id, None)
