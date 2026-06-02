# Vault Update v1 Design

## Summary

Vault Update v1 adds a controlled lead-agent tool for updating existing
Obsidian vault notes. It closes the main Second Brain gap between read/search
and new-note writes without exposing raw filesystem writes, note movement,
batch mutation, or Hermes direct writes.

The design keeps v1 deliberately narrow:

- Tool-only, lead-agent only.
- No API, UI, database, persistence queue, or batch operation.
- No delete, rename, move, folder change, slug change, or direct `_index.md`
  editing.
- No Hermes direct write path.
- No approval queue integration in v1.
- Existing-note update only; `vault_write` remains the new-note creation path.

## Existing Context

Current code boundaries:

- `app/services/vault_gatekeeper.py` is the official in-process writer boundary.
  It validates standard vault paths, serializes writes through an `asyncio.Lock`,
  writes atomically, and updates folder indexes for new notes.
- `vault_write` creates new notes through the gatekeeper and does not expose
  `writer` or `overwrite`.
- `vault_read` can read a validated note path but does not yet expose an update
  token.
- `vault_ingest` already preserves human/custom frontmatter while normalizing
  v7 metadata, and writes under the gatekeeper lock when applying changes.
- Lead-only tool injection is explicit in `app/agent/loader.py`; members do not
  receive vault tools automatically.

Vault Update v1 should extend these patterns rather than create a second writer
lane.

## Chosen Approach

Use a structured update tool with an optimistic read token.

Flow:

1. Lead agent calls `vault_read(folder, slug, include_update_token=True)`.
2. `vault_read` returns the note content plus an update token derived from the
   current file bytes: `sha256:<hex>`.
3. Lead agent calls `vault_update(...)` with `expected_sha256`.
4. Gatekeeper validates path, takes its lock, reads the current file, recomputes
   the hash, and rejects if the file changed.
5. If the hash matches, gatekeeper parses frontmatter, applies the structured
   update, sets `updated_at` and `writer`, then writes atomically.

This gives a lightweight lost-update guard without a database and keeps the
agent from blindly overwriting notes it has not just read.

## Alternatives Considered

### Full Note Replace

The tool would accept full Markdown and overwrite the existing note after a
hash check.

This is simple, but too close to raw filesystem write. It also makes it easy for
an LLM to accidentally drop custom frontmatter or human-authored content. This
approach is rejected for v1.

### Diff Or Patch Apply

The tool would accept a patch, find/replace block, or structured text diff.

This can produce small edits, but patch conflict semantics are harder to make
clear and robust. Markdown whitespace and context matching can become flaky.
This is deferred until after the basic controlled update boundary is proven.

### Structured Update With Read Token

This is the selected approach. It provides a clear agent workflow, strong enough
lost-update protection for v1, small implementation surface, and good alignment
with the existing gatekeeper lock and atomic write path.

## Tool Contract

Add a new builtin tool: `vault_update`.

Inputs:

- `folder: str`
- `slug: str`
- `expected_sha256: str`
- `replace_body: str | None = None`
- `append_body: str | None = None`
- `status: str | None = None`
- `tags: list[str] | None = None`
- `source_refs: list[str] | None = None`
- `relations: list[str] | None = None`
- `last_summarized_at: str | None = None`
- injected `_state`

Rules:

- `expected_sha256` must match the current file hash and should be supplied as
  the raw hex digest or `sha256:<hex>`. The service normalizes both forms.
- Exactly one of `replace_body` or `append_body` may be provided.
- At least one body or metadata update must be requested.
- `replace_body`, when used, replaces only the Markdown body after frontmatter.
- `append_body`, when used, appends Markdown to the existing body with a stable
  separator.
- Metadata updates are restricted to the explicit allowlist:
  - `status`
  - `tags`
  - `source_refs`
  - `relations`
  - `last_summarized_at`
- The service always updates:
  - `updated_at`
  - `writer`

Read-only in v1:

- `id`
- `created_at`
- `title`
- `type`
- `folder`
- `slug`

`title` and `type` stay read-only because folder indexes include those values.
Allowing title/type changes in v1 would require index rewrite and rollback
semantics for existing notes. That belongs in a later phase.

## `vault_read` Token Extension

Extend `vault_read` with:

- `include_update_token: bool = False`

When false, output remains compatible with the current behavior.

When true, append a small machine-readable footer after the returned content:

```text

[vault_update_token: sha256:<hex>]
```

The token is computed from the full raw note content before any display
truncation or frontmatter hiding. If the requested `max_chars` truncates the
displayed body, the token still represents the full current file. The tool
should make this clear by keeping the existing truncation marker and appending
the token footer after it.

## Service Boundary

Extend `VaultGatekeeper` with an update method rather than creating a new writer
service.

New dataclasses:

- `VaultUpdateIntent`
- `VaultUpdateResult`

New errors:

- `VaultUpdateConflictError`
- `VaultNoteNotFoundError`
- `VaultMalformedNoteError`

The update method:

1. Builds `rel_path = f"{folder}/{slug}.md"`.
2. Calls `validate_vault_note_path`.
3. Acquires the existing gatekeeper lock.
4. Reads current raw content.
5. Computes current SHA-256.
6. Compares against normalized `expected_sha256`.
7. Splits YAML frontmatter with `split_vault_note_frontmatter`.
8. Requires valid existing frontmatter for v1.
9. Applies only allowed metadata/body changes.
10. Sets `updated_at` to current UTC ISO timestamp.
11. Sets `writer` from injected agent name.
12. Renders frontmatter with `yaml.safe_dump(sort_keys=False, allow_unicode=True)`.
13. Writes atomically through the existing `_atomic_write`.

No index update happens in v1 because `title`, `type`, `folder`, and `slug` are
not mutable.

## Frontmatter Preservation

The update path must preserve custom frontmatter keys.

Implementation rule:

- Parse existing metadata into a dict.
- Copy it before applying changes.
- Mutate only allowlisted fields plus `updated_at` and `writer`.
- Dump the resulting full dict back to YAML.

This may normalize YAML formatting, which is acceptable for v1. The semantic
requirement is preserving unknown/custom keys and their values.

## Body Update Semantics

`replace_body`:

- Must contain non-empty Markdown after trimming.
- Replaces the existing Markdown body exactly as the new body, with one trailing
  newline in the rendered note.

`append_body`:

- Must contain non-empty Markdown after trimming.
- Appends to the existing body using:

```text

<existing body stripped of trailing whitespace>

---

<append body stripped>
```

The separator is intentionally simple and visible in Obsidian. Section-aware
append belongs in a later phase.

## Error Semantics

Service errors should be typed and precise:

- Missing note: `VaultNoteNotFoundError`
- Invalid folder/slug/path: `VaultPathError`
- Missing or malformed `expected_sha256`: `ValueError`
- Hash mismatch: `VaultUpdateConflictError`
- Missing/malformed frontmatter: `VaultMalformedNoteError`
- Both `replace_body` and `append_body`: `ValueError`
- No requested changes: `ValueError`
- Empty replacement/append body: `ValueError`
- Write failure: `VaultWriteError`

The service should not catch broad `Exception`.

The tool may catch these typed errors and return stable, agent-readable strings.
It should avoid generic error messages.

## Tool Output

Success:

```text
Vault note updated at 20-topics/example.md
```

Conflict:

```text
Update conflict at vault/20-topics/example.md: note changed since last read. Read it again and retry with the new update token.
```

Malformed note:

```text
Cannot update vault/20-topics/example.md: note frontmatter is missing or malformed. Run ingest/reconcile first.
```

The tool must not echo note body, token/hash, title, tags, source refs, or
relations in observability attributes.

## Observability

Instrument `vault_update` through the existing Second Brain tool observability
helper.

Outcomes:

- `updated`
- `conflict`
- `not_found`
- `invalid_path`
- `invalid_request`
- `malformed_frontmatter`
- `write_error`

Status:

- `ok` for `updated`
- `error` for all other outcomes

Low-risk attributes only:

- `vault.folder`
- `vault.path`
- `vault.replace_body_length`
- `vault.append_body_length`
- `vault.metadata_fields_count`
- `vault.has_replace_body`
- `vault.has_append_body`

Do not record:

- note body
- update token/hash
- title
- tags values
- source refs values
- relations values

## Loader And Registry

Register `vault_update` in:

- `app/agent/tools/builtin/__init__.py`
- `app/agent/loader.py`

Lead agents receive it automatically with the other Second Brain tools.

Member agents do not receive it automatically, and listing it in member
frontmatter should still not grant the tool.

Lead frontmatter entries for `vault_update` are deduped the same way as
`vault_write`, `vault_read`, and `vault_search`.

## Out Of Scope

- API route.
- UI.
- Database persistence.
- Batch update.
- Rename, move, delete, or folder change.
- Update `_index.md`.
- Change `title` or `type`.
- Hermes direct writes.
- Hermes update proposals.
- Approval queue for updates.
- Section-aware Markdown editing.
- Diff/patch application.
- Raw full-file overwrite tool.

## Test Plan

Service tests first:

- Compute update token from raw note content.
- Update succeeds when `expected_sha256` matches.
- Stale hash rejects without writing.
- Missing note rejects without creating a file.
- Invalid path/folder/slug rejects through existing path validation.
- Missing frontmatter rejects.
- Malformed frontmatter rejects.
- Custom frontmatter keys are preserved.
- `replace_body` replaces only body and preserves allowed/read-only metadata.
- `append_body` appends with the v1 separator.
- Allowed metadata fields update correctly.
- `updated_at` and `writer` are set on every successful update.
- Both `replace_body` and `append_body` reject.
- No requested changes rejects.
- Concurrent updates with the same token allow one winner and one conflict.
- Atomic write failure maps to `VaultWriteError`.

Tool tests:

- `vault_read(include_update_token=True)` returns a token footer.
- Existing `vault_read` default output remains unchanged.
- `vault_update` success uses injected writer.
- Conflict/not-found/path/malformed/request/write errors return clear messages.
- Observability records success and error outcomes without sensitive attrs.

Loader tests:

- Builtin registry includes `vault_update`.
- Lead agents receive `vault_update`.
- Member agents do not receive `vault_update`.
- Lead frontmatter dedupes `vault_update`.
- Member frontmatter listing `vault_update` does not grant it.

Regression tests:

- Existing vault gatekeeper tests pass.
- Existing `vault_write`, `vault_read`, `vault_search` tests pass.
- Loader tests pass.
- Second Brain observability tests pass.

## Verification Commands

```powershell
uv run pytest tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_update_tool.py tests/agent/tools/test_vault_read_tool.py --no-cov -q
uv run pytest tests/agent/tools/test_vault_write_tool.py tests/agent/tools/test_vault_search_tool.py tests/agent/test_loader.py --no-cov -q
uv run pytest tests/services/test_observability_service.py tests/api/routes/test_observability_route.py --no-cov -q
uv run ruff check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_update.py app/agent/tools/builtin/vault_read.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_update_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/test_loader.py
uv run ruff format --check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_update.py app/agent/tools/builtin/vault_read.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_update_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/test_loader.py
uv run ty check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_update.py app/agent/tools/builtin/vault_read.py app/agent/loader.py
```

## Review Notes

This is a write-path feature with higher blast radius than new-note creation.
Before implementation, ask an architecture reviewer to check:

- Lost-update semantics.
- Frontmatter preservation.
- Read-only `title/type/id/created_at` boundary.
- No hidden raw overwrite path.
- No Hermes direct write coupling.
- Error semantics and observability privacy.
