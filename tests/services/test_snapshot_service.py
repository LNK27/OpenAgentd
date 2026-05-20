"""Unit tests for :mod:`app.services.snapshot_service`.

Exercises the out-of-tree Git snapshot lifecycle end-to-end against a real
``git`` binary in a temporary directory. Skipped automatically when git is
not on PATH so the suite still runs in minimal environments.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.services import snapshot_service


pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary not available"
)


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``OPENAGENTD_STATE_DIR`` so the snapshot repo lives in tmp."""
    from app.core.config import settings

    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "OPENAGENTD_STATE_DIR", str(state))
    return state


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.mark.asyncio
async def test_track_returns_tree_hash(state_dir: Path, workspace: Path) -> None:
    (workspace / "a.txt").write_text("hello")

    snapshot = await snapshot_service.track("sess-1", workspace)

    assert snapshot is not None
    # SHA-1 tree hash → 40 hex chars.
    assert len(snapshot) == 40
    assert snapshot_service.snapshot_dir("sess-1").exists()


@pytest.mark.asyncio
async def test_track_empty_workspace_returns_hash(
    state_dir: Path, workspace: Path
) -> None:
    # ``git write-tree`` against an empty index returns the well-known
    # empty-tree hash. We accept it as a valid baseline snapshot.
    snapshot = await snapshot_service.track("sess-empty", workspace)
    assert snapshot is not None
    assert len(snapshot) == 40


@pytest.mark.asyncio
async def test_track_missing_workspace_returns_none(
    state_dir: Path, tmp_path: Path
) -> None:
    missing = tmp_path / "does-not-exist"
    snapshot = await snapshot_service.track("sess-miss", missing)
    assert snapshot is None


@pytest.mark.asyncio
async def test_restore_replaces_modified_file(state_dir: Path, workspace: Path) -> None:
    file = workspace / "config.txt"
    file.write_text("v1")
    baseline = await snapshot_service.track("sess-mod", workspace)
    assert baseline is not None

    # Simulate an assistant turn that modifies the file.
    file.write_text("v2-changed-by-tool")
    await snapshot_service.track("sess-mod", workspace)  # commit v2 to index

    # Restore baseline.
    ok = await snapshot_service.restore("sess-mod", workspace, baseline)
    assert ok is True
    assert file.read_text() == "v1"


@pytest.mark.asyncio
async def test_restore_deletes_files_added_after_snapshot(
    state_dir: Path, workspace: Path
) -> None:
    (workspace / "keep.txt").write_text("anchor")
    baseline = await snapshot_service.track("sess-add", workspace)
    assert baseline is not None

    # Simulate an assistant turn that adds a new file.
    new_file = workspace / "new_artifact.md"
    new_file.write_text("agent produced this")
    # Track to bring it under the index before restoring back.
    await snapshot_service.track("sess-add", workspace)

    ok = await snapshot_service.restore("sess-add", workspace, baseline)
    assert ok is True
    assert not new_file.exists(), (
        "Newly-added file must be removed when restoring to a snapshot that predates it"
    )
    assert (workspace / "keep.txt").exists()


@pytest.mark.asyncio
async def test_restore_brings_back_deleted_file(
    state_dir: Path, workspace: Path
) -> None:
    target = workspace / "deleted_by_agent.txt"
    target.write_text("important")
    baseline = await snapshot_service.track("sess-del", workspace)
    assert baseline is not None

    # Simulate agent deleting the file.
    target.unlink()

    ok = await snapshot_service.restore("sess-del", workspace, baseline)
    assert ok is True
    assert target.exists()
    assert target.read_text() == "important"


@pytest.mark.asyncio
async def test_restore_no_repo_returns_false(state_dir: Path, workspace: Path) -> None:
    ok = await snapshot_service.restore("sess-unknown", workspace, "0" * 40)
    assert ok is False


@pytest.mark.asyncio
async def test_restore_unknown_hash_returns_false(
    state_dir: Path, workspace: Path
) -> None:
    (workspace / "a.txt").write_text("x")
    await snapshot_service.track("sess-bad-hash", workspace)
    ok = await snapshot_service.restore("sess-bad-hash", workspace, "0" * 40)
    assert ok is False


@pytest.mark.asyncio
async def test_undo_redo_round_trip(state_dir: Path, workspace: Path) -> None:
    """Two-step round trip mirroring the real /undo → /redo flow."""
    file = workspace / "doc.md"
    file.write_text("v1")
    snap_v1 = await snapshot_service.track("rt", workspace)
    assert snap_v1 is not None

    # Assistant turn writes v2.
    file.write_text("v2")
    snap_live = await snapshot_service.track("rt", workspace)  # redo anchor
    assert snap_live is not None

    # /undo → restore v1.
    assert await snapshot_service.restore("rt", workspace, snap_v1) is True
    assert file.read_text() == "v1"

    # /redo → restore live.
    assert await snapshot_service.restore("rt", workspace, snap_live) is True
    assert file.read_text() == "v2"


@pytest.mark.asyncio
async def test_remove_drops_repo(state_dir: Path, workspace: Path) -> None:
    (workspace / "a").write_text("x")
    await snapshot_service.track("doomed", workspace)
    repo = snapshot_service.snapshot_dir("doomed")
    assert repo.exists()

    await snapshot_service.remove("doomed")
    assert not repo.exists()


@pytest.mark.asyncio
async def test_track_skips_oversized_untracked_files(
    state_dir: Path, workspace: Path
) -> None:
    big = workspace / "huge.bin"
    big.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    small = workspace / "small.txt"
    small.write_text("ok")

    snapshot = await snapshot_service.track("sess-big", workspace)
    assert snapshot is not None

    # Mutate then restore — small.txt should round-trip; big stays
    # oversized so it remains untracked across the restore.
    small.write_text("changed")
    big.write_bytes(b"y" * (2 * 1024 * 1024 + 1))

    await snapshot_service.restore("sess-big", workspace, snapshot)
    assert small.read_text() == "ok"
    # The oversized file was never staged, so restore leaves it alone.
    assert big.exists()
