---
title: Wiki Memory
description: Three-tier memory system — raw sessions (DB) → agent notes (wiki/notes/) → consolidated knowledge (wiki topics). Maintained by the dream agent.
status: stable
updated: 2026-05-13
---

# Wiki Memory

**Sources:** `app/services/wiki.py`, `app/services/dream.py`, `app/services/dream_scheduler.py`, `app/agent/hooks/wiki_injection.py`, `app/agent/tools/builtin/wiki_search.py`, `app/agent/tools/builtin/note.py`

Three tiers:

| Tier | What | Where |
|------|------|-------|
| Raw | All chat messages | SQLite (`session_messages`) |
| Episodic | Agent notes written mid-session | `wiki/notes/` |
| Wiki | Consolidated durable knowledge | `wiki/topics/`, `wiki/USER.md`, `wiki/INDEX.md` |

---

## Directory layout

```
{OPENAGENTD_WIKI_DIR}/
  USER.md           # stable user facts — injected into every prompt
  INDEX.md          # dream-maintained table of contents (user-editable)
  topics/           # durable knowledge base
    {slug}.md
  notes/            # agent notes (one file per day, append-only)
    {date}.md
```

`OPENAGENTD_WIKI_DIR` defaults to `.openagentd/wiki/` (dev) or `~/.local/share/openagentd-wiki/` (prod).

`USER.md` and `INDEX.md` cannot be deleted via the API — only overwritten.

---

## Components

### `WikiInjectionHook`

`app/agent/hooks/wiki_injection.py` — injects `USER.md` into the system prompt on every LLM call. Topics are never auto-injected — the agent calls `wiki_search` explicitly.

### `note` tool

`app/agent/tools/builtin/note.py` — appends a `## HH:MM UTC` entry to `wiki/notes/{date}.md`. One file per day, no frontmatter. The only write path to `wiki/notes/`.

### `wiki_search` tool

`app/agent/tools/builtin/wiki_search.py` — BM25 keyword search over `wiki/topics/`.

### Dream agent

`app/services/dream.py` — reads unprocessed sessions and note files, runs the dream agent with a fresh instance per item, writes to `topics/`, `USER.md`, `INDEX.md`. Tracks processed items in `dream_log` / `dream_notes_log`.

- Sessions with no messages are auto-skipped (marked processed, no batch slot consumed). The drain is capped at `max(100, batch_size * 100)` per run so a backlog of thousands of empties does not produce a commit storm.
- Renaming the dream agent via `dream.md` (`name:` field) automatically updates the filter — dream still cannot feed itself.
- The dream agent's sandbox workspace is set to `wiki_root()` so `ls(".")`, `read("USER.md")` etc. resolve correctly without a `wiki/` prefix.
- Sessions and notes are **interleaved** (session, note, session, …) up to `batch_size` so a backlog of one type never starves the other.
- Each item is wrapped in `asyncio.wait_for(..., timeout=timeout_seconds)` (default `300s`). On timeout or any LLM error the item is **not** marked processed and will be retried on the next run.
- Transcripts are capped at `DEFAULT_MAX_PROMPT_CHARS = 60_000` with middle elision; per-message cap is `4_000` chars.
- A module-level `asyncio.Lock` serialises concurrent runs so manual `/api/dream/run` cannot race the scheduler and violate the `dream_log.session_id` UNIQUE constraint.
- `dream.md` is parsed once per run; the agent is loaded once and reused across all items in the batch via the `_sandbox_ctx` ContextVar (reset in a `finally` block).
- **`wiki/notes/` is append-only and dream MUST NOT modify or delete files in it.** This is enforced by the system prompt — dream is given `read`, `write`, `edit`, `rm`, `ls`, `wiki_search` but is instructed to use `edit`/`rm`/`write` only against `USER.md`, `INDEX.md`, and `topics/`.

`app/services/dream_scheduler.py` — cron scheduler.

- `start()` is idempotent — a second call while running is a no-op (no leaked task).
- `reload()` (called from `PUT /api/dream/config`) takes effect without restart. If a fire is in progress it **does not** block on it: the old loop is orphaned (held in a module-level set so CPython's weak-ref task GC doesn't collect it mid-synthesis) and a fresh scheduler task takes over immediately.
- `stop()` cancels the loop **and** awaits the in-flight `_fire()` so callers can rely on a clean shutdown — the shield protects synthesis from mid-run cancellation, so `stop()` can take up to `timeout_seconds * batch_size` to return when a fire is active.
- `start`/`stop`/`reload` are serialised through `_lifecycle_lock` so concurrent `PUT /api/dream/config` requests cannot both spawn fresh scheduler tasks.

---

## `wiki/notes/` format

Plain markdown, no frontmatter. One file per day — all sessions append to it.

```markdown
## 14:32 UTC

User prefers Vim. Always use terminal-based editors.

## 14:45 UTC

Decided to use SQLite WAL mode for performance.
```

---

## `wiki/topics/{slug}.md` format

Required frontmatter (dream agent only):

```markdown
---
description: One-sentence summary (drives BM25 search relevance).
tags: [tag1, tag2]
updated: YYYY-MM-DD
---
```

---

## Dream agent config

`.openagentd/config/dream.md` — the dream agent's working directory is `wiki_root()`. Use bare paths (`USER.md`, `topics/slug.md`) not `wiki/USER.md`.

`read`, `write`, `edit`, `rm`, `ls`, `wiki_search` are always injected (the `_REQUIRED_TOOLS` set in `app/services/dream.py`) regardless of what `tools:` lists in the frontmatter. Dream-specific frontmatter fields:

| Field | Default | Purpose |
|-------|---------|---------|
| `enabled` | `false` | Master switch — when `false`, items are marked processed without synthesis. |
| `schedule` | `0 2 * * *` | Cron expression for the scheduler. |
| `batch_size` | `1` | Items per `run_dream()` call (sessions and notes interleaved). |
| `timeout_seconds` | `300` | Per-item LLM timeout. Items that exceed it are not marked processed and retry next run. |

Configure via `/settings/dream` or edit the file directly; `PUT /api/dream/config` reloads the scheduler live.

---

## Data flow

```
Agent mid-session
  → note tool appends to wiki/notes/{date}.md

Every LLM call
  → WikiInjectionHook injects USER.md

Agent needs past context
  → calls wiki_search → BM25 over topics/

Dream runs (cron or manual, serialised by _run_lock)
  → empty sessions auto-skipped (no batch slot consumed)
  → sessions + notes interleaved up to batch_size
  → one dream agent loaded for the whole batch, sandbox = wiki_root()
  → per-item asyncio.wait_for(timeout_seconds)
  → writes topics/, USER.md, INDEX.md (never wiki/notes/)
  → marks processed in dream_log / dream_notes_log (per-item commit)
  → on timeout or error → no mark → retries next run
```

---

## Path validation rules (`validate_wiki_path`)

All client-supplied paths go through `validate_wiki_path` in `app/services/wiki.py` before any disk operation. Rules:

- Must be relative (no leading `/` or `~`).
- Must end in `.md`.
- No `..` or `.` segments — checked against the **raw string** (not `Path.parts`) because `Path` silently normalises `topics/./test.md` → `('topics', 'test.md')` before the parts check runs.
- Root-level: only `USER.md` and `INDEX.md` are accepted.
- Sub-directory: only `topics/` and `notes/`.
- Max depth: 2 components (`dir/file.md`).
- Final `Path.resolve()` must remain inside `wiki_root()` (symlink-escape guard).

---

## What lives where

| Concern | Location |
|---------|---------|
| Wiki file ops, path validation | `app/services/wiki.py` |
| Data types (`WikiFileInfo`, `WikiTree`, `WikiPathError`) | `app/services/wiki.py` |
| Dream runner + empty-session filter | `app/services/dream.py` |
| Dream config parser (`parse_dream_md`, `DreamAgentConfig`) | `app/services/dream.py` |
| Dream scheduler (cron, `reload()`) | `app/services/dream_scheduler.py` |
| USER.md injection | `app/agent/hooks/wiki_injection.py` |
| Note writing | `app/agent/tools/builtin/note.py` |
| Topic search (BM25) | `app/agent/tools/builtin/wiki_search.py` |
| DB tables | `app/models/chat.py` (`DreamLog`, `DreamNotesLog`) |
| Migration | `app/migrations/versions/00000004_create_dream_log.py` |
| Seed defaults | `app/core/wiki_seed.py`, `seed/dream.md` |
| Manual scripts | `manual/wiki.py`, `manual/note.py`, `manual/dream.py` |
