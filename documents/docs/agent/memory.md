---
title: Wiki Memory
description: Wiki memory system - raw sessions and notes are consolidated into a Karpathy-style LLM wiki by the dream agent.
status: stable
updated: 2026-05-17
---

# Wiki Memory

**Sources:** `app/services/wiki.py`, `app/services/dream.py`, `app/services/dream_scheduler.py`, `app/agent/hooks/wiki_injection.py`, `app/agent/tools/builtin/wiki_search.py`, `app/agent/tools/builtin/note.py`

OpenAgentd uses a wiki memory system:

| Layer | What | Where |
|------|------|-------|
| Raw | All chat messages | SQLite (`session_messages`) |
| Notes | Agent/user notes written mid-session | `wiki/notes/` |
| Wiki | Consolidated durable knowledge | `wiki/topics/`, `wiki/entities/`, `wiki/sources/`, `wiki/comparisons/`, `wiki/USER.md`, `wiki/INDEX.md` |

The wiki layout follows Karpathy's LLM-Wiki pattern: every non-trivial source gets a source page, durable concepts and entities are promoted into interlinked pages, and each page carries source traceability in frontmatter.

---

## Directory layout

```text
{OPENAGENTD_WIKI_DIR}/
  USER.md           # pure YAML durable user facts, injected into every prompt
  INDEX.md          # dream-maintained table of contents
  LOG.md            # service-managed append-only dream/lint log
  LINT.md           # latest dream lint report
  topics/           # concept pages, kept as the legacy name for compatibility
    {slug}.md
  entities/         # people, tools, products, organizations, concrete things
    {slug}.md
  sources/          # one summary page per ingested source
    {slug}.md
  comparisons/      # X-vs-Y comparison pages
    {slug}.md
  notes/            # agent notes, one file per day, append-only input
    {date}.md
```

`OPENAGENTD_WIKI_DIR` defaults to `.openagentd/wiki/` in dev or `~/.local/share/openagentd-wiki/` in prod.

`USER.md`, `INDEX.md`, and `LOG.md` cannot be deleted via the API. `LINT.md` can be deleted because lint regenerates it.

---

## Components

### `WikiInjectionHook`

`app/agent/hooks/wiki_injection.py` injects `USER.md` into the system prompt on every LLM call. Knowledge pages are never auto-injected; the agent calls `wiki_search` explicitly.

`USER.md` is intended to be pure YAML, not markdown prose. The default seed is:

```yaml
identity: {}
preferences: []
working_style: []
projects: []
```

### `note` tool

`app/agent/tools/builtin/note.py` appends a `## HH:MM UTC` entry to `wiki/notes/{date}.md`. Notes are plain markdown with one file per day and no frontmatter. This is the only write path to `wiki/notes/`.

### `wiki_search` tool

`app/agent/tools/builtin/wiki_search.py` runs BM25 keyword search over `topics/`, `entities/`, `sources/`, and `comparisons/`.

### Dream agent

`app/services/dream.py` reads unprocessed sessions and note files, runs the dream agent with a fresh instance per item, and writes durable output to `USER.md`, `INDEX.md`, `topics/`, `entities/`, `sources/`, and `comparisons/`. The service appends `LOG.md` entries after runs. Processed items are tracked in `dream_log` and `dream_notes_log`.

- Sessions with no messages are auto-skipped and marked processed without consuming a batch slot.
- Empty-session draining is capped at `max(100, batch_size * 100)` per run.
- The dream agent name comes from `dream.md`, so renaming the dream agent updates the self-filter.
- The dream agent sandbox workspace is `wiki_root()`, so `read("USER.md")` and `write("topics/slug.md")` use bare wiki-relative paths.
- Sessions and notes are interleaved as session, note, session, note up to the run cap.
- Scheduled runs process up to `batch_size`; manual runs use `drain=True` and process all pending non-empty items.
- Each item is wrapped in `asyncio.wait_for(..., timeout=timeout_seconds)`.
- On timeout or LLM error, the item is not marked processed and retries on the next run.
- Transcripts are capped at `DEFAULT_MAX_PROMPT_CHARS = 60_000` with middle elision; per-message cap is `4_000` chars.
- `_run_lock` serializes in-process dream and lint runs.
- Wiki context is rebuilt before each item so later items in a drain can see pages created by earlier items.
- `wiki/notes/` is append-only input and dream must not modify or delete it.
- `LOG.md` is service-managed and dream must not edit it.

`app/services/dream_scheduler.py` runs the scheduler.

- `start()` is idempotent and only starts when `dream.md` has `enabled: true`.
- `enabled: false` disables scheduled runs only; manual runs still work when a model is configured.
- The scheduler reparses `dream.md` on each iteration, so direct file edits to schedule or `enabled` are picked up without restart.
- `reload()` from `PUT /api/dream/config` takes effect without restart.
- `stop()` cancels the loop and awaits any in-flight fire for clean shutdown.

---

## `wiki/notes/` format

Plain markdown, no frontmatter. One file per day; all note tool calls append to that day's file.

```markdown
## 14:32 UTC

User prefers Vim. Always use terminal-based editors.

## 14:45 UTC

Decided to use SQLite WAL mode for performance.
```

---

## Knowledge page format

Every file under `topics/`, `entities/`, `sources/`, and `comparisons/` should have YAML frontmatter:

```markdown
---
description: One-sentence summary used by search and the UI.
tags: [tag1, tag2]
updated: YYYY-MM-DD UTC
confidence: high | medium | low
sources:
  - session-a1b2c3d4
  - note-2026-05-17
related:
  - "[[related-slug]]"
---
```

`sources/{Source-Slug}.md` is mandatory for every non-trivial source. Session source slugs use `session-<last-8-uuid-hex>`. Note source slugs use `note-<filename-stem>`.

Body content should use Obsidian-style wikilinks such as `[[asyncio-cancellation]]` and `[[session-a1b2c3d4]]`.

---

## Dream agent config

`.openagentd/config/dream.md` uses the same markdown-plus-frontmatter format as normal agents. The dream agent working directory is `wiki_root()`, so prompts should use bare paths such as `USER.md`, `sources/session-a1b2c3d4.md`, and `topics/auth.md`.

`read`, `write`, `edit`, `rm`, `ls`, and `wiki_search` are always injected through `_REQUIRED_TOOLS` in `app/services/dream.py`, regardless of the `tools:` field in frontmatter.

| Field | Default | Purpose |
|-------|---------|---------|
| `enabled` | `false` | Scheduler switch. Manual runs still work when a model is configured. |
| `schedule` | `0 2 * * *` | Cron expression in UTC. |
| `batch_size` | `1` | Items per scheduled run. Sessions and notes are interleaved. |
| `timeout_seconds` | `300` | Per-item LLM timeout. Items that exceed it retry next run. |

Configure via `/settings/dream` or edit the file directly. `PUT /api/dream/config` reloads the scheduler live.

---

## Data flow

```text
Agent mid-session
  -> note tool appends to wiki/notes/{date}.md

Every LLM call
  -> WikiInjectionHook injects USER.md

Agent needs past context
  -> calls wiki_search
  -> BM25 over topics/, entities/, sources/, comparisons/

Dream runs by schedule
  -> scheduler fires run_dream(drain=False)
  -> empty sessions auto-skipped
  -> sessions + notes interleaved up to batch_size
  -> wiki context rebuilt before each item
  -> per-item fresh dream agent, sandbox = wiki_root()
  -> writes source/topic/entity/comparison pages, USER.md, INDEX.md
  -> service appends LOG.md
  -> marks processed in dream_log / dream_notes_log
  -> timeout or error leaves item unprocessed for retry

Manual dream run
  -> POST /api/dream/run or manual.dream run --direct
  -> run_dream(drain=True)
  -> drains pending non-empty items in one call

Dream lint
  -> POST /api/dream/lint or manual.dream lint
  -> inspects current wiki
  -> writes LINT.md only
  -> service appends LOG.md
```

---

## Path validation rules (`validate_wiki_path`)

All client-supplied paths go through `validate_wiki_path` in `app/services/wiki.py` before any disk operation. Rules:

- Must be relative, with no leading `/` or `~`.
- Must end in `.md`.
- No `..` or `.` segments.
- Root-level files are limited to `USER.md`, `INDEX.md`, `LOG.md`, and `LINT.md`.
- Sub-directories are limited to `topics/`, `entities/`, `sources/`, `comparisons/`, and `notes/`.
- Paths are limited to two components, such as `topics/auth.md`.
- Final `Path.resolve()` must remain inside `wiki_root()` to block symlink escapes.

---

## What lives where

| Concern | Location |
|---------|---------|
| Wiki file ops, path validation, frontmatter parsing | `app/services/wiki.py` |
| Data types (`WikiFileInfo`, `WikiTree`, `WikiPathError`) | `app/services/wiki.py` |
| Dream runner, drain semantics, source slug injection | `app/services/dream.py` |
| Dream lint operation | `app/services/dream.py` |
| Dream config parser (`parse_dream_md`, `DreamAgentConfig`) | `app/services/dream.py` |
| Dream scheduler | `app/services/dream_scheduler.py` |
| USER.md injection | `app/agent/hooks/wiki_injection.py` |
| Note writing | `app/agent/tools/builtin/note.py` |
| Wiki search (BM25) | `app/agent/tools/builtin/wiki_search.py` |
| DB tables | `app/models/chat.py` (`DreamLog`, `DreamNotesLog`) |
| Migrations | `app/migrations/versions/00000004_create_dream_log.py` |
| Seed defaults | `app/core/wiki_seed.py`, `seed/dream.md` |
| Manual scripts | `manual/wiki.py`, `manual/note.py`, `manual/dream.py` |
