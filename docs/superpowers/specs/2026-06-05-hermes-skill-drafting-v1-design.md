# Hermes Skill Drafting v1 Design

## Summary

Hermes Skill Drafting v1 lets the lead agent ask the Hermes sidecar for
structured skill drafts, review them in an in-memory pending queue, and approve
one draft to create a new `SKILL.md` file under the configured skills
directory.

The feature extends Hermes from vault-note proposals into skill drafting while
preserving OpenAgentd as the only approval and write boundary. Hermes proposes
structured draft data only; it never writes to the skill filesystem and never
installs, grants, loads, or activates a skill.

V1 remains deliberately narrow:

- Tool-only, lead-agent only.
- No API or UI.
- No database persistence.
- No batch approve.
- No update, overwrite, delete, rename, or move for existing skills.
- No Hermes direct write.
- No raw filesystem write from Hermes or the tool layer.
- No skill scripts, assets, or auxiliary files.
- No automatic `skills[]` grant to agents, no `team_configure`, and no
  automatic `load_skill`.

## Existing Context

Relevant current boundaries:

- `app/services/hermes.py` owns the loopback-only HTTP adapter and schema
  normalization for Hermes `write-intents` and read-only `query`.
- `app/services/hermes_approval.py` is vault-specific. Its pending entries hold
  `HermesIntentProposal` objects and approval writes through
  `VaultWriteIntent`. It should not be generalized in v1.
- `app/agent/tools/builtin/hermes_propose.py` enqueues vault note proposals but
  never writes to the vault.
- `app/agent/tools/builtin/hermes_pending.py` approves or rejects vault note
  proposals and writes only through the vault gatekeeper.
- `app/agent/tools/builtin/skill.py` discovers and loads skills. It does not
  write skills.
- `app/services/agent_fs.py` already validates skill names and writes
  `{SKILLS_DIR}/{name}/SKILL.md` atomically through `write_skill(...)`.
- `app/services/team_manager.py` already exposes
  `invalidate_skill_cache()`, which clears the `discover_skills()` cache after
  skill filesystem changes.
- Lead-only tool injection and member exclusion are centralized in
  `app/agent/loader.py`.

Skill drafting should reuse these existing boundaries instead of creating a
raw write lane or refactoring the stable vault approval queue.

## Chosen Approach

Use a separate Hermes skill draft queue and a separate lead-only approval tool
set.

Flow:

1. Lead agent calls `hermes_skill_draft(task, context, max_drafts)`.
2. OpenAgentd calls Hermes `POST /v1/skill-drafts`.
3. OpenAgentd normalizes each returned draft into a structured
   `HermesSkillDraftProposal`.
4. Valid new-skill drafts are enqueued in an in-memory queue scoped to the
   current `session_id`.
5. Drafts that target an existing skill name are reported as conflicts and are
   not enqueued.
6. Lead agent lists pending drafts with `hermes_skill_pending_list`.
7. Lead agent approves one pending id with `hermes_skill_pending_approve`.
8. OpenAgentd revalidates the draft, checks that the skill still does not
   exist, renders `SKILL.md`, writes through `agent_fs.write_skill(...,
   create=True)`, invalidates the skill cache, and marks the entry approved.

Hermes is not called during approve or reject.

## Alternatives Considered

### A. Separate Skill Draft Queue

This is the selected approach.

It keeps the vault-note approval queue stable and preserves a clear boundary
between vault-note writes and skill-file writes. The implementation is slightly
duplicative, but the duplication is acceptable because skill drafts and vault
write intents have different schemas, storage targets, conflict rules, and
post-write side effects.

### B. Generalize `hermes_approval.py`

The existing queue could become a multi-artifact approval queue with handlers
for vault notes and skills.

This would be more abstract, but it increases blast radius in a safety-critical
path that is already accepted and closed. It also risks mixing vault and skill
semantics in one service before the skill workflow is proven. This is rejected
for v1.

### C. Proposal-Only With No Approval Write

Hermes could return draft text and leave the lead agent to use API/UI/manual
filesystem writes.

This is smaller, but it does not satisfy the review/approve/write workflow and
would push agents toward uncontrolled write paths. This is rejected for v1.

## Hermes Contract

Add a read/normalize path to `app/services/hermes.py`.

Request dataclass:

- `HermesSkillDraftRequest`
  - `task: str`
  - `context: str = ""`
  - `max_drafts: int = 3`

HTTP endpoint:

- `POST /v1/skill-drafts`

Request JSON:

```json
{
  "task": "Draft a skill for ...",
  "context": "...",
  "max_drafts": 3
}
```

Raw response shape:

```json
{
  "summary": "Drafted one skill.",
  "skill_drafts": [
    {
      "name": "skill-name",
      "description": "Short description.",
      "body": "Skill instructions...",
      "rationale": "Why this skill helps.",
      "warnings": ["optional warning"]
    }
  ],
  "warnings": [],
  "model_info": {}
}
```

OpenAgentd owns rendering `SKILL.md`. Hermes supplies raw `name`,
`description`, and `body` strings only. Hermes must not return filesystem
paths or pre-rendered frontmatter as the authority for writing.

## Draft Normalization

New dataclasses:

- `HermesSkillDraftProposal`
- `HermesSkillDraftResult`

`HermesSkillDraftProposal` fields:

- `name: str`
- `description: str`
- `body: str`
- `rationale: str = ""`
- `body_truncated: bool = False`
- `exists_conflict: bool = False`
- `warning: str | None = None`
- `invalid_reason: str | None = None`
- `warnings: list[str] = field(default_factory=list)`

`HermesSkillDraftResult` fields:

- `summary: str = ""`
- `valid_drafts: list[HermesSkillDraftProposal]`
- `conflicts: list[HermesSkillDraftProposal]`
- `invalid_drafts: list[HermesSkillDraftProposal]`
- `warnings: list[str]`
- `model_info: dict[str, Any]`

Validation rules:

- `name` must match the existing `agent_fs` name policy:
  - starts with a letter or digit
  - contains only letters, digits, `.`, `_`, and `-`
  - max length 64
- `description` must be a non-empty string after trimming.
- `body` must be a non-empty string after trimming.
- `body` is clamped to a v1 maximum, default `8000` characters, and the draft
  receives a warning when truncated.
- If `{SKILLS_DIR}/{name}/SKILL.md` already exists, the draft is a conflict and
  is not enqueued.
- Invalid drafts are returned under `invalid_drafts`; they are not enqueued.

Forbidden fields in Hermes draft items:

- `path`
- `absolute_path`
- `content`
- `frontmatter`
- `overwrite`
- `existing_skill`
- `install`
- `tools`
- `agent_config`
- `writer`
- `pending_id`

Presence of forbidden fields raises `HermesSchemaError`, matching the current
strict behavior for forbidden Hermes write-control fields.

## Skill Rendering

OpenAgentd renders new skill content as:

```markdown
---
name: <name>
description: <description>
---
<body>
```

Rules:

- Hermes does not provide authoritative frontmatter.
- YAML is rendered by OpenAgentd with `yaml.safe_dump(sort_keys=False,
  allow_unicode=True)`.
- `name` and `description` are always sourced from the validated proposal
  fields.
- Rendered content uses one newline after the closing frontmatter delimiter
  before the body, matching the agreed `{SKILLS_DIR}/{name}/SKILL.md`
  structure.
- The body is normalized to one trailing newline.
- No scripts, references, assets, or sibling files are created in v1.

## Skill Draft Queue

Add a new service, for example `app/services/hermes_skill_drafting.py`.

The queue is:

- In-memory only.
- Per-process.
- Scoped by `session_id`.
- Protected by `asyncio.Lock`.
- Limited to `50` pending entries per session.
- Cleared on server restart.

Statuses:

- `pending`
- `approved`
- `rejected`
- `failed`

Terminal statuses:

- `approved`
- `rejected`
- `failed`

Queue limit behavior:

- When enqueueing would exceed `50` pending drafts for a session, the oldest
  pending drafts in that session are marked `rejected`.
- Reject reason: `superseded_by_queue_limit`.
- `hermes_skill_draft` reports `evicted_count` in its output.

No dedupe in v1:

- Repeated `hermes_skill_draft` calls may create multiple pending drafts for
  the same name if the skill does not yet exist on disk.
- Approve revalidation still prevents overwriting an existing skill.
- The lead can reject stale pending drafts manually.

## Approval Semantics

`hermes_skill_pending_approve`:

1. Requires `_state.metadata["session_id"]`.
2. Finds the pending entry for the current session.
3. Rejects not found or cross-session ids.
4. Rejects terminal entries.
5. Revalidates name, description, and body.
6. Rechecks that `{SKILLS_DIR}/{name}/SKILL.md` does not exist.
7. Renders `SKILL.md`.
8. Writes through `agent_fs.write_skill(name, content, create=True)`.
9. Calls `team_manager.invalidate_skill_cache()`.
10. Marks the entry `approved`.
11. Returns a short success message with the skill name and relative target.

No overwrite is exposed. If the skill appears on disk between enqueue and
approve, approval marks the entry `failed` and returns a clear conflict/write
error.

Approve does not:

- call Hermes
- call `load_skill`
- modify any agent `.md` config
- call `team_configure`
- add the skill to any `skills[]` list

## Rejection Semantics

`hermes_skill_pending_reject`:

- Requires `_state.metadata["session_id"]`.
- Marks one pending entry `rejected`.
- Stores an optional reason in memory.
- Does not write to disk.
- Does not record the reject reason in observability.

## Tools

Add lead-only builtin tools:

- `hermes_skill_draft`
- `hermes_skill_pending_list`
- `hermes_skill_pending_approve`
- `hermes_skill_pending_reject`

### `hermes_skill_draft`

Inputs:

- `task: str`
- `context: str = ""`
- `max_drafts: int = 3`
- injected `_state`

Behavior:

- Requires `session_id` before calling Hermes.
- Calls Hermes `POST /v1/skill-drafts`.
- Enqueues valid drafts.
- Returns JSON with:
  - `summary`
  - `warnings`
  - `model_info`
  - `evicted_count`
  - `valid_drafts` with `pending_id` and preview
  - `conflicts`
  - `invalid_drafts`

Preview includes:

- `name`
- `description`
- bounded `body_preview`
- `body_length`
- `body_truncated`
- `body_preview_truncated`
- `rationale`
- `warnings`

Preview does not include unbounded body text. It includes a bounded
`body_preview` so the lead can review the draft without exposing full text into
observability. The pending entry stores the full normalized body that will be
written on approve. Default `body_preview` limit is `4000` characters.

### `hermes_skill_pending_list`

Inputs:

- `include_non_pending: bool = False`
- injected `_state`

Behavior:

- Lists current session entries.
- Defaults to pending only.
- Output is compact and LLM-readable.
- Includes `pending_id`, status, name, description, body length, truncation
  flag, bounded `body_preview`, body preview truncation flag, and warnings.
- Does not include full body, body preview, or reject reason in telemetry.

### `hermes_skill_pending_approve`

Inputs:

- `pending_id: str`
- injected `_state`

Behavior:

- Approves one pending draft.
- Writes a new skill file through `agent_fs.write_skill(..., create=True)`.
- Invalidates skill cache.
- Does not call Hermes.
- Does not expose overwrite or update.

### `hermes_skill_pending_reject`

Inputs:

- `pending_id: str`
- `reason: str | None = None`
- injected `_state`

Behavior:

- Rejects one pending draft.
- Does not write files.

## Loader And Registry

Register the new tools in:

- `app/agent/tools/builtin/__init__.py`
- `app/agent/loader.py`

Lead agents receive all four tools automatically.

Member agents do not receive them. If a member lists any of these tool names in
YAML frontmatter, loader handling should skip them and log a warning rather
than granting them. Lead frontmatter entries are deduped.

This is slightly stricter than older lead-only tool skip behavior that silently
skips. The warning helps detect attempted manual grants of a write-capable
skill approval surface.

## Observability And Privacy

Instrument with the existing Second Brain tool observability helper.

Tool names:

- `hermes_skill_draft`
- `hermes_skill_pending_list`
- `hermes_skill_pending_approve`
- `hermes_skill_pending_reject`

Outcomes:

- Draft:
  - `enqueued`
  - `missing_session`
  - `unavailable`
  - `timeout`
  - `connection_error`
  - `schema_error`
- List:
  - `listed`
  - `empty`
  - `missing_session`
- Approve:
  - `approved`
  - `missing_session`
  - `not_found`
  - `already_processed`
  - `write_error`
  - `approval_error`
- Reject:
  - `rejected`
  - `missing_session`
  - `not_found`
  - `already_processed`
  - `approval_error`

Low-risk attributes only:

- `skill.name`
- `skill.body_length`
- `skill.description_length`
- `skill.draft_count`
- `skill.pending_count`
- `skill.evicted_count`
- booleans such as `skill.body_truncated`

Do not record:

- skill body content
- full description text
- reject reason
- pending id
- raw Hermes context
- task text
- rendered `SKILL.md` content

## Error Semantics

Service-level errors should be typed and specific:

- `HermesSkillDraftError`
- `HermesSkillDraftNotFoundError`
- `HermesSkillDraftAlreadyProcessedError`
- `HermesSkillDraftWriteError`

Approval write failures:

- Existing skill at approve time: terminal `failed`, clear conflict message.
- Invalid name/path: terminal `failed`, clear validation message.
- Atomic write failure: terminal `failed`, clear write error.
- Cache invalidation failure should be treated as an approval failure only if it
  raises. The existing `team_manager.invalidate_skill_cache()` has no expected
  normal failure mode.

The implementation should not catch broad `Exception` around Hermes schema
normalization or skill filesystem validation.

## Out Of Scope

- API routes.
- UI.
- SQLite/DB persistence.
- Batch approve or reject.
- Updating existing skills.
- Overwrite.
- Deleting, renaming, or moving skills.
- Creating skill sibling files, assets, references, or scripts.
- Installing external skills.
- Granting the new skill to any agent.
- Calling `load_skill` after approve.
- Calling `team_configure`.
- Hermes writing files directly.
- Generalizing the vault Hermes approval queue.

## Test Plan

Service tests first:

- Normalize valid Hermes skill draft response.
- Clamp `max_drafts` and context.
- Reject non-list `skill_drafts`.
- Reject forbidden fields.
- Mark existing on-disk skill names as conflicts and do not enqueue them.
- Report invalid drafts for bad name, empty description, and empty body.
- Truncate oversized body with warning.
- Render `SKILL.md` with OpenAgentd-owned frontmatter.
- Enqueue valid drafts and create opaque pending ids.
- List pending entries scoped by `session_id`.
- Queue limit rejects oldest pending entry with `superseded_by_queue_limit`.
- Approve writes a new skill through `agent_fs.write_skill(..., create=True)`.
- Approve invalidates skill cache.
- Approve fails clearly when skill appears after enqueue and does not overwrite.
- Reject marks entry rejected without writing.
- Double approve allows exactly one winner.
- Approve rejected/failed entry is refused.
- Approve does not call Hermes.

Tool tests:

- `hermes_skill_draft` requires `session_id` before calling Hermes.
- `hermes_skill_draft` enqueues valid drafts and returns pending ids.
- `hermes_skill_draft` output includes conflicts, invalid drafts, warnings, and
  `evicted_count`.
- Repeated draft calls create multiple pending entries.
- Hermes unavailable/timeout/connection/schema errors map to specific messages.
- `hermes_skill_pending_list` formats output clearly.
- `hermes_skill_pending_approve` writes a skill successfully.
- `hermes_skill_pending_approve` returns clear existing-skill/write errors.
- `hermes_skill_pending_reject` rejects successfully.
- Observability success/error paths record outcomes without leaking body,
  description text, pending id, or reject reason.

Loader tests:

- Builtin registry includes the four new tools.
- Lead agents receive the four new tools.
- Member agents do not receive the four new tools.
- Member frontmatter listing any new tool is skipped and logged.
- Lead frontmatter listing any new tool is deduped.

Regression:

- Existing Hermes write proposal tests pass.
- Existing Hermes approval queue tests pass.
- Existing Hermes query tests pass.
- Existing skill loader tests pass.
- Existing `agent_fs` tests pass.
- Existing loader tests pass.

## Verification Commands

```powershell
uv run pytest tests/services/test_hermes.py tests/services/test_hermes_skill_drafting.py --no-cov -q
uv run pytest tests/agent/tools/test_hermes_skill_tools.py tests/agent/tools/test_skill_loader.py --no-cov -q
uv run pytest tests/services/test_agent_fs.py tests/services/test_hermes_approval.py tests/agent/tools/test_hermes_propose_tool.py tests/agent/tools/test_hermes_pending_tools.py tests/agent/tools/test_hermes_query_tool.py tests/agent/test_loader.py --no-cov -q
uv run ruff check app/services/hermes.py app/services/hermes_skill_drafting.py app/agent/tools/builtin/hermes_skill.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_hermes.py tests/services/test_hermes_skill_drafting.py tests/agent/tools/test_hermes_skill_tools.py tests/agent/test_loader.py
uv run ruff format --check app/services/hermes.py app/services/hermes_skill_drafting.py app/agent/tools/builtin/hermes_skill.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_hermes.py tests/services/test_hermes_skill_drafting.py tests/agent/tools/test_hermes_skill_tools.py tests/agent/test_loader.py
uv run ty check app/services/hermes.py app/services/hermes_skill_drafting.py app/agent/tools/builtin/hermes_skill.py app/agent/loader.py
```

## Review Notes

Ask architecture/security review to focus on:

- Whether a separate skill draft queue is the right boundary.
- No Hermes direct write path.
- No raw filesystem write in the tool layer.
- Skill name/path validation and no overwrite semantics.
- Cache invalidation after approve.
- Member-agent exclusion and warning behavior.
- Observability privacy.
- Whether body preview should be omitted entirely or bounded in v1 output.
