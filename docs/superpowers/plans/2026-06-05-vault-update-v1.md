# Vault Update v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a controlled lead-only `vault_update` tool for updating existing Obsidian vault notes with optimistic hash protection and preserved frontmatter.

**Architecture:** Extend `VaultGatekeeper` as the single in-process writer boundary with typed update intents/results/errors and the existing lock/atomic write path. Extend `vault_read` to optionally expose a SHA-256 update token, then add `vault_update` as a structured tool with Second Brain observability and lead-only loader injection.

**Tech Stack:** Python 3.14, dataclasses, asyncio locks, pathlib, hashlib, PyYAML, Pydantic tool schemas, pytest, OpenTelemetry test spans, ruff, ty.

---

## File Structure

- Modify `app/services/vault_gatekeeper.py`
  - Add `VaultUpdateIntent`, `VaultUpdateResult`, `VaultUpdateConflictError`, `VaultNoteNotFoundError`, `VaultMalformedNoteError`.
  - Add helper `vault_note_sha256(raw: str) -> str`.
  - Add `VaultGatekeeper.update_note(...)` using the existing `_lock`, `validate_vault_note_path`, `split_vault_note_frontmatter`, and `_atomic_write`.

- Modify `app/agent/tools/builtin/vault_read.py`
  - Add `include_update_token: bool = False`.
  - Compute the token from the full raw note content before truncation or frontmatter hiding.
  - Append `[vault_update_token: sha256:<hex>]` only when requested.

- Create `app/agent/tools/builtin/vault_update.py`
  - Expose lead-agent structured update arguments.
  - Inject writer from `_state.metadata["agent_name"]`, fallback `agent:unknown`.
  - Catch typed service errors and return stable LLM-readable messages.
  - Record Second Brain observability outcomes.

- Modify `app/agent/tools/builtin/__init__.py`
  - Export `vault_update`.

- Modify `app/agent/loader.py`
  - Add `vault_update` to the default registry.
  - Auto-inject into lead agents.
  - Skip/dedupe explicit `vault_update` frontmatter entries for both lead and member agents.

- Modify `tests/services/test_vault_gatekeeper.py`
  - Add service-level update tests before implementation code changes.

- Create `tests/agent/tools/test_vault_update_tool.py`
  - Add tool behavior, error message, writer attribution, and observability tests.

- Modify `tests/agent/tools/test_vault_read_tool.py`
  - Add token footer tests and regression for default output.

- Modify `tests/agent/test_loader.py`
  - Add registry/lead/member/dedupe coverage for `vault_update`.

- Modify `.agent/memory/CONTEXT_SNAPSHOT.md`
  - Record implementation status after code and verification pass.

---

## Task 1: Gatekeeper Update Service

**Files:**
- Modify: `tests/services/test_vault_gatekeeper.py`
- Modify: `app/services/vault_gatekeeper.py`

- [ ] **Step 1: Add service update tests**

Append these imports to `tests/services/test_vault_gatekeeper.py`:

```python
from app.services.markdown_text import split_vault_note_frontmatter
```

Extend the existing `from app.services.vault_gatekeeper import (...)` block with:

```python
    VaultMalformedNoteError,
    VaultNoteNotFoundError,
    VaultUpdateConflictError,
    VaultUpdateIntent,
    vault_note_sha256,
```

Add these tests near the existing write-note tests:

```python
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
    parsed = split_vault_note_frontmatter(raw)
    assert parsed.body == "Updated body.\n"
    assert parsed.metadata["title"] == "Agent Memory"
    assert parsed.metadata["type"] == "topic"
    assert parsed.metadata["created_at"] != parsed.metadata["updated_at"]
    assert parsed.metadata["writer"] == "agent:editor"
```

```python
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
    path.write_text(path.read_text(encoding="utf-8") + "\nHuman edit.\n", encoding="utf-8")

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
```

```python
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
```

```python
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
    assert parsed.body == "Existing body.\n\n---\n\nAppended body.\n"
```

```python
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
            VaultUpdateIntent(folder="20-topics", slug="invalid-update", expected_sha256="")
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
```

```python
@pytest.mark.asyncio
async def test_update_note_rejects_missing_and_malformed_notes(_vault_dir: Path) -> None:
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
                expected_sha256=vault_note_sha256(malformed.read_text(encoding="utf-8")),
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
                expected_sha256=vault_note_sha256(no_frontmatter.read_text(encoding="utf-8")),
                replace_body="Body.",
            )
        )
```

```python
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
```

- [ ] **Step 2: Run service tests and verify RED**

Run:

```powershell
uv run pytest tests/services/test_vault_gatekeeper.py --no-cov -q
```

Expected: fail because `VaultUpdateIntent`, update errors, `vault_note_sha256`, and `VaultGatekeeper.update_note` are not defined.

- [ ] **Step 3: Implement gatekeeper update dataclasses, errors, hash helper**

In `app/services/vault_gatekeeper.py`, add imports:

```python
import hashlib
```

Add import from `markdown_text` near the existing imports:

```python
from app.services.markdown_text import (
    VaultFrontmatterParseError,
    split_vault_note_frontmatter,
)
```

Add errors and dataclasses after `VaultIndexUpdateError`:

```python
class VaultUpdateConflictError(ValueError):
    """Raised when the note changed since the caller's read token."""


class VaultNoteNotFoundError(FileNotFoundError):
    """Raised when an update target note does not exist."""


class VaultMalformedNoteError(ValueError):
    """Raised when an existing note cannot be safely parsed for update."""


@dataclass(frozen=True)
class VaultUpdateIntent:
    """Structured update request accepted by the gatekeeper."""

    folder: str
    slug: str
    expected_sha256: str
    replace_body: str | None = None
    append_body: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    source_refs: list[str] | None = None
    relations: list[str] | None = None
    last_summarized_at: str | None = None
    writer: str = "agent"


@dataclass(frozen=True)
class VaultUpdateResult:
    """Result of a committed vault update."""

    path: str
    note_id: str | None
    updated: bool
    content: str
    sha256: str
```

Add a public hash helper near `vault_root`:

```python
def vault_note_sha256(raw: str) -> str:
    """Return the SHA-256 hex digest for a raw vault note string."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Implement `VaultGatekeeper.update_note`**

Add this method to `VaultGatekeeper`:

```python
    async def update_note(self, intent: VaultUpdateIntent) -> VaultUpdateResult:
        """Serialize, validate, and commit an existing note update."""
        async with self._lock:
            return await asyncio.to_thread(self._update_note_sync, intent)
```

Add this sync implementation below `_write_note_sync`:

```python
    def _update_note_sync(self, intent: VaultUpdateIntent) -> VaultUpdateResult:
        _validate_update_intent(intent)
        rel_path = f"{intent.folder}/{intent.slug}.md"
        target = validate_vault_note_path(rel_path, root=self._root)
        if not target.exists():
            raise VaultNoteNotFoundError(f"Vault note not found: {rel_path}")

        try:
            raw = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise VaultWriteError(f"Failed to read vault note: {rel_path}") from exc

        expected = _normalize_expected_sha256(intent.expected_sha256)
        current_hash = vault_note_sha256(raw)
        if current_hash != expected:
            raise VaultUpdateConflictError(
                f"Vault note changed since last read: {rel_path}"
            )

        try:
            parsed = split_vault_note_frontmatter(raw)
        except VaultFrontmatterParseError as exc:
            raise VaultMalformedNoteError(
                f"Vault note frontmatter is malformed: {rel_path}"
            ) from exc
        if not parsed.had_frontmatter:
            raise VaultMalformedNoteError(
                f"Vault note frontmatter is missing: {rel_path}"
            )

        metadata = dict(parsed.metadata)
        body = _updated_body(parsed.body, intent)
        _apply_update_metadata(metadata, intent)
        content = _render_existing_note(metadata=metadata, body=body)

        try:
            _atomic_write(target, content)
        except OSError as exc:
            raise VaultWriteError(f"Failed to update vault note: {rel_path}") from exc

        logger.info("vault_note_updated path={}", rel_path)
        return VaultUpdateResult(
            path=rel_path,
            note_id=str(metadata.get("id")).strip() if metadata.get("id") else None,
            updated=True,
            content=content,
            sha256=vault_note_sha256(content),
        )
```

- [ ] **Step 5: Implement update validation/render helpers**

Add these helpers near `_validate_intent`:

```python
def _validate_update_intent(intent: VaultUpdateIntent) -> None:
    if intent.folder not in VAULT_FOLDERS:
        allowed = ", ".join(sorted(VAULT_FOLDERS))
        raise VaultPathError(
            f"Vault folder must be one of [{allowed}]: {intent.folder!r}"
        )
    if not _SLUG_RE.match(intent.slug):
        raise VaultPathError(f"Vault slug is invalid: {intent.slug!r}")
    _validate_windows_safe_stem(intent.slug)
    _normalize_expected_sha256(intent.expected_sha256)
    if intent.replace_body is not None and intent.append_body is not None:
        raise ValueError("Provide only one of replace_body and append_body.")
    if intent.replace_body is not None and not intent.replace_body.strip():
        raise ValueError("Vault update body must not be empty.")
    if intent.append_body is not None and not intent.append_body.strip():
        raise ValueError("Vault update body must not be empty.")
    metadata_requested = any(
        value is not None
        for value in (
            intent.status,
            intent.tags,
            intent.source_refs,
            intent.relations,
            intent.last_summarized_at,
        )
    )
    if intent.replace_body is None and intent.append_body is None and not metadata_requested:
        raise ValueError("No vault update changes requested.")


def _normalize_expected_sha256(value: str) -> str:
    token = str(value).strip()
    if token.startswith("sha256:"):
        token = token.removeprefix("sha256:").strip()
    if len(token) != 64 or any(char not in "0123456789abcdefABCDEF" for char in token):
        raise ValueError("expected_sha256 must be a SHA-256 hex digest.")
    return token.lower()


def _updated_body(existing_body: str, intent: VaultUpdateIntent) -> str:
    if intent.replace_body is not None:
        return intent.replace_body.strip() + "\n"
    if intent.append_body is not None:
        existing = existing_body.rstrip()
        appended = intent.append_body.strip()
        return f"{existing}\n\n---\n\n{appended}\n"
    return existing_body


def _apply_update_metadata(metadata: dict[str, Any], intent: VaultUpdateIntent) -> None:
    if intent.status is not None:
        metadata["status"] = intent.status.strip()
    if intent.tags is not None:
        metadata["tags"] = _normalize_list(intent.tags)
    if intent.source_refs is not None:
        metadata["source_refs"] = _normalize_list(intent.source_refs)
    if intent.relations is not None:
        metadata["relations"] = _normalize_list(intent.relations)
    if intent.last_summarized_at is not None:
        value = intent.last_summarized_at.strip()
        metadata["last_summarized_at"] = value or None
    metadata["updated_at"] = datetime.now(UTC).isoformat()
    metadata["writer"] = intent.writer.strip() or "agent"


def _render_existing_note(*, metadata: dict[str, Any], body: str) -> str:
    yaml_block = yaml.safe_dump(
        metadata,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    return f"---\n{yaml_block}\n---\n{body}"
```

- [ ] **Step 6: Run service tests and verify GREEN**

Run:

```powershell
uv run pytest tests/services/test_vault_gatekeeper.py --no-cov -q
```

Expected: all vault gatekeeper tests pass.

---

## Task 2: `vault_read` Update Token

**Files:**
- Modify: `tests/agent/tools/test_vault_read_tool.py`
- Modify: `app/agent/tools/builtin/vault_read.py`

- [ ] **Step 1: Add token tests**

Modify `tests/agent/tools/test_vault_read_tool.py` imports:

```python
from app.services.vault_gatekeeper import VAULT_FOLDERS, vault_note_sha256
```

Add these tests:

```python
@pytest.mark.asyncio
async def test_vault_read_can_include_update_token(_vault_dir: Path) -> None:
    raw = "---\ntitle: Token Note\n---\nBody.\n"
    (_vault_dir / "20-topics" / "token-note.md").write_text(raw, encoding="utf-8")

    result = await vault_read.arun(
        folder="20-topics",
        slug="token-note",
        include_update_token=True,
    )

    assert result.startswith(raw)
    assert result.endswith(
        f"\n\n[vault_update_token: sha256:{vault_note_sha256(raw)}]"
    )
```

```python
@pytest.mark.asyncio
async def test_vault_read_default_does_not_include_update_token(_vault_dir: Path) -> None:
    raw = "---\ntitle: Raw Note\n---\nBody.\n"
    (_vault_dir / "20-topics" / "raw-note.md").write_text(raw, encoding="utf-8")

    result = await vault_read.arun(folder="20-topics", slug="raw-note")

    assert result == raw
    assert "vault_update_token" not in result
```

```python
@pytest.mark.asyncio
async def test_vault_read_update_token_uses_full_raw_note_when_truncated(
    _vault_dir: Path,
) -> None:
    raw = "---\ntitle: Long Note\n---\n" + ("x" * 2000)
    (_vault_dir / "20-topics" / "long-note.md").write_text(raw, encoding="utf-8")

    result = await vault_read.arun(
        folder="20-topics",
        slug="long-note",
        max_chars=1000,
        include_update_token=True,
    )

    assert "[truncated at 1000 characters]" in result
    assert result.endswith(
        f"\n\n[vault_update_token: sha256:{vault_note_sha256(raw)}]"
    )
```

- [ ] **Step 2: Run token tests and verify RED**

Run:

```powershell
uv run pytest tests/agent/tools/test_vault_read_tool.py::test_vault_read_can_include_update_token tests/agent/tools/test_vault_read_tool.py::test_vault_read_default_does_not_include_update_token tests/agent/tools/test_vault_read_tool.py::test_vault_read_update_token_uses_full_raw_note_when_truncated --no-cov -q
```

Expected: fail because `vault_note_sha256` is now available from Task 1 but `vault_read` does not accept `include_update_token`.

- [ ] **Step 3: Implement `include_update_token`**

In `app/agent/tools/builtin/vault_read.py`, import:

```python
from app.services.vault_gatekeeper import vault_note_sha256
```

Add the tool parameter after `include_frontmatter`:

```python
    include_update_token: Annotated[
        bool,
        Field(description="Whether to append a sha256 update token footer."),
    ] = False,
```

Add this helper:

```python
def _with_update_token(content: str, raw: str, include_update_token: bool) -> str:
    if not include_update_token:
        return content
    return f"{content}\n\n[vault_update_token: sha256:{vault_note_sha256(raw)}]"
```

Change the result construction:

```python
    result = _truncate(content, max_chars_clamped)
    result = _with_update_token(result, raw, include_update_token)
```

Add attr:

```python
            "vault.include_update_token": include_update_token,
```

- [ ] **Step 4: Run `vault_read` tests and verify GREEN**

Run:

```powershell
uv run pytest tests/agent/tools/test_vault_read_tool.py --no-cov -q
```

Expected: all `vault_read` tests pass.

---

## Task 3: `vault_update` Tool

**Files:**
- Create: `tests/agent/tools/test_vault_update_tool.py`
- Create: `app/agent/tools/builtin/vault_update.py`

- [ ] **Step 1: Add tool tests**

Create `tests/agent/tools/test_vault_update_tool.py`:

```python
"""Tests for the vault_update built-in tool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace.status import StatusCode

from app.agent.tools.builtin.vault_update import vault_update
from app.services import vault_gatekeeper
from app.services.markdown_text import split_vault_note_frontmatter
from app.services.vault_gatekeeper import (
    VAULT_FOLDERS,
    VaultMalformedNoteError,
    VaultNoteNotFoundError,
    VaultPathError,
    VaultUpdateConflictError,
    VaultUpdateResult,
    VaultWriteError,
    VaultWriteIntent,
    get_vault_gatekeeper,
    vault_note_sha256,
)


@dataclass
class MockState:
    metadata: dict[str, Any]


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
    return target


@pytest.mark.asyncio
async def test_vault_update_success_uses_injected_writer(_vault_dir: Path) -> None:
    gatekeeper = get_vault_gatekeeper()
    await gatekeeper.write_note(
        VaultWriteIntent(
            folder="20-topics",
            slug="agent-memory",
            title="Agent Memory",
            note_type="topic",
            body="Original.",
            writer="agent:first",
        )
    )
    path = _vault_dir / "20-topics" / "agent-memory.md"

    result = await vault_update.arun(
        folder="20-topics",
        slug="agent-memory",
        expected_sha256=vault_note_sha256(path.read_text(encoding="utf-8")),
        replace_body="Updated.",
        _injected={"_state": MockState(metadata={"agent_name": "researcher"})},
    )

    assert result == "Vault note updated at 20-topics/agent-memory.md"
    parsed = split_vault_note_frontmatter(path.read_text(encoding="utf-8"))
    assert parsed.body == "Updated.\n"
    assert parsed.metadata["writer"] == "agent:researcher"


@pytest.mark.asyncio
async def test_vault_update_falls_back_to_unknown_writer(_vault_dir: Path) -> None:
    gatekeeper = get_vault_gatekeeper()
    await gatekeeper.write_note(
        VaultWriteIntent(
            folder="20-topics",
            slug="unknown-writer",
            title="Unknown Writer",
            note_type="topic",
            body="Original.",
        )
    )
    path = _vault_dir / "20-topics" / "unknown-writer.md"

    await vault_update.arun(
        folder="20-topics",
        slug="unknown-writer",
        expected_sha256=vault_note_sha256(path.read_text(encoding="utf-8")),
        append_body="Append.",
        _injected={"_state": MockState(metadata={})},
    )

    parsed = split_vault_note_frontmatter(path.read_text(encoding="utf-8"))
    assert parsed.metadata["writer"] == "agent:unknown"


@pytest.mark.asyncio
async def test_vault_update_error_messages_are_specific() -> None:
    mock_gatekeeper = AsyncMock()
    cases = [
        (
            VaultUpdateConflictError("changed"),
            "Update conflict at vault/20-topics/example.md",
        ),
        (
            VaultNoteNotFoundError("missing"),
            "Note not found at vault/20-topics/example.md",
        ),
        (
            VaultMalformedNoteError("malformed"),
            "Cannot update vault/20-topics/example.md",
        ),
        (
            VaultPathError("bad path"),
            "bad path",
        ),
        (
            VaultWriteError("write failed"),
            "Failed to update vault note at vault/20-topics/example.md",
        ),
        (
            ValueError("No vault update changes requested."),
            "Invalid vault update request: No vault update changes requested.",
        ),
    ]

    for exc, expected in cases:
        mock_gatekeeper.update_note.side_effect = exc
        with patch(
            "app.agent.tools.builtin.vault_update.get_vault_gatekeeper",
            return_value=mock_gatekeeper,
        ):
            result = await vault_update.arun(
                folder="20-topics",
                slug="example",
                expected_sha256="sha256:" + ("0" * 64),
                replace_body="Updated.",
            )
        assert expected in result


@pytest.mark.asyncio
async def test_vault_update_records_observability_success() -> None:
    mock_gatekeeper = AsyncMock()
    mock_gatekeeper.update_note.return_value = VaultUpdateResult(
        path="20-topics/example.md",
        note_id="example",
        updated=True,
        content="---\n---\nBody.\n",
        sha256="a" * 64,
    )
    tracer, exporter = _tracer_with_exporter()

    with (
        patch(
            "app.agent.tools.builtin.vault_update.get_vault_gatekeeper",
            return_value=mock_gatekeeper,
        ),
        tracer.start_as_current_span("execute_tool vault_update"),
    ):
        result = await vault_update.arun(
            folder="20-topics",
            slug="example",
            expected_sha256="sha256:" + ("0" * 64),
            replace_body="Updated.",
            tags=["one", "two"],
        )

    assert result == "Vault note updated at 20-topics/example.md"
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.UNSET
    assert span.attributes["openagentd.second_brain.tool"] == "vault_update"
    assert span.attributes["openagentd.second_brain.outcome"] == "updated"
    assert span.attributes["vault.path"] == "20-topics/example.md"
    assert span.attributes["vault.replace_body_length"] == len("Updated.")
    assert span.attributes["vault.metadata_fields_count"] == 1
    assert "vault.expected_sha256" not in span.attributes
    assert "vault.tags" not in span.attributes


@pytest.mark.asyncio
async def test_vault_update_records_observability_error() -> None:
    mock_gatekeeper = AsyncMock()
    mock_gatekeeper.update_note.side_effect = VaultUpdateConflictError("changed")
    tracer, exporter = _tracer_with_exporter()

    with (
        patch(
            "app.agent.tools.builtin.vault_update.get_vault_gatekeeper",
            return_value=mock_gatekeeper,
        ),
        tracer.start_as_current_span("execute_tool vault_update"),
    ):
        await vault_update.arun(
            folder="20-topics",
            slug="example",
            expected_sha256="sha256:" + ("0" * 64),
            append_body="Append.",
        )

    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["openagentd.second_brain.outcome"] == "conflict"


def _tracer_with_exporter():
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter
```

- [ ] **Step 2: Run tool tests and verify RED**

Run:

```powershell
uv run pytest tests/agent/tools/test_vault_update_tool.py --no-cov -q
```

Expected: fail because `app.agent.tools.builtin.vault_update` does not exist.

- [ ] **Step 3: Implement `vault_update` tool**

Create `app/agent/tools/builtin/vault_update.py`:

```python
"""vault_update tool -- structured updates for existing Obsidian vault notes."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import Field

from app.agent.tools.builtin._observability import (
    SECOND_BRAIN_ERROR,
    SECOND_BRAIN_OK,
    record_second_brain_tool_observation,
)
from app.agent.tools.registry import InjectedArg, Tool
from app.services.vault_gatekeeper import (
    VaultMalformedNoteError,
    VaultNoteNotFoundError,
    VaultPathError,
    VaultUpdateConflictError,
    VaultUpdateIntent,
    VaultWriteError,
    get_vault_gatekeeper,
)


def _writer_from_state(state: Any) -> str:
    if state is None:
        return "agent:unknown"
    metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, dict):
        return "agent:unknown"
    agent_name = metadata.get("agent_name")
    if not isinstance(agent_name, str) or not agent_name.strip():
        return "agent:unknown"
    return f"agent:{agent_name.strip()}"


async def _vault_update(
    folder: Annotated[str, Field(description="Standard vault folder.")],
    slug: Annotated[str, Field(description="Note filename stem without .md suffix.")],
    expected_sha256: Annotated[
        str,
        Field(description="SHA-256 update token from vault_read(include_update_token=True)."),
    ],
    replace_body: Annotated[
        str | None,
        Field(description="Replace the Markdown body. Mutually exclusive with append_body."),
    ] = None,
    append_body: Annotated[
        str | None,
        Field(description="Append Markdown to the body. Mutually exclusive with replace_body."),
    ] = None,
    status: Annotated[str | None, Field(description="Optional frontmatter status.")] = None,
    tags: Annotated[
        list[str] | None,
        Field(description="Optional replacement frontmatter tags."),
    ] = None,
    source_refs: Annotated[
        list[str] | None,
        Field(description="Optional replacement source references."),
    ] = None,
    relations: Annotated[
        list[str] | None,
        Field(description="Optional replacement relations."),
    ] = None,
    last_summarized_at: Annotated[
        str | None,
        Field(description="Optional last_summarized_at frontmatter value."),
    ] = None,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Update one existing Obsidian vault note through the gatekeeper."""
    start = time.perf_counter()
    attrs = _attrs(folder, slug, replace_body, append_body, status, tags, source_refs, relations, last_summarized_at)
    try:
        result = await get_vault_gatekeeper().update_note(
            VaultUpdateIntent(
                folder=folder,
                slug=slug,
                expected_sha256=expected_sha256,
                replace_body=replace_body,
                append_body=append_body,
                status=status,
                tags=tags,
                source_refs=source_refs,
                relations=relations,
                last_summarized_at=last_summarized_at,
                writer=_writer_from_state(_state),
            )
        )
    except VaultUpdateConflictError:
        _record("conflict", SECOND_BRAIN_ERROR, start, attrs)
        return (
            f"Update conflict at vault/{folder}/{slug}.md: note changed since last "
            "read. Read it again and retry with the new update token."
        )
    except VaultNoteNotFoundError:
        _record("not_found", SECOND_BRAIN_ERROR, start, attrs)
        return f"Note not found at vault/{folder}/{slug}.md"
    except VaultMalformedNoteError:
        _record("malformed_frontmatter", SECOND_BRAIN_ERROR, start, attrs)
        return (
            f"Cannot update vault/{folder}/{slug}.md: note frontmatter is missing "
            "or malformed. Run ingest/reconcile first."
        )
    except VaultPathError as exc:
        _record("invalid_path", SECOND_BRAIN_ERROR, start, attrs)
        return str(exc)
    except VaultWriteError:
        _record("write_error", SECOND_BRAIN_ERROR, start, attrs)
        return f"Failed to update vault note at vault/{folder}/{slug}.md"
    except ValueError as exc:
        _record("invalid_request", SECOND_BRAIN_ERROR, start, attrs)
        return f"Invalid vault update request: {exc}"

    _record("updated", SECOND_BRAIN_OK, start, {**attrs, "vault.path": result.path})
    return f"Vault note updated at {result.path}"


def _attrs(
    folder: str,
    slug: str,
    replace_body: str | None,
    append_body: str | None,
    status: str | None,
    tags: list[str] | None,
    source_refs: list[str] | None,
    relations: list[str] | None,
    last_summarized_at: str | None,
) -> dict[str, object]:
    metadata_fields_count = sum(
        value is not None
        for value in (status, tags, source_refs, relations, last_summarized_at)
    )
    return {
        "vault.folder": folder,
        "vault.path": f"{folder}/{slug}.md",
        "vault.replace_body_length": len(replace_body or ""),
        "vault.append_body_length": len(append_body or ""),
        "vault.metadata_fields_count": metadata_fields_count,
        "vault.has_replace_body": replace_body is not None,
        "vault.has_append_body": append_body is not None,
    }


def _record(
    outcome: str,
    status: str,
    start: float,
    attributes: Mapping[str, object],
) -> None:
    record_second_brain_tool_observation(
        tool="vault_update",
        outcome=outcome,
        status=status,
        duration_seconds=time.perf_counter() - start,
        attributes=attributes,
    )


vault_update = Tool(
    _vault_update,
    name="vault_update",
    description=(
        "Update an existing Obsidian vault note through the gatekeeper using a "
        "sha256 update token from vault_read. Supports structured body and "
        "allowlisted frontmatter updates only."
    ),
)
```

Run format after this step because some function signatures are long:

```powershell
uv run ruff format app/agent/tools/builtin/vault_update.py tests/agent/tools/test_vault_update_tool.py
```

- [ ] **Step 4: Run tool tests and verify GREEN**

Run:

```powershell
uv run pytest tests/agent/tools/test_vault_update_tool.py --no-cov -q
```

Expected: all `vault_update` tool tests pass.

---

## Task 4: Registry And Lead-Only Injection

**Files:**
- Modify: `app/agent/tools/builtin/__init__.py`
- Modify: `app/agent/loader.py`
- Modify: `tests/agent/test_loader.py`

- [ ] **Step 1: Add loader and registry tests**

In `tests/agent/test_loader.py`, update existing expected sets and assertions:

Add `"vault_update"` to the expected registry set in `test_default_tool_registry_contains_core_tools`.

In `test_note_tool_auto_injected_into_lead`, add:

```python
    assert "vault_update" in agent._tools
    assert agent._tools["vault_update"].name == "vault_update"
```

In `test_note_tool_not_injected_into_member`, add:

```python
    assert "vault_update" not in agent._tools
```

In `test_note_in_frontmatter_tools_silently_skipped_for_lead`, add `"vault_update"` to the `tools=[...]` list and assertions:

```python
    assert "vault_update" in agent._tools
    assert list(agent._tools.keys()).count("vault_update") == 1
```

In `test_note_in_frontmatter_tools_silently_skipped_for_member`, add `"vault_update"` to the `tools=[...]` list and assertion:

```python
    assert "vault_update" not in agent._tools
```

In `test_note_tools_injected_into_lead_only_integration`, add:

```python
    assert "vault_update" in lead_tool_names
    assert "vault_update" not in worker_tool_names
```

In `test_note_and_todo_both_injected_into_lead`, add:

```python
    assert "vault_update" in agent._tools
```

In `test_note_deduped_with_other_injected_tools`, add `"vault_update"` to the `tools=[...]` list and assertion:

```python
    assert list(agent._tools.keys()).count("vault_update") == 1
```

- [ ] **Step 2: Run loader tests and verify RED**

Run:

```powershell
uv run pytest tests/agent/test_loader.py --no-cov -q
```

Expected: fail because `vault_update` is not registered or injected yet.

- [ ] **Step 3: Register builtin export**

In `app/agent/tools/builtin/__init__.py`, add:

```python
from .vault_update import vault_update
```

Add `"vault_update"` to `__all__`.

- [ ] **Step 4: Register and inject in loader**

In `app/agent/loader.py`, import `vault_update` in `_default_tool_registry`:

```python
        vault_update,
```

Add registry entry:

```python
        "vault_update": vault_update,
```

In `_build_agent`, import default tool for lead:

```python
        from app.agent.tools.builtin.vault_update import (
            vault_update as _vault_update_tool,
        )
```

Resolve from registry:

```python
        _vault_update = tool_registry.get("vault_update", _vault_update_tool)
```

Append to lead tools after `_vault_search`:

```python
            _vault_update,
```

Add `"vault_update"` to the lead-only skip tuple used when processing `cfg.tools`.

- [ ] **Step 5: Run loader tests and verify GREEN**

Run:

```powershell
uv run pytest tests/agent/test_loader.py --no-cov -q
```

Expected: loader tests pass.

---

## Task 5: Regression, Snapshot, And Commit

**Files:**
- Modify: `.agent/memory/CONTEXT_SNAPSHOT.md`
- All implementation files from prior tasks.

- [ ] **Step 1: Run full targeted regression**

Run:

```powershell
uv run pytest tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_update_tool.py tests/agent/tools/test_vault_read_tool.py --no-cov -q
uv run pytest tests/agent/tools/test_vault_write_tool.py tests/agent/tools/test_vault_search_tool.py tests/agent/test_loader.py --no-cov -q
uv run pytest tests/services/test_observability_service.py tests/api/routes/test_observability_route.py --no-cov -q
```

Expected: all tests pass.

- [ ] **Step 2: Run lint, format, and type checks**

Run:

```powershell
uv run ruff check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_update.py app/agent/tools/builtin/vault_read.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_update_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/test_loader.py
uv run ruff format --check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_update.py app/agent/tools/builtin/vault_read.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_update_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/test_loader.py
uv run ty check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_update.py app/agent/tools/builtin/vault_read.py app/agent/loader.py
```

Expected: all checks pass. If `ruff format --check` fails, run the same command without `--check`, then rerun all checks.

- [ ] **Step 3: Update snapshot**

In `.agent/memory/CONTEXT_SNAPSHOT.md`, add:

```markdown
- Vault Update v1 is now implemented and verified:
  - `VaultGatekeeper.update_note(...)` updates existing notes under the existing gatekeeper lock with atomic writes and optimistic SHA-256 conflict detection.
  - `vault_read(include_update_token=True)` returns a `sha256` token for the full raw note content without changing default read output.
  - `vault_update` is lead-only and supports structured body replacement, body append, and allowlisted metadata updates while preserving custom frontmatter.
  - `title`, `type`, `id`, `created_at`, `folder`, and `slug` remain read-only in v1; no index update, API/UI, batch, delete, rename, move, Hermes direct write, or approval queue integration was added.
```

Update `Next Implementation Steps` to mark Vault Update v1 done and leave Hermes skill drafting as the likely next candidate.

- [ ] **Step 4: Commit implementation**

Run:

```powershell
git status --short
git add app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_update.py app/agent/tools/builtin/vault_read.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_update_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/test_loader.py .agent/memory/CONTEXT_SNAPSHOT.md
git commit -m "feat: add Vault Update tool"
```

Expected: commit succeeds with only Vault Update v1 implementation, tests, and snapshot changes.

---

## Final Verification Checklist

- [ ] `uv run pytest tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_update_tool.py tests/agent/tools/test_vault_read_tool.py --no-cov -q`
- [ ] `uv run pytest tests/agent/tools/test_vault_write_tool.py tests/agent/tools/test_vault_search_tool.py tests/agent/test_loader.py --no-cov -q`
- [ ] `uv run pytest tests/services/test_observability_service.py tests/api/routes/test_observability_route.py --no-cov -q`
- [ ] `uv run ruff check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_update.py app/agent/tools/builtin/vault_read.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_update_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/test_loader.py`
- [ ] `uv run ruff format --check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_update.py app/agent/tools/builtin/vault_read.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_update_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/test_loader.py`
- [ ] `uv run ty check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_update.py app/agent/tools/builtin/vault_read.py app/agent/loader.py`
- [ ] `git status --short` is clean after commit.

## Review Handoff

After implementation, send the diff to an architecture reviewer with this focus:

- Lost-update semantics and hash normalization.
- Frontmatter preservation and YAML rendering.
- Read-only `title/type/id/created_at/folder/slug` boundary.
- No hidden raw overwrite path.
- No index update path in v1.
- No Hermes direct write coupling.
- Observability privacy.
- Test reliability for concurrent update conflict.
