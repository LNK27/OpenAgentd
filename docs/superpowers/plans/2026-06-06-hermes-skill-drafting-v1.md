# Hermes Skill Drafting v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lead-only Hermes skill drafting flow where Hermes proposes drafts, OpenAgentd queues them for review, and approval creates a new `SKILL.md` without overwrite, auto-install, UI, API, or DB persistence.

**Architecture:** Keep skill drafting separate from the accepted vault Hermes approval queue. Extend `app/services/hermes.py` for the `/v1/skill-drafts` contract, add `app/services/hermes_skill_drafting.py` for the in-memory review queue/write boundary, and expose four lead-only builtin tools through `app/agent/tools/builtin/hermes_skill.py`. Harden shared runtime logging and skill create semantics before adding the new write-capable approval tool.

**Tech Stack:** Python 3.14, FastAPI-adjacent services, Pydantic tool schemas, `httpx`, `yaml.safe_dump`, Loguru, OpenTelemetry, Prometheus client, pytest, Ruff, ty.

---

## File Map

- Modify `app/services/agent_fs.py`
  - Add a public skill-name validator and a create-only atomic write path for `write_skill(..., create=True)`.
  - Preserve existing agent write behavior.
- Modify `tests/services/test_agent_fs.py`
  - Add tests for skill name validation and create-only no-overwrite hardening.
- Modify `app/agent/agent_loop/tool_executor.py`
  - Redact raw Hermes skill tool arguments and debug result previews in runtime logs.
- Modify `app/agent/hooks/stream_publisher.py`
  - Redact ToolStart arguments for Hermes skill tools before SSE stream storage/replay.
- Add `tests/agent/test_hermes_skill_redaction.py`
  - Verify log redaction and ToolStart stream redaction while preserving ToolEnd review output.
- Modify `app/services/hermes.py`
  - Add `HermesSkillDraftRequest`, `HermesSkillDraftProposal`, `HermesSkillDraftResult`, client protocol method, HTTP `/v1/skill-drafts`, and normalization.
- Modify `tests/services/test_hermes.py`
  - Add skill draft service/normalization tests next to existing Hermes tests.
- Add `app/services/hermes_skill_drafting.py`
  - Implement in-memory, session-scoped, max-50-total queue and approve/reject/list flow.
- Add `tests/services/test_hermes_skill_drafting.py`
  - Cover queue limits, session scoping, approval write path, rejection, terminal status, and no Hermes calls on approve.
- Add `app/agent/tools/builtin/hermes_skill.py`
  - Implement `hermes_skill_draft`, `hermes_skill_pending_list`, `hermes_skill_pending_approve`, and `hermes_skill_pending_reject`.
- Add `tests/agent/tools/test_hermes_skill_tools.py`
  - Cover tool output, error messages, observability outcomes, and privacy attributes.
- Modify `app/agent/tools/builtin/__init__.py`
  - Export the four new builtin tools.
- Modify `app/agent/loader.py`
  - Register and auto-inject the tools for lead agents only; warn and skip member frontmatter attempts.
- Modify `tests/agent/test_loader.py`
  - Add lead-only injection/member exclusion/warning/dedup regression tests.
- Modify `.agent/memory/CONTEXT_SNAPSHOT.md`
  - Record implementation status and verification results before final completion.

---

## Task 1: Harden `agent_fs` Skill Create Semantics

**Files:**
- Modify: `app/services/agent_fs.py`
- Test: `tests/services/test_agent_fs.py`

- [ ] **Step 1: Write failing tests for public validation and create-only no-overwrite**

Add tests like these to `tests/services/test_agent_fs.py`:

```python
def test_validate_skill_name_accepts_agent_fs_policy() -> None:
    from app.services.agent_fs import validate_skill_name

    assert validate_skill_name("skill-name_1.2") == "skill-name_1.2"


def test_validate_skill_name_rejects_invalid_values() -> None:
    from app.services.agent_fs import AgentFsPathError, validate_skill_name

    for value in ("", "../bad", "-bad", "bad/name", "x" * 65):
        with pytest.raises(AgentFsPathError):
            validate_skill_name(value)


def test_write_skill_create_does_not_overwrite_existing_skill(monkeypatch, tmp_path):
    from app.services import agent_fs
    from app.services.agent_fs import AgentFsConflictError

    monkeypatch.setattr(agent_fs.settings, "SKILLS_DIR", str(tmp_path))
    first = agent_fs.write_skill("draft-skill", "first", create=True)

    with pytest.raises(AgentFsConflictError):
        agent_fs.write_skill("draft-skill", "second", create=True)

    assert Path(first.path).read_text(encoding="utf-8") == "first"
```

- [ ] **Step 2: Run the tests and verify they fail for the new public validator if absent**

Run:

```powershell
uv run pytest tests/services/test_agent_fs.py::test_validate_skill_name_accepts_agent_fs_policy tests/services/test_agent_fs.py::test_validate_skill_name_rejects_invalid_values tests/services/test_agent_fs.py::test_write_skill_create_does_not_overwrite_existing_skill --no-cov -q
```

Expected:

```text
FAILED ... cannot import name 'validate_skill_name'
```

- [ ] **Step 3: Implement public validation and create-only atomic publish**

In `app/services/agent_fs.py`, add `import os`, expose `validate_skill_name`, and split atomic write into overwrite/create paths:

```python
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
```

```python
def validate_skill_name(name: str) -> str:
    """Public skill-name validator shared by skill write flows."""
    return _validate_name(name)
```

```python
def _write_temp_file(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    return tmp_path


def _atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* atomically, allowing overwrite."""
    tmp_path = _write_temp_file(path, content)
    tmp_path.replace(path)


def _atomic_create(path: Path, content: str) -> None:
    """Create *path* atomically and fail if the destination already exists."""
    tmp_path = _write_temp_file(path, content)
    try:
        os.link(tmp_path, path)
    except FileExistsError as exc:
        raise AgentFsConflictError(f"File already exists: {path.name}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
```

Update `write_skill`:

```python
def write_skill(name: str, content: str, *, create: bool) -> SkillFileRecord:
    file = _skill_file(name)
    if create:
        _atomic_create(file, content)
    else:
        _atomic_write(file, content)
    logger.info("skill_fs_write name={} bytes={}", name, len(content))
    return SkillFileRecord(name=name, path=str(file), content=content)
```

Keep `write_agent` on the existing `file.exists()` + `_atomic_write(...)` behavior because this phase only hardens skill create semantics.

- [ ] **Step 4: Run targeted agent_fs tests**

Run:

```powershell
uv run pytest tests/services/test_agent_fs.py --no-cov -q
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add app/services/agent_fs.py tests/services/test_agent_fs.py
git commit -m "test: harden skill create semantics"
```

---

## Task 2: Redact Runtime Logs And ToolStart Stream Arguments

**Files:**
- Modify: `app/agent/agent_loop/tool_executor.py`
- Modify: `app/agent/hooks/stream_publisher.py`
- Test: `tests/agent/test_hermes_skill_redaction.py`

- [ ] **Step 1: Write failing tests for log and stream redaction**

Create `tests/agent/test_hermes_skill_redaction.py`:

```python
from __future__ import annotations

import json

from app.agent.agent_loop.tool_executor import (
    _redact_tool_args_for_log,
    _redact_tool_result_for_log,
)
from app.agent.hooks.stream_publisher import _redact_tool_start_arguments


def test_hermes_skill_draft_args_are_redacted_for_logs() -> None:
    raw = json.dumps(
        {
            "task": "draft secret workflow",
            "context": "private operational context",
            "max_drafts": 2,
        }
    )

    redacted = _redact_tool_args_for_log("hermes_skill_draft", raw)

    assert "draft secret workflow" not in redacted
    assert "private operational context" not in redacted
    assert '"task": "<redacted>"' in redacted
    assert '"context": "<redacted>"' in redacted
    assert '"max_drafts": 2' in redacted


def test_hermes_skill_tool_result_preview_is_redacted_for_logs() -> None:
    result = '{"pending_id":"abc","body_preview":"private draft body"}'

    redacted = _redact_tool_result_for_log("hermes_skill_draft", result)

    assert "abc" not in redacted
    assert "private draft body" not in redacted
    assert redacted == "<redacted:hermes_skill_tool_result>"


def test_hermes_skill_draft_tool_start_stream_arguments_are_redacted() -> None:
    raw = json.dumps(
        {
            "task": "draft secret workflow",
            "context": "private operational context",
            "max_drafts": 2,
        }
    )

    redacted = _redact_tool_start_arguments("hermes_skill_draft", raw)

    assert "draft secret workflow" not in redacted
    assert "private operational context" not in redacted
    assert '"task": "<redacted>"' in redacted
    assert '"context": "<redacted>"' in redacted
    assert '"max_drafts": 2' in redacted
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
uv run pytest tests/agent/test_hermes_skill_redaction.py --no-cov -q
```

Expected:

```text
FAILED ... cannot import name '_redact_tool_args_for_log'
```

- [ ] **Step 3: Implement runtime log redaction helpers**

In `app/agent/agent_loop/tool_executor.py`, add helpers near `sanitize_error`:

```python
SENSITIVE_HERMES_SKILL_TOOLS = {
    "hermes_skill_draft",
    "hermes_skill_pending_list",
    "hermes_skill_pending_approve",
    "hermes_skill_pending_reject",
}

_HERMES_SKILL_ARG_REDACTIONS = {
    "task",
    "context",
    "body",
    "body_preview",
    "description",
    "reason",
    "pending_id",
}


def _redact_tool_args_for_log(tool_name: str, raw_args: str | None) -> str:
    if not raw_args:
        return "{}"
    if tool_name not in SENSITIVE_HERMES_SKILL_TOOLS:
        return raw_args[:500]
    try:
        payload = json.loads(raw_args)
    except (json.JSONDecodeError, ValueError):
        return "<redacted:invalid_json_args>"
    if not isinstance(payload, dict):
        return "<redacted:non_object_args>"
    redacted = {
        key: "<redacted>" if key in _HERMES_SKILL_ARG_REDACTIONS else value
        for key, value in payload.items()
    }
    return json.dumps(redacted, ensure_ascii=False)[:500]


def _redact_tool_result_for_log(tool_name: str, result: str) -> str:
    if tool_name in SENSITIVE_HERMES_SKILL_TOOLS:
        return "<redacted:hermes_skill_tool_result>"
    return result[:1000] if len(result) > 1000 else result
```

Replace the `tool_start` args expression:

```python
_redact_tool_args_for_log(tc.function.name, tc.function.arguments)
```

Replace debug result preview:

```python
logger.debug(
    "tool_result_preview agent={} tool={} result={}",
    agent_name,
    tc.function.name,
    _redact_tool_result_for_log(tc.function.name, result),
)
```

- [ ] **Step 4: Implement ToolStart stream redaction helper**

In `app/agent/hooks/stream_publisher.py`, add helpers above `StreamPublisherHook`:

```python
_HERMES_SKILL_STREAM_ARG_REDACTIONS = {
    "task",
    "context",
    "body",
    "body_preview",
    "description",
    "reason",
    "pending_id",
}


def _redact_tool_start_arguments(tool_name: str, arguments: str | None) -> str | None:
    if arguments is None:
        return None
    if tool_name not in {
        "hermes_skill_draft",
        "hermes_skill_pending_list",
        "hermes_skill_pending_approve",
        "hermes_skill_pending_reject",
    }:
        return arguments
    import json as _json

    try:
        payload = _json.loads(arguments or "{}")
    except Exception:
        return "<redacted:invalid_json_args>"
    if not isinstance(payload, dict):
        return "<redacted:non_object_args>"
    redacted = {
        key: "<redacted>" if key in _HERMES_SKILL_STREAM_ARG_REDACTIONS else value
        for key, value in payload.items()
    }
    return _json.dumps(redacted, ensure_ascii=False)
```

Replace `ToolStartEvent(arguments=...)` with:

```python
arguments=_redact_tool_start_arguments(
    fn_name,
    tool_call.function.arguments if tool_call.function else None,
),
```

Do not redact ToolEnd result; it is the lead review surface and remains covered by the tool-level bounded `body_preview`.

- [ ] **Step 5: Run redaction tests**

Run:

```powershell
uv run pytest tests/agent/test_hermes_skill_redaction.py --no-cov -q
```

Expected:

```text
3 passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add app/agent/agent_loop/tool_executor.py app/agent/hooks/stream_publisher.py tests/agent/test_hermes_skill_redaction.py
git commit -m "feat: redact Hermes skill tool runtime logs"
```

---

## Task 3: Add Hermes Skill Draft Service Contract

**Files:**
- Modify: `app/services/hermes.py`
- Test: `tests/services/test_hermes.py`

- [ ] **Step 1: Write failing Hermes skill draft normalization tests**

Append tests to `tests/services/test_hermes.py`:

```python
def test_normalize_skill_draft_response_partitions_valid_invalid_and_conflicts(
    monkeypatch, tmp_path
) -> None:
    from app.services import agent_fs
    from app.services.hermes import normalize_hermes_skill_draft_response

    monkeypatch.setattr(agent_fs.settings, "SKILLS_DIR", str(tmp_path))
    agent_fs.write_skill(
        "existing-skill",
        "---\nname: existing-skill\ndescription: Existing\n---\nBody\n",
        create=True,
    )

    result = normalize_hermes_skill_draft_response(
        {
            "summary": "done",
            "skill_drafts": [
                {
                    "name": "new-skill",
                    "description": "Draft helper",
                    "body": "Use this when drafting.",
                    "rationale": "Useful.",
                },
                {
                    "name": "existing-skill",
                    "description": "Existing helper",
                    "body": "Should conflict.",
                },
                {"name": "-bad", "description": "Bad", "body": "Bad"},
            ],
            "warnings": ["top warning"],
            "model_info": {"model": "hermes-test"},
        }
    )

    assert result.summary == "done"
    assert [draft.name for draft in result.valid_drafts] == ["new-skill"]
    assert [draft.name for draft in result.conflicts] == ["existing-skill"]
    assert result.invalid_drafts[0].invalid_reason
    assert "top warning" in result.warnings
    assert result.model_info == {"model": "hermes-test"}


def test_normalize_skill_draft_response_rejects_forbidden_fields() -> None:
    from app.services.hermes import (
        HermesSchemaError,
        normalize_hermes_skill_draft_response,
    )

    with pytest.raises(HermesSchemaError, match="forbidden field"):
        normalize_hermes_skill_draft_response(
            {
                "skill_drafts": [
                    {
                        "name": "bad",
                        "description": "Bad",
                        "body": "Bad",
                        "frontmatter": "---",
                    }
                ]
            }
        )


def test_normalize_skill_draft_response_truncates_body(monkeypatch, tmp_path) -> None:
    from app.services import agent_fs
    from app.services.hermes import normalize_hermes_skill_draft_response

    monkeypatch.setattr(agent_fs.settings, "SKILLS_DIR", str(tmp_path))
    result = normalize_hermes_skill_draft_response(
        {
            "skill_drafts": [
                {
                    "name": "long-skill",
                    "description": "Long helper",
                    "body": "x" * 12,
                }
            ]
        },
        max_body_chars_per_draft=5,
    )

    draft = result.valid_drafts[0]
    assert draft.body == "x" * 5
    assert draft.body_truncated is True
    assert any("truncated" in warning for warning in draft.warnings)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/services/test_hermes.py::test_normalize_skill_draft_response_partitions_valid_invalid_and_conflicts tests/services/test_hermes.py::test_normalize_skill_draft_response_rejects_forbidden_fields tests/services/test_hermes.py::test_normalize_skill_draft_response_truncates_body --no-cov -q
```

Expected:

```text
FAILED ... cannot import name 'normalize_hermes_skill_draft_response'
```

- [ ] **Step 3: Implement dataclasses, protocol, HTTP method, and normalization**

In `app/services/hermes.py`, add constants:

```python
_MAX_SKILL_DRAFTS = 10
_DEFAULT_MAX_BODY_CHARS_PER_SKILL_DRAFT = 8000
_FORBIDDEN_SKILL_DRAFT_FIELDS = {
    "path",
    "absolute_path",
    "content",
    "frontmatter",
    "overwrite",
    "existing_skill",
    "install",
    "tools",
    "agent_config",
    "writer",
    "pending_id",
}
```

Add dataclasses:

```python
@dataclass(frozen=True)
class HermesSkillDraftRequest:
    task: str
    context: str = ""
    max_drafts: int = 3


@dataclass(frozen=True)
class HermesSkillDraftProposal:
    name: str
    description: str
    body: str
    rationale: str = ""
    body_truncated: bool = False
    exists_conflict: bool = False
    warning: str | None = None
    invalid_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HermesSkillDraftResult:
    summary: str = ""
    valid_drafts: list[HermesSkillDraftProposal] = field(default_factory=list)
    conflicts: list[HermesSkillDraftProposal] = field(default_factory=list)
    invalid_drafts: list[HermesSkillDraftProposal] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model_info: dict[str, Any] = field(default_factory=dict)
```

Extend `HermesClient`:

```python
async def draft_skills(self, request: HermesSkillDraftRequest) -> dict[str, Any]:
    """Return the raw Hermes skill draft payload."""
```

Add `HttpHermesClient.draft_skills`:

```python
async def draft_skills(self, request: HermesSkillDraftRequest) -> dict[str, Any]:
    response = await self._request(
        "POST",
        "/v1/skill-drafts",
        json={
            "task": request.task,
            "context": request.context,
            "max_drafts": request.max_drafts,
        },
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise HermesSchemaError("Hermes response must be a JSON object.")
    return payload
```

Add public service function:

```python
async def draft_skills(
    request: HermesSkillDraftRequest,
    *,
    client: HermesClient | None = None,
    max_context_chars: int | None = None,
    max_body_chars_per_draft: int | None = None,
) -> HermesSkillDraftResult:
    hermes_client = client or _client_from_settings()
    prepared = _prepare_skill_draft_request(
        request,
        max_context_chars=max_context_chars,
    )
    await hermes_client.health()
    payload = await hermes_client.draft_skills(prepared)
    return normalize_hermes_skill_draft_response(
        payload,
        max_body_chars_per_draft=max_body_chars_per_draft,
    )
```

Add prepare and normalization helpers:

```python
def _prepare_skill_draft_request(
    request: HermesSkillDraftRequest,
    *,
    max_context_chars: int | None,
) -> HermesSkillDraftRequest:
    return replace(
        request,
        task=request.task.strip(),
        context=request.context[
            : _positive_int(
                max_context_chars,
                fallback=settings.OPENAGENTD_HERMES_MAX_CONTEXT_CHARS,
            )
        ],
        max_drafts=_clamp_int(request.max_drafts, minimum=1, maximum=_MAX_SKILL_DRAFTS),
    )
```

```python
def normalize_hermes_skill_draft_response(
    payload: dict[str, Any],
    *,
    max_body_chars_per_draft: int | None = None,
) -> HermesSkillDraftResult:
    if not isinstance(payload, dict):
        raise HermesSchemaError("Hermes response must be a JSON object.")
    summary = _optional_string(payload.get("summary"), field_name="summary")
    raw_warnings = payload.get("warnings", [])
    if raw_warnings is None:
        raw_warnings = []
    if not isinstance(raw_warnings, list):
        raise HermesSchemaError("Hermes response warnings must be a list.")
    warnings = [str(item) for item in raw_warnings if str(item).strip()]
    raw_model_info = payload.get("model_info", {})
    model_info = raw_model_info if isinstance(raw_model_info, dict) else {}
    raw_drafts = payload.get("skill_drafts", [])
    if not isinstance(raw_drafts, list):
        raise HermesSchemaError("Hermes response skill_drafts must be a list.")

    body_limit = _positive_int(
        max_body_chars_per_draft,
        fallback=_DEFAULT_MAX_BODY_CHARS_PER_SKILL_DRAFT,
    )
    valid_drafts: list[HermesSkillDraftProposal] = []
    conflicts: list[HermesSkillDraftProposal] = []
    invalid_drafts: list[HermesSkillDraftProposal] = []
    for raw in raw_drafts:
        draft = _normalize_skill_draft(raw, body_limit=body_limit)
        if draft.invalid_reason:
            invalid_drafts.append(draft)
        elif draft.exists_conflict:
            conflicts.append(draft)
        else:
            valid_drafts.append(draft)
        warnings.extend(draft.warnings)
    return HermesSkillDraftResult(
        summary=summary,
        valid_drafts=valid_drafts,
        conflicts=conflicts,
        invalid_drafts=invalid_drafts,
        warnings=_dedupe(warnings),
        model_info=model_info,
    )
```

```python
def _normalize_skill_draft(raw: Any, *, body_limit: int) -> HermesSkillDraftProposal:
    from app.services import agent_fs

    if not isinstance(raw, dict):
        return HermesSkillDraftProposal(
            name="",
            description="",
            body="",
            invalid_reason="Hermes skill_draft must be an object.",
        )
    forbidden = sorted(_FORBIDDEN_SKILL_DRAFT_FIELDS.intersection(raw))
    if forbidden:
        raise HermesSchemaError(
            f"Hermes skill_draft contains forbidden field: {', '.join(forbidden)}"
        )
    try:
        name = _required_string(raw, "name")
        description = _required_string(raw, "description")
        body = _required_string(raw, "body")
        agent_fs.validate_skill_name(name)
    except (HermesSchemaError, agent_fs.AgentFsPathError) as exc:
        return HermesSkillDraftProposal(
            name=str(raw.get("name") or ""),
            description=str(raw.get("description") or ""),
            body=str(raw.get("body") or ""),
            invalid_reason=str(exc),
        )

    body_truncated = False
    warnings: list[str] = []
    if len(body) > body_limit:
        body = body[:body_limit]
        body_truncated = True
        warnings.append(f"skill body was truncated to {body_limit} characters")

    draft = HermesSkillDraftProposal(
        name=name,
        description=description,
        body=body,
        rationale=_optional_string(raw.get("rationale"), field_name="rationale"),
        body_truncated=body_truncated,
        warnings=warnings,
    )
    try:
        agent_fs.read_skill(name)
    except agent_fs.AgentFsNotFoundError:
        return draft
    return replace(
        draft,
        exists_conflict=True,
        warning=f"skill already exists at skills/{name}/SKILL.md",
    )
```

- [ ] **Step 4: Run Hermes service tests**

Run:

```powershell
uv run pytest tests/services/test_hermes.py --no-cov -q
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add app/services/hermes.py tests/services/test_hermes.py
git commit -m "feat: add Hermes skill draft contract"
```

---

## Task 4: Add Hermes Skill Draft Queue Service

**Files:**
- Create: `app/services/hermes_skill_drafting.py`
- Test: `tests/services/test_hermes_skill_drafting.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/services/test_hermes_skill_drafting.py` with focused tests:

```python
from __future__ import annotations

import asyncio
import re

import pytest

from app.services.hermes import HermesSkillDraftProposal
from app.services.hermes_skill_drafting import (
    HERMES_SKILL_QUEUE_LIMIT_REASON,
    HermesSkillDraftAlreadyProcessedError,
    HermesSkillDraftNotFoundError,
    HermesSkillDraftQueue,
)


def _draft(name: str = "draft-skill") -> HermesSkillDraftProposal:
    return HermesSkillDraftProposal(
        name=name,
        description=f"Description for {name}",
        body=f"Body for {name}",
    )


async def test_enqueue_creates_uuid4_pending_ids() -> None:
    queue = HermesSkillDraftQueue()
    result = await queue.enqueue("session-a", [_draft()])

    assert len(result.entries) == 1
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        result.entries[0].pending_id,
    )


async def test_list_is_scoped_by_session() -> None:
    queue = HermesSkillDraftQueue()
    await queue.enqueue("session-a", [_draft("a")])
    await queue.enqueue("session-b", [_draft("b")])

    assert [entry.draft.name for entry in await queue.list_pending("session-a")] == ["a"]
    assert [entry.draft.name for entry in await queue.list_pending("session-b")] == ["b"]


async def test_queue_limit_prunes_terminal_before_evicting_pending() -> None:
    queue = HermesSkillDraftQueue(max_entries_per_session=3)
    first = await queue.enqueue("session-a", [_draft("one"), _draft("two")])
    await queue.reject(first.entries[0].pending_id, session_id="session-a")

    result = await queue.enqueue("session-a", [_draft("three"), _draft("four")])

    assert result.pruned_count == 1
    assert result.evicted_count == 0
    entries = await queue.list_pending("session-a", include_non_pending=True)
    assert [entry.draft.name for entry in entries] == ["two", "three", "four"]


async def test_queue_limit_evicts_oldest_pending_when_needed() -> None:
    queue = HermesSkillDraftQueue(max_entries_per_session=2)
    first = await queue.enqueue("session-a", [_draft("one"), _draft("two")])

    result = await queue.enqueue("session-a", [_draft("three")])

    assert result.pruned_count == 0
    assert result.evicted_count == 1
    with pytest.raises(HermesSkillDraftNotFoundError):
        await queue.approve(first.entries[0].pending_id, session_id="session-a")
    remaining = await queue.list_pending("session-a")
    assert [entry.draft.name for entry in remaining] == ["two", "three"]


async def test_reject_marks_entry_terminal() -> None:
    queue = HermesSkillDraftQueue()
    result = await queue.enqueue("session-a", [_draft()])

    entry = await queue.reject(result.entries[0].pending_id, session_id="session-a", reason="no")

    assert entry.status == "rejected"
    assert entry.reject_reason == "no"
    with pytest.raises(HermesSkillDraftAlreadyProcessedError):
        await queue.approve(result.entries[0].pending_id, session_id="session-a")


async def test_double_approve_only_one_wins(monkeypatch, tmp_path) -> None:
    from app.services import agent_fs

    monkeypatch.setattr(agent_fs.settings, "SKILLS_DIR", str(tmp_path))
    queue = HermesSkillDraftQueue()
    result = await queue.enqueue("session-a", [_draft()])
    pending_id = result.entries[0].pending_id

    outcomes = await asyncio.gather(
        queue.approve(pending_id, session_id="session-a"),
        queue.approve(pending_id, session_id="session-a"),
        return_exceptions=True,
    )

    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert sum(isinstance(item, HermesSkillDraftAlreadyProcessedError) for item in outcomes) == 1
    assert (tmp_path / "draft-skill" / "SKILL.md").is_file()


async def test_approve_writes_skill_and_invalidates_cache(monkeypatch, tmp_path) -> None:
    from app.services import agent_fs
    from app.services import hermes_skill_drafting as module

    monkeypatch.setattr(agent_fs.settings, "SKILLS_DIR", str(tmp_path))
    invalidated = False

    def fake_invalidate() -> None:
        nonlocal invalidated
        invalidated = True

    monkeypatch.setattr(module.team_manager, "invalidate_skill_cache", fake_invalidate)
    queue = HermesSkillDraftQueue()
    result = await queue.enqueue("session-a", [_draft()])

    approved = await queue.approve(result.entries[0].pending_id, session_id="session-a")

    assert approved.name == "draft-skill"
    assert invalidated is True
    content = (tmp_path / "draft-skill" / "SKILL.md").read_text(encoding="utf-8")
    assert content.startswith("---\nname: draft-skill\ndescription: Description for draft-skill\n---\n")
    assert "Body for draft-skill\n" in content
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/services/test_hermes_skill_drafting.py --no-cov -q
```

Expected:

```text
FAILED ... No module named 'app.services.hermes_skill_drafting'
```

- [ ] **Step 3: Implement queue dataclasses and errors**

Create `app/services/hermes_skill_drafting.py`:

```python
"""Hermes skill draft review queue and approval write boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import yaml

from app.services import agent_fs, team_manager
from app.services.hermes import HermesSkillDraftProposal

HERMES_SKILL_QUEUE_LIMIT_REASON = "superseded_by_queue_limit"
DEFAULT_MAX_SKILL_DRAFT_ENTRIES_PER_SESSION = 50
TERMINAL_STATUSES = {"approved", "rejected", "failed"}


class HermesSkillDraftError(Exception):
    """Base error for Hermes skill draft approval flow."""


class HermesSkillDraftNotFoundError(HermesSkillDraftError):
    """Raised when a pending id is missing or not visible in this session."""


class HermesSkillDraftAlreadyProcessedError(HermesSkillDraftError):
    """Raised when an entry is not pending."""


class HermesSkillDraftWriteError(HermesSkillDraftError):
    """Raised when approval cannot create the skill file."""
```

Add dataclasses:

```python
@dataclass
class PendingHermesSkillDraft:
    pending_id: str
    session_id: str
    draft: HermesSkillDraftProposal
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reject_reason: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class HermesSkillDraftEnqueueResult:
    entries: list[PendingHermesSkillDraft]
    evicted_count: int = 0
    pruned_count: int = 0


@dataclass(frozen=True)
class HermesSkillDraftApprovalResult:
    pending_id: str
    name: str
    path: str
```

- [ ] **Step 4: Implement rendering and queue methods**

Continue `app/services/hermes_skill_drafting.py`:

```python
def render_skill_markdown(draft: HermesSkillDraftProposal) -> str:
    metadata = {
        "name": agent_fs.validate_skill_name(draft.name),
        "description": draft.description.strip(),
    }
    if not metadata["description"]:
        raise HermesSkillDraftWriteError("Skill description cannot be empty.")
    body = draft.body.strip()
    if not body:
        raise HermesSkillDraftWriteError("Skill body cannot be empty.")
    frontmatter = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{frontmatter}\n---\n{body}\n"
```

```python
class HermesSkillDraftQueue:
    def __init__(
        self,
        *,
        max_entries_per_session: int = DEFAULT_MAX_SKILL_DRAFT_ENTRIES_PER_SESSION,
    ) -> None:
        self.max_entries_per_session = max(1, int(max_entries_per_session))
        self._entries: dict[str, PendingHermesSkillDraft] = {}
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        session_id: str,
        drafts: list[HermesSkillDraftProposal],
    ) -> HermesSkillDraftEnqueueResult:
        async with self._lock:
            entries = [
                PendingHermesSkillDraft(
                    pending_id=str(uuid4()),
                    session_id=session_id,
                    draft=draft,
                )
                for draft in drafts
            ]
            for entry in entries:
                self._entries[entry.pending_id] = entry
            pruned_count, evicted_count = self._enforce_limit_locked(session_id)
            return HermesSkillDraftEnqueueResult(
                entries=[
                    entry
                    for entry in entries
                    if entry.pending_id in self._entries and entry.status == "pending"
                ],
                evicted_count=evicted_count,
                pruned_count=pruned_count,
            )

    async def list_pending(
        self,
        session_id: str,
        *,
        include_non_pending: bool = False,
    ) -> list[PendingHermesSkillDraft]:
        async with self._lock:
            self._enforce_limit_locked(session_id)
            entries = [
                entry
                for entry in self._entries.values()
                if entry.session_id == session_id
                and (include_non_pending or entry.status == "pending")
            ]
            return sorted(entries, key=lambda entry: entry.created_at)

    async def approve(
        self,
        pending_id: str,
        *,
        session_id: str,
    ) -> HermesSkillDraftApprovalResult:
        async with self._lock:
            entry = self._get_for_session_locked(pending_id, session_id)
            self._ensure_pending_locked(entry)
            content = render_skill_markdown(entry.draft)
            try:
                record = agent_fs.write_skill(entry.draft.name, content, create=True)
                team_manager.invalidate_skill_cache()
            except (agent_fs.AgentFsPathError, agent_fs.AgentFsConflictError, OSError) as exc:
                entry.status = "failed"
                entry.failure_reason = str(exc)
                entry.updated_at = datetime.now(UTC)
                raise HermesSkillDraftWriteError(str(exc)) from exc
            entry.status = "approved"
            entry.updated_at = datetime.now(UTC)
            return HermesSkillDraftApprovalResult(
                pending_id=entry.pending_id,
                name=entry.draft.name,
                path=record.path,
            )

    async def reject(
        self,
        pending_id: str,
        *,
        session_id: str,
        reason: str | None = None,
    ) -> PendingHermesSkillDraft:
        async with self._lock:
            entry = self._get_for_session_locked(pending_id, session_id)
            self._ensure_pending_locked(entry)
            entry.status = "rejected"
            entry.reject_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
            entry.updated_at = datetime.now(UTC)
            self._enforce_limit_locked(session_id)
            return entry
```

Add private helpers and singleton:

```python
    def _enforce_limit_locked(self, session_id: str) -> tuple[int, int]:
        entries = sorted(
            [entry for entry in self._entries.values() if entry.session_id == session_id],
            key=lambda entry: entry.created_at,
        )
        overflow = max(0, len(entries) - self.max_entries_per_session)
        pruned_count = 0
        evicted_count = 0
        if overflow <= 0:
            return pruned_count, evicted_count

        terminal = [entry for entry in entries if entry.status in TERMINAL_STATUSES]
        for entry in terminal[:overflow]:
            self._entries.pop(entry.pending_id, None)
            pruned_count += 1
        overflow -= pruned_count
        if overflow <= 0:
            return pruned_count, evicted_count

        pending = [entry for entry in entries if entry.status == "pending"]
        for entry in pending[:overflow]:
            entry.status = "rejected"
            entry.reject_reason = HERMES_SKILL_QUEUE_LIMIT_REASON
            entry.updated_at = datetime.now(UTC)
            self._entries.pop(entry.pending_id, None)
            evicted_count += 1
        return pruned_count, evicted_count

    def _get_for_session_locked(
        self,
        pending_id: str,
        session_id: str,
    ) -> PendingHermesSkillDraft:
        entry = self._entries.get(pending_id)
        if entry is None or entry.session_id != session_id:
            raise HermesSkillDraftNotFoundError(
                f"No Hermes skill draft found for this session: {pending_id}"
            )
        return entry

    def _ensure_pending_locked(self, entry: PendingHermesSkillDraft) -> None:
        if entry.status in TERMINAL_STATUSES:
            raise HermesSkillDraftAlreadyProcessedError(
                f"Hermes skill draft {entry.pending_id} is already {entry.status}."
            )
        if entry.status != "pending":
            raise HermesSkillDraftAlreadyProcessedError(
                f"Hermes skill draft {entry.pending_id} is not pending."
            )


_queue = HermesSkillDraftQueue()


def get_hermes_skill_draft_queue() -> HermesSkillDraftQueue:
    return _queue
```

- [ ] **Step 5: Run service tests**

Run:

```powershell
uv run pytest tests/services/test_hermes_skill_drafting.py --no-cov -q
```

Expected:

```text
... passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add app/services/hermes_skill_drafting.py tests/services/test_hermes_skill_drafting.py
git commit -m "feat: add Hermes skill draft queue"
```

---

## Task 5: Add Lead-Only Hermes Skill Tools

**Files:**
- Create: `app/agent/tools/builtin/hermes_skill.py`
- Test: `tests/agent/tools/test_hermes_skill_tools.py`

- [ ] **Step 1: Write failing tool tests**

Create `tests/agent/tools/test_hermes_skill_tools.py`:

```python
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.agent.tools.builtin import hermes_skill as module
from app.services.hermes import HermesSkillDraftProposal, HermesSkillDraftResult
from app.services.hermes_skill_drafting import HermesSkillDraftQueue


def _state(session_id: str | None = "session-a"):
    metadata = {"agent_name": "lead"}
    if session_id is not None:
        metadata["session_id"] = session_id
    return SimpleNamespace(metadata=metadata)


async def test_hermes_skill_draft_requires_session_before_calling_hermes(monkeypatch) -> None:
    called = False

    async def fake_draft_skills(*args, **kwargs):
        nonlocal called
        called = True
        return HermesSkillDraftResult()

    monkeypatch.setattr(module, "draft_skills", fake_draft_skills)

    result = await module.hermes_skill_draft.arun(task="draft", _injected={"_state": _state(None)})

    assert "requires a session_id" in result
    assert called is False


async def test_hermes_skill_draft_enqueues_valid_drafts(monkeypatch) -> None:
    queue = HermesSkillDraftQueue()
    monkeypatch.setattr(module, "get_hermes_skill_draft_queue", lambda: queue)

    async def fake_draft_skills(*args, **kwargs):
        return HermesSkillDraftResult(
            summary="done",
            valid_drafts=[
                HermesSkillDraftProposal(
                    name="draft-skill",
                    description="Draft helper",
                    body="Body content",
                    rationale="Useful",
                )
            ],
        )

    monkeypatch.setattr(module, "draft_skills", fake_draft_skills)

    result = await module.hermes_skill_draft.arun(
        task="draft",
        context="ctx",
        _injected={"_state": _state()},
    )
    payload = json.loads(result)

    assert payload["summary"] == "done"
    assert payload["evicted_count"] == 0
    assert payload["pruned_count"] == 0
    assert payload["valid_drafts"][0]["pending_id"]
    assert payload["valid_drafts"][0]["preview"]["body_preview"] == "Body content"
    assert payload["valid_drafts"][0]["preview"]["body_length"] == len("Body content")


async def test_hermes_skill_pending_approve_writes_skill(monkeypatch, tmp_path) -> None:
    from app.services import agent_fs

    monkeypatch.setattr(agent_fs.settings, "SKILLS_DIR", str(tmp_path))
    queue = HermesSkillDraftQueue()
    enqueued = await queue.enqueue(
        "session-a",
        [
            HermesSkillDraftProposal(
                name="draft-skill",
                description="Draft helper",
                body="Body content",
            )
        ],
    )
    monkeypatch.setattr(module, "get_hermes_skill_draft_queue", lambda: queue)

    result = await module.hermes_skill_pending_approve.arun(
        pending_id=enqueued.entries[0].pending_id,
        _injected={"_state": _state()},
    )

    assert "approved" in result
    assert (tmp_path / "draft-skill" / "SKILL.md").is_file()


async def test_hermes_skill_pending_reject_rejects(monkeypatch) -> None:
    queue = HermesSkillDraftQueue()
    enqueued = await queue.enqueue("session-a", [HermesSkillDraftProposal(name="draft-skill", description="Draft helper", body="Body")])
    monkeypatch.setattr(module, "get_hermes_skill_draft_queue", lambda: queue)

    result = await module.hermes_skill_pending_reject.arun(
        pending_id=enqueued.entries[0].pending_id,
        reason="not needed",
        _injected={"_state": _state()},
    )

    assert "rejected" in result
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/agent/tools/test_hermes_skill_tools.py --no-cov -q
```

Expected:

```text
FAILED ... cannot import name 'hermes_skill'
```

- [ ] **Step 3: Implement `hermes_skill.py`**

Create `app/agent/tools/builtin/hermes_skill.py` with the same patterns as `hermes_propose.py` and `hermes_pending.py`:

```python
"""Hermes skill draft and pending approval tools."""

from __future__ import annotations

import json
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
from app.services.hermes import (
    HermesConnectionError,
    HermesSchemaError,
    HermesSkillDraftProposal,
    HermesSkillDraftRequest,
    HermesTimeoutError,
    HermesUnavailableError,
    draft_skills,
)
from app.services.hermes_skill_drafting import (
    HermesSkillDraftAlreadyProcessedError,
    HermesSkillDraftError,
    HermesSkillDraftNotFoundError,
    HermesSkillDraftWriteError,
    PendingHermesSkillDraft,
    get_hermes_skill_draft_queue,
)

_BODY_PREVIEW_CHARS = 4000
```

Implement helpers:

```python
def _session_id_from_state(state: Any) -> str | None:
    metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    session_id = metadata.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    return session_id.strip()


def _preview(draft: HermesSkillDraftProposal) -> dict[str, Any]:
    body_preview = draft.body[:_BODY_PREVIEW_CHARS]
    return {
        "name": draft.name,
        "description": draft.description,
        "body_preview": body_preview,
        "body_length": len(draft.body),
        "body_truncated": draft.body_truncated,
        "body_preview_truncated": len(draft.body) > len(body_preview),
        "rationale": draft.rationale,
        "warnings": draft.warnings,
    }


def _record(
    tool: str,
    outcome: str,
    status: str,
    start: float,
    attributes: Mapping[str, object],
) -> None:
    record_second_brain_tool_observation(
        tool=tool,
        outcome=outcome,
        status=status,
        duration_seconds=time.perf_counter() - start,
        attributes=attributes,
    )
```

Implement `_hermes_skill_draft`:

```python
async def _hermes_skill_draft(
    task: Annotated[str, Field(description="The skill drafting task Hermes should analyze.")],
    context: Annotated[str, Field(description="Optional context string for Hermes.")] = "",
    max_drafts: Annotated[int, Field(description="Maximum drafts to request, clamped by Hermes adapter.")] = 3,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    start = time.perf_counter()
    attrs = {
        "skill.task_length": len(task or ""),
        "skill.context_length": len(context or ""),
        "skill.max_drafts": max_drafts,
    }
    session_id = _session_id_from_state(_state)
    if session_id is None:
        _record("hermes_skill_draft", "missing_session", SECOND_BRAIN_ERROR, start, attrs)
        return "Hermes skill draft queue requires a session_id."

    try:
        result = await draft_skills(
            HermesSkillDraftRequest(task=task, context=context, max_drafts=max_drafts)
        )
    except HermesUnavailableError as exc:
        _record("hermes_skill_draft", "unavailable", SECOND_BRAIN_ERROR, start, attrs)
        return f"Hermes connector unavailable: {exc}"
    except HermesTimeoutError as exc:
        _record("hermes_skill_draft", "timeout", SECOND_BRAIN_ERROR, start, attrs)
        return f"Hermes connector timed out: {exc}"
    except HermesConnectionError as exc:
        _record("hermes_skill_draft", "connection_error", SECOND_BRAIN_ERROR, start, attrs)
        return f"Hermes connector connection failed: {exc}"
    except HermesSchemaError as exc:
        _record("hermes_skill_draft", "schema_error", SECOND_BRAIN_ERROR, start, attrs)
        return f"Hermes connector schema error: {exc}"

    enqueued = await get_hermes_skill_draft_queue().enqueue(session_id, result.valid_drafts)
    _record(
        "hermes_skill_draft",
        "enqueued",
        SECOND_BRAIN_OK,
        start,
        {
            **attrs,
            "skill.draft_count": len(result.valid_drafts),
            "skill.conflict_count": len(result.conflicts),
            "skill.invalid_count": len(result.invalid_drafts),
            "skill.pending_count": len(enqueued.entries),
            "skill.evicted_count": enqueued.evicted_count,
            "skill.pruned_count": enqueued.pruned_count,
        },
    )
    return json.dumps(
        {
            "summary": result.summary,
            "warnings": result.warnings,
            "model_info": result.model_info,
            "evicted_count": enqueued.evicted_count,
            "pruned_count": enqueued.pruned_count,
            "valid_drafts": [
                {
                    "pending_id": entry.pending_id,
                    "preview": _preview(entry.draft),
                }
                for entry in enqueued.entries
            ],
            "conflicts": [
                {
                    "preview": _preview(draft),
                    "warning": draft.warning,
                }
                for draft in result.conflicts
            ],
            "invalid_drafts": [
                {
                    "name": draft.name,
                    "invalid_reason": draft.invalid_reason,
                }
                for draft in result.invalid_drafts
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
```

Implement list/approve/reject using the same catch pattern as `hermes_pending.py`, with outcomes from the spec and no raw body/reason/pending id in observability attrs.

Register `Tool(...)` objects at the bottom:

```python
hermes_skill_draft = Tool(
    _hermes_skill_draft,
    name="hermes_skill_draft",
    description=(
        "Ask Hermes for structured skill drafts. This never writes skill files; "
        "it creates pending skill draft entries for lead review."
    ),
)
```

Add analogous `hermes_skill_pending_list`, `hermes_skill_pending_approve`, and `hermes_skill_pending_reject` tool objects.

- [ ] **Step 4: Run tool tests**

Run:

```powershell
uv run pytest tests/agent/tools/test_hermes_skill_tools.py --no-cov -q
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add app/agent/tools/builtin/hermes_skill.py tests/agent/tools/test_hermes_skill_tools.py
git commit -m "feat: add Hermes skill draft tools"
```

---

## Task 6: Register Tools And Enforce Lead-Only Loader Boundary

**Files:**
- Modify: `app/agent/tools/builtin/__init__.py`
- Modify: `app/agent/loader.py`
- Test: `tests/agent/test_loader.py`

- [ ] **Step 1: Write failing loader/registry tests**

Add tests to `tests/agent/test_loader.py` using existing loader fixtures/patterns:

```python
def test_lead_receives_hermes_skill_tools(tmp_path):
    from app.agent.loader import load_team_from_dir

    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "lead.md").write_text(
        """---
name: lead
role: lead
model: __PROVIDER_MODEL__
tools: []
---
Lead.
""",
        encoding="utf-8",
    )

    team = load_team_from_dir(agents)

    tool_names = {tool.name for tool in team.lead.agent.tools}
    assert {
        "hermes_skill_draft",
        "hermes_skill_pending_list",
        "hermes_skill_pending_approve",
        "hermes_skill_pending_reject",
    }.issubset(tool_names)


def test_member_frontmatter_hermes_skill_tools_are_skipped_with_warning(tmp_path, caplog_loguru):
    from app.agent.loader import load_team_from_dir, rebuild_agent_from_disk

    agents = tmp_path / "agents"
    agents.mkdir()
    member_path = agents / "member.md"
    member_path.write_text(
        """---
name: member
role: member
model: __PROVIDER_MODEL__
tools: [hermes_skill_draft, hermes_skill_pending_approve]
---
Member.
""",
        encoding="utf-8",
    )
    (agents / "lead.md").write_text(
        """---
name: lead
role: lead
model: __PROVIDER_MODEL__
tools: []
---
Lead.
""",
        encoding="utf-8",
    )

    member = rebuild_agent_from_disk(member_path)

    tool_names = {tool.name for tool in member.tools}
    assert "hermes_skill_draft" not in tool_names
    assert "hermes_skill_pending_approve" not in tool_names
    assert "lead_only_tool_skipped" in caplog_loguru.text
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
uv run pytest tests/agent/test_loader.py::test_lead_receives_hermes_skill_tools tests/agent/test_loader.py::test_member_frontmatter_hermes_skill_tools_are_skipped_with_warning --no-cov -q
```

Expected:

```text
FAILED ... hermes_skill_draft
```

- [ ] **Step 3: Export the tools**

Modify `app/agent/tools/builtin/__init__.py`:

```python
from .hermes_skill import (
    hermes_skill_draft,
    hermes_skill_pending_approve,
    hermes_skill_pending_list,
    hermes_skill_pending_reject,
)
```

Add names to `__all__`.

- [ ] **Step 4: Register and inject tools in loader**

In `_default_tool_registry`, import the new tools and add:

```python
"hermes_skill_draft": hermes_skill_draft,
"hermes_skill_pending_list": hermes_skill_pending_list,
"hermes_skill_pending_approve": hermes_skill_pending_approve,
"hermes_skill_pending_reject": hermes_skill_pending_reject,
```

In `_build_agent`, introduce a lead-only set:

```python
LEAD_ONLY_BUILTIN_TOOLS = {
    "skill",
    "todo_manage",
    "schedule_task",
    "hermes_query",
    "hermes_propose",
    "hermes_pending_list",
    "hermes_pending_approve",
    "hermes_pending_reject",
    "hermes_skill_draft",
    "hermes_skill_pending_list",
    "hermes_skill_pending_approve",
    "hermes_skill_pending_reject",
    "note",
    "vault_read",
    "vault_search",
    "vault_update",
    "vault_write",
}
```

Use the set in the `for tool_name in cfg.tools` loop:

```python
if tool_name in LEAD_ONLY_BUILTIN_TOOLS:
    if cfg.role != "lead":
        logger.warning(
            "lead_only_tool_skipped agent={} role={} tool={}",
            cfg.name,
            cfg.role,
            tool_name,
        )
    continue
```

For lead injection, import the new tool module and append the four resolved tools to the existing lead-only tools list.

- [ ] **Step 5: Run loader tests**

Run:

```powershell
uv run pytest tests/agent/test_loader.py --no-cov -q
```

Expected:

```text
... passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add app/agent/tools/builtin/__init__.py app/agent/loader.py tests/agent/test_loader.py
git commit -m "feat: register Hermes skill tools"
```

---

## Task 7: Expand Tool Privacy And Observability Tests

**Files:**
- Modify: `tests/agent/tools/test_hermes_skill_tools.py`
- Modify: `app/agent/tools/builtin/hermes_skill.py`

- [ ] **Step 1: Add failing tests that inspect OTel span attrs**

Add tests using the existing in-memory span exporter pattern from `tests/agent/hooks/test_otel_hook.py`:

```python
def test_skill_tool_observability_attrs_do_not_leak_sensitive_values(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_record(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(module, "record_second_brain_tool_observation", fake_record)

    module._record(
        "hermes_skill_draft",
        "enqueued",
        module.SECOND_BRAIN_OK,
        0.0,
        {
            "skill.name": "draft-skill",
            "skill.body_length": 11,
            "skill.description_length": 12,
            "skill.pending_count": 1,
        },
    )

    attributes = calls[0]["attributes"]
    forbidden_values = ["private", "body_preview", "pending_id", "reason"]
    assert all(value not in str(attributes) for value in forbidden_values)
```

Add a test that Hermes errors map specifically:

```python
async def test_hermes_skill_draft_schema_error_is_specific(monkeypatch) -> None:
    from app.services.hermes import HermesSchemaError

    async def fake_draft_skills(*args, **kwargs):
        raise HermesSchemaError("bad skill draft")

    monkeypatch.setattr(module, "draft_skills", fake_draft_skills)

    result = await module.hermes_skill_draft.arun(
        task="draft",
        _injected={"_state": _state()},
    )

    assert result == "Hermes connector schema error: bad skill draft"
```

- [ ] **Step 2: Run tests**

Run:

```powershell
uv run pytest tests/agent/tools/test_hermes_skill_tools.py --no-cov -q
```

Expected:

```text
... passed
```

If the first test fails because `_record` passes sensitive values, remove those attributes from `app/agent/tools/builtin/hermes_skill.py` and keep only lengths/counts/booleans/names.

- [ ] **Step 3: Commit**

Run:

```powershell
git add app/agent/tools/builtin/hermes_skill.py tests/agent/tools/test_hermes_skill_tools.py
git commit -m "test: cover Hermes skill tool privacy outcomes"
```

---

## Task 8: Regression, Snapshot, And Final Commit

**Files:**
- Modify: `.agent/memory/CONTEXT_SNAPSHOT.md`

- [ ] **Step 1: Run targeted service tests**

Run:

```powershell
uv run pytest tests/services/test_agent_fs.py tests/services/test_hermes.py tests/services/test_hermes_skill_drafting.py --no-cov -q
```

Expected:

```text
... passed
```

- [ ] **Step 2: Run targeted tool/loader tests**

Run:

```powershell
uv run pytest tests/agent/test_hermes_skill_redaction.py tests/agent/tools/test_hermes_skill_tools.py tests/agent/test_loader.py --no-cov -q
```

Expected:

```text
... passed
```

- [ ] **Step 3: Run neighboring regression tests**

Run:

```powershell
uv run pytest tests/services/test_hermes_approval.py tests/agent/tools/test_hermes_propose_tool.py tests/agent/tools/test_hermes_pending_tools.py tests/agent/tools/test_hermes_query_tool.py tests/agent/tools/test_skill_loader.py --no-cov -q
```

Expected:

```text
... passed
```

- [ ] **Step 4: Run lint and format checks**

Run:

```powershell
uv run ruff check app/services/agent_fs.py app/services/hermes.py app/services/hermes_skill_drafting.py app/agent/agent_loop/tool_executor.py app/agent/hooks/stream_publisher.py app/agent/tools/builtin/hermes_skill.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_agent_fs.py tests/services/test_hermes.py tests/services/test_hermes_skill_drafting.py tests/agent/test_hermes_skill_redaction.py tests/agent/tools/test_hermes_skill_tools.py tests/agent/test_loader.py
uv run ruff format --check app/services/agent_fs.py app/services/hermes.py app/services/hermes_skill_drafting.py app/agent/agent_loop/tool_executor.py app/agent/hooks/stream_publisher.py app/agent/tools/builtin/hermes_skill.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_agent_fs.py tests/services/test_hermes.py tests/services/test_hermes_skill_drafting.py tests/agent/test_hermes_skill_redaction.py tests/agent/tools/test_hermes_skill_tools.py tests/agent/test_loader.py
```

Expected:

```text
All checks passed!
```

- [ ] **Step 5: Run targeted type check**

Run:

```powershell
uv run ty check app/services/agent_fs.py app/services/hermes.py app/services/hermes_skill_drafting.py app/agent/agent_loop/tool_executor.py app/agent/hooks/stream_publisher.py app/agent/tools/builtin/hermes_skill.py app/agent/loader.py
```

Expected:

```text
No type errors found
```

If `ty` reports pre-existing diagnostics outside these touched files, record them in the final summary and keep the targeted command output as the gate.

- [ ] **Step 6: Update context snapshot**

Update `.agent/memory/CONTEXT_SNAPSHOT.md` with:

```markdown
- Hermes Skill Drafting v1 is implemented and verified. Lead agents can request Hermes skill drafts, review bounded previews, approve one pending draft to create `SKILLS_DIR/{name}/SKILL.md` through `agent_fs.write_skill(..., create=True)`, or reject it without writing. The queue is in-memory, per-process, session-scoped, capped at 50 total entries per session, and uses unguessable pending ids. No API/UI/DB/batch/update/overwrite/auto-install/load/grant/Hermes direct write path was added.
```

Also replace Next Implementation Step 12 with the next candidate after review, for example:

```markdown
12. Send Hermes Skill Drafting v1 to architecture/security review, then Gemini regression/checklist.
```

- [ ] **Step 7: Commit final snapshot**

Run:

```powershell
git add .agent/memory/CONTEXT_SNAPSHOT.md
git commit -m "docs: update Hermes skill drafting status"
```

---

## Implementation Review Prompt

Use this prompt for Claude/Gemini after implementation:

```text
Review Hermes Skill Drafting v1 implementation in OpenAgentd.

Focus:
1. Hermes cannot write files directly; only OpenAgentd approval writes.
2. Approve creates only new SKILLS_DIR/{name}/SKILL.md through agent_fs.write_skill(..., create=True); no overwrite/update/delete/rename/move.
3. Queue is in-memory per-process, session-scoped, max 50 total entries/session, prunes terminal entries, evicts pending with superseded_by_queue_limit, and uses UUIDv4/random pending ids.
4. Existing skill conflicts are detected at proposal normalization and rechecked at approval.
5. Approve calls team_manager.invalidate_skill_cache() and does not call Hermes/load_skill/team_configure/agent config mutation.
6. Four new tools are lead-only; member frontmatter attempts are skipped and logged.
7. Runtime logs, ToolStart stream args, OTel attrs, and metrics do not leak task/context/body/body_preview/description/reject reason/pending_id. ToolEnd output may include pending_id and bounded body_preview for lead review.
8. agent_fs create-only hardening closes the obvious TOCTOU overwrite gap without breaking existing agent/skill routes.
9. No API/UI/DB/batch/auto-install/sibling files were added.

Verdict: Ship / Ship with P2 / Blocked. List P0/P1 with file and line references.
```

---

## Final Verification Bundle

Run this before marking implementation complete:

```powershell
uv run pytest tests/services/test_agent_fs.py tests/services/test_hermes.py tests/services/test_hermes_skill_drafting.py --no-cov -q
uv run pytest tests/agent/test_hermes_skill_redaction.py tests/agent/tools/test_hermes_skill_tools.py tests/agent/test_loader.py --no-cov -q
uv run pytest tests/services/test_hermes_approval.py tests/agent/tools/test_hermes_propose_tool.py tests/agent/tools/test_hermes_pending_tools.py tests/agent/tools/test_hermes_query_tool.py tests/agent/tools/test_skill_loader.py --no-cov -q
uv run ruff check app/services/agent_fs.py app/services/hermes.py app/services/hermes_skill_drafting.py app/agent/agent_loop/tool_executor.py app/agent/hooks/stream_publisher.py app/agent/tools/builtin/hermes_skill.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_agent_fs.py tests/services/test_hermes.py tests/services/test_hermes_skill_drafting.py tests/agent/test_hermes_skill_redaction.py tests/agent/tools/test_hermes_skill_tools.py tests/agent/test_loader.py
uv run ruff format --check app/services/agent_fs.py app/services/hermes.py app/services/hermes_skill_drafting.py app/agent/agent_loop/tool_executor.py app/agent/hooks/stream_publisher.py app/agent/tools/builtin/hermes_skill.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_agent_fs.py tests/services/test_hermes.py tests/services/test_hermes_skill_drafting.py tests/agent/test_hermes_skill_redaction.py tests/agent/tools/test_hermes_skill_tools.py tests/agent/test_loader.py
uv run ty check app/services/agent_fs.py app/services/hermes.py app/services/hermes_skill_drafting.py app/agent/agent_loop/tool_executor.py app/agent/hooks/stream_publisher.py app/agent/tools/builtin/hermes_skill.py app/agent/loader.py
```
