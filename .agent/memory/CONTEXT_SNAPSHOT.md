# OpenAgentd Second Brain Context Snapshot

Last updated: 2026-08-19 (Codex briefing after Wave A/B-min/C/D)


## Purpose

This file is the continuity packet for new Codex/OpenAgentd sessions working on the local-first second brain project. Read this file at the start of every new session before planning or editing. Keep it updated whenever decisions, implementation status, blockers, or next steps change.

## Codex briefing — 2026-08-19 (authoritative)

Read this block first. It supersedes `handover_to_codex.md`, `handover_to_antigravity_2.md`, GitHub vault roadmap checkboxes, and every “next = migrate / E2E / Bun” sentence further down this file.

### Do not re-implement

Vault gatekeeper, ingest/search/read/update, Hermes proposal/queue/query/skill (in-process, no live gateway), MCP watchdog, Windows shell hardening, coding-mode permission gate, Bun `base-url` `"undefined"` guard, Core CI Windows/`ty`/ruff fixes. Those are **done and pushed**.

### GitHub pins (pushed)

| Repo | SHA | Note |
|---|---|---|
| `LNK27/OpenAgentd` | `origin/main` | Wave C code is `08c8c892`; briefing docs sit on top of that. Use `git pull`, do not check out an older SHA from this table. |
| `LNK27/browser-harness` | `ec8957b9e` | inherited `cloud_evals`/`docker` workflows disabled |
| `LNK27/ai-agents` | `origin/main` | submodule pointer tracks OpenAgentd `origin/main` |

OpenAgentd Core CI is green on `913c1cd1` (lint + tests). Wave C after that is frontend/docs; Core may not re-run.

### Runtime (this machine)

- Canonical DB: `D:\ai-agents\OpenAgentd\.openagentd\data\openagentd.db` — Alembic **`00000010`**, `integrity_check=ok`.
- Home DB `%USERPROFILE%\.local\share\openagentd\openagentd.db` is still `00000007`. **Do not start a second server against it. Do not migrate it unless the user asks.**
- Vault path is in local `.env`: `OPENAGENTD_OBSIDIAN_VAULT_DIR=D:\ai-agents\ObsidianVault`. Do not commit `.env`.
- Cockpit is **Vite `:5173`**, API is **`127.0.0.1:4082`**. Root `/` on `:4082` is 404 by design (API-only).
- Two long-lived processes are the **live stack**, not unfinished jobs. They stay up until the user asks to stop them:
  - `uv run openagentd serve --host 127.0.0.1 --port 4082`
  - `bun run dev` in `web/` with `VITE_API_PROXY_TARGET=http://127.0.0.1:4082` (`bun.exe` 1.3.14, not npm `bun.ps1`)
- Live LLM: local agent config uses `googlegenai:gemini-2.5-flash` and `thinking_level: none`. OpenRouter `:free` 404 / paid 402; `gemini-3.1-flash` 404. Do not print keys.
- Coding mode uses blocking `PermissionService` (ask/deny), not `AutoAllowPermissionService`. Live-verified: `mkdir` pending then reject.
- `PRAGMA foreign_keys` is still **0**. Windows Alembic migrate lock is still a no-op.

### Wave C leftover (not a Codex re-do)

- Official `bun.exe` 1.3.14 via winget; User PATH prepends WinGet `bun-windows-x64` so it wins over `AppData\Roaming\npm\bun.ps1`. Always call `bun.exe`, never the npm shim.
- `web/src/api/base-url.ts` `normalizeBaseUrl` maps empty / `"undefined"` / `"null"` → `'/api'`.
- Isolated desktop-notification tests use `fileURLToPath` + `process.execPath` (Windows Bun path filter).
- `bun run lint` and `bun run typecheck` pass. Targeted `base-url` + notification tests pass.
- Full `bun test --parallel` flakes UI timeouts on this 16GB laptop (16 workers). That is environment load, not the `"undefined"` bug. Do not start a UI rewrite to “make 2068 tests green in parallel”.

### Next work (only these)

1. **P0 security:** rotate the Google API key used by `browser-use` MCP. The old key was exposed during audit. Need a **new** key from the user. Put it in gitignored `mcp.json` / harness env. Do not print the old or new key. Do not commit secrets.
2. **P1 optional:** enable `PRAGMA foreign_keys=ON` in the SQLAlchemy/SQLite engine and replace the Windows Alembic migrate-lock no-op with a real lock. Backup the project DB first.
3. **Not now:** ADR-003, Hermes Hybrid MCP Bridge, live Hermes gateway, persist approval queue to SQLite, sync/rebase `lthoangg/OpenAgentd` (~1579 behind) or `browser-use` (~841 behind).

### Local-only files — do not add

- `browser-harness/test_browser.py`
- `ObsidianVault/00-inbox/smoke-live-*.md`
- `.env`, `.openagentd/config/mcp.json`, API keys

## Project Goal

Build a Windows-native second brain stack on a Dell 16GB RAM machine.

Core roles:

- `OpenAgentd`: central orchestrator, cockpit UI, MCP supervisor, permission gate, vault gatekeeper, and agent writer.
- `browser-harness`: browser runtime using Brave/Playwright through MCP stdio.
- `Obsidian`: durable human-editable knowledge base and source of truth.
- `Hermes Agent`: future sidecar for deep memory and skill drafting; it must not write directly to the vault in v1.
- `Superpowers`: selected coding workflow discipline for code tasks only.
- `RTK`: optional explicit shell wrapper on native Windows; not a v1 dependency.

## Fixed Decisions

- Run v1 fully native on Windows/PowerShell. Do not introduce WSL into the critical path.
- `OpenAgentd` and `browser-harness` must not share the same Google Developer API key.
- Prefer `OpenAgentd` on `geminicli` OAuth or another provider; if it uses `googlegenai`, it needs a separate Google key from `browser-harness`.
- `browser-harness` gets its own Google API key in MCP env.
- Obsidian vault has two writer classes:
  - human writes directly through Obsidian desktop
  - agent writes only through OpenAgentd vault gatekeeper
- Do not expose the Obsidian vault through any write-capable MCP filesystem server.
- Coding mode must not auto-allow every shell command.
- Basic MCP watchdog for `browser-use` belongs in Phase 1, not later.
- Browser session concurrency is `1`; browser idle timeout target is `3 minutes`.

## Current Paths

- OpenAgentd repo: `D:\ai-agents\OpenAgentd`
- Browser Harness repo: `D:\ai-agents\browser-harness`
- Browser Harness Python: `D:\ai-agents\browser-harness\.venv\Scripts\python.exe`
- Brave executable: `C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe`
- Browser Harness config dir: `D:\ai-agents\browser-harness\.config`
- Default Obsidian vault target: `D:\ai-agents\ObsidianVault`
- OpenAgentd MCP config: `D:\ai-agents\OpenAgentd\.openagentd\config\mcp.json`

## Recommended Model Allocation

As of 2026-05-22, do not use one model for every layer of the project. Split by ownership boundary:

- `GPT-5.5`: primary owner/final integrator for `OpenAgentd` core integration work, MCP manager, permission system, cross-module debugging, and final code-carrying patches in the main repo.
- `GPT-5.4`: lower-cost OpenAI fallback for normal coding/professional work when `GPT-5.5` is overkill.
- `GPT-5.4 mini` / `GPT-5.4 nano`: cheap subagent lanes for narrow checks, simple code edits, extraction, and high-volume validation; do not use as final reviewer for risky patches.
- `Claude Opus 4.7` if available, otherwise `Claude Opus 4.6`: architecture, ADR drafting, spec writing, code review, security review, edge-case analysis, vault schema design, and human-readable policy text before implementation.
- `Claude Sonnet 4.6`: balanced Claude lane for review, refactor guidance, and medium-complexity coding when Opus is too expensive.
- `Claude Haiku 4.5`: cheap/fast Claude lane for summarization, cleanup, and low-risk text/code review passes.
- `Gemini 3.1 Pro`: browser-harness flows, Brave/browser automation reasoning, multimodal/screenshot interpretation, Google ecosystem research, broad external research passes, and long-context synthesis.
- `Gemini 3.5 Flash` if available, otherwise `Gemini 3.1 Flash` / `Gemini 3 Flash` / `Gemini 3.1 Flash-Lite` depending on the user's tooling: fast browser/research passes, cheap iteration, extraction, summarization, and non-critical validation.
- `Gemini 2.5 Computer Use` or current Google computer-use-capable line: UI/browser operation specialist when real screen/browser interaction is the primary task.
- `Qwen3.7-Max`: agentic coding worker for long-horizon coding tasks, scaffold implementation, repetitive refactors, test expansion, price-sensitive parallel work, and MCP/tool-use experiments; do not make it the sole final arbiter for critical cross-cutting patches until it is proven in this repo.
- `Qwen-Max` / `Qwen-Plus` / `Qwen-Flash` / `Qwen-Coder` lines: use by cost tier for generic reasoning, balanced work, cheap tasks, and code/tool-use respectively when `Qwen3.7-Max` is unavailable or unnecessary.
- Always separate implementation and review across different model families for risky changes. Example: GPT implements, Claude reviews, Gemini validates browser-facing behavior, Qwen handles low-risk batch work.
- Review feedback workflow preference: when Claude/Gemini/other agents return review findings, Codex must verify each claim against the codebase before accepting it. For real P0/P1 fixes, Codex/GPT-5.5 owns the patch; Claude Opus/Sonnet reviews security/contract boundaries after the patch; Gemini Flash/Pro runs regression/checklist validation. If a reviewer claim is false, call it out explicitly and do not implement it.

## Roadmap v7 Summary

Phase 1: runtime safety.

- Configure `browser-use` MCP with browser-harness venv Python, `PYTHONPATH`, Brave headed mode, config dir, and a dedicated Google key.
- Keep OpenAgentd on a separate credential/provider path.
- Add basic MCP watchdog for `browser-use`: detect runner error/process exit, restart with backoff, cap retries, avoid infinite restart loops.
- Harden browser lifecycle in browser-harness: concurrency `1`, cleanup after task, idle timeout, health check, profile recovery that does not blindly delete locks.
- Add browser quota/vision policy: step cap, request budget, `429` backoff/cooldown, default `use_vision='auto'` or `False`.
- Wire coding mode to a blocking permission service for shell safety.
- Create Obsidian vault skeleton:
  - `00-inbox`
  - `10-sources`
  - `20-topics`
  - `30-projects`
  - `40-people`
  - `50-decisions`
  - `90-archive`
  - `MAP_OF_CONTENT.md`

Phase 2: memory workflow and ingest.

- Build OpenAgentd vault gatekeeper with queued writes, frontmatter normalization, path validation, duplicate detection, and incremental index updates.
- Minimal note frontmatter:
  - `id`
  - `title`
  - `type`
  - `status`
  - `tags`
  - `created_at`
  - `updated_at`
  - `source_refs`
  - `relations`
  - `last_summarized_at`
  - `writer`
- Add human ingest/reconcile: detect Obsidian notes missing frontmatter or indexes, update MOC/index, and make them recallable in the same day.
- Add Hermes connector as a sidecar API adapter; Hermes returns structured output/write-intent only.
- Add selected Superpowers workflow pieces for coding: brainstorming, writing-plans, TDD, requesting-code-review.

Phase 3: observability and expansion.

- Add detailed MCP observability: restart count, last restart reason, flapping detection, UI warning.
- Track browser sessions, vault queue length, human ingest count, permission prompts, `429` count, recall latency.
- Add LiteLLM/global quota proxy only if separate keys still fail.
- Add Khoj, AgentScope, Kronos, or low-privilege Windows user sandbox only after the core is stable.

## Implementation Status

Phase 1 was **fully closed on the pre-sync local main**, but the `codex/sync-origin-main` branch intentionally did not replay the older MCP watchdog/runtime-observability patches because they conflict with the newer `origin/main` MCP manager refactor. Re-port MCP runtime observability separately before treating Phase 1 runtime observability as closed on the synced branch.

Known local state before this snapshot:

- `browser-harness` exists and has previously run an independent Brave test successfully.
- OpenAgentd `.openagentd\config\mcp.json` now includes a `browser-use` stdio server using `D:\ai-agents\browser-harness\.venv\Scripts\python.exe`, `PYTHONPATH`, browser-harness config paths, headed mode, and telemetry/cloud sync disabled.
- `browser-use` MCP is now enabled in `D:\ai-agents\OpenAgentd\.openagentd\config\mcp.json` with a non-placeholder Google API key supplied by the user. Do not print or expose the key in logs/responses.
- Follow-up checks confirmed OpenAgentd config loader reads `browser-use.enabled=True` from the active config file, and MCP config/schema tests passed (`16 passed`).
- Resolved prior 404 by stopping the old global uv tool process on port 4082 and starting the local repo binary `D:\ai-agents\OpenAgentd\.venv\Scripts\openagentd.exe`.
- `mcp_apply.py status browser-use` now reports `ready` with 16 tools, including browser navigation/click/type/state/screenshot/session tools and `retry_with_browser_use_agent`.
- `D:\ai-agents\browser-harness\.config\config.json` now pins Brave headed mode, a browser-harness-only profile/download path, `max_steps: 25`, and `use_vision: false`; it contains no real API key.
- OpenAgentd `MCPManager` now includes an auto-watchdog (retry loop with exponential backoff) for detecting runner error/process exit and avoiding infinite restart loops.
- Coding mode now uses a blocking `PermissionService` scoped to the lead session instead of `AutoAllowPermissionService`.
- Coding shell permission defaults are now:
  - non-shell tools: allow
  - selected read-only shell commands: allow
  - high-risk shell patterns: deny
  - all other shell commands: ask through pending permission APIs
- Team permission APIs now resolve pending requests through a live per-session permission-service registry so HTTP requests can approve/deny agent-task prompts by lead session id.
- Verification for the shell permission gate passed:
  - `uv run pytest tests/agent/test_permission.py tests/agent/mode/team/test_member_worker.py tests/api/routes/test_team.py -q` (`65 passed`)
  - `uv run ruff check app/agent/permission.py app/agent/mode/team/member.py app/api/routes/team/permissions.py tests/agent/test_permission.py tests/agent/mode/team/test_member_worker.py`
- Broader `tests/agent/tools/test_shell.py` was not used as gate verification because existing Windows/PowerShell environment assumptions fail POSIX-oriented cases (`tr`, `sleep`, `os.getpgid`) unrelated to the permission-service wiring.
- `uv run ty check app/` currently fails on existing Windows/POSIX portability diagnostics (`signal.SIGKILL`, `os.killpg/getpgid`, `fcntl.flock/LOCK_EX/LOCK_UN`), not on the PermissionService changes.
- `.agent/memory/CONTEXT_SNAPSHOT.md` now exists and is the continuity source for future sessions.
- Obsidian Vault skeleton (`D:\ai-agents\ObsidianVault`) has been created according to v7 AI-readable standards, including standard folders (`00-inbox`, `10-sources`, `20-topics`, `30-projects`, `40-people`, `50-decisions`, `90-archive`), central `MAP_OF_CONTENT.md`, area indexes (`_index.md`), an initial project note (`second-brain-project.md`), and an architecture decision record (`ADR-001-second-brain-architecture.md`).
- Fixed the critical MCP manager session-lifecycle bug in `app\agent\mcp\manager.py` by enclosing `runner.session`, state, and wait logic cleanly inside the `AsyncExitStack` block.
- Replaced all absolute `file:///D:/...` links in the Obsidian Vault skeleton with highly portable standard Obsidian WikiLinks (`[[folder/_index|Label]]`), conforming strictly to the link-integrity policy.
- Restored and expanded the watchdog integration test coverage in `tests/agent/mcp/test_manager.py` (added class `TestMCPWatchdogAndToolExecution` including mock crash/retry watchdog flows and tool execution post-ready). Resolved all background task leaks, resulting in 100% test pass.
- **MCP watchdog crash-after-ready recovery is now fully verified.** `_run_server()` includes `monitor_liveness()` that pings `session.list_tools()` every 5s while idle. When the liveness check fails, the runner transitions through `error` → `starting` → re-creates transport and session → returns to `ready` with tools repopulated. `test_watchdog_crash_after_ready()` proves the full recovery loop by tracking monotonic counters: `transport_enter_count ≥ 2`, `session_enter_count ≥ 2`, `list_tools_call ≥ 3`, and asserting tools/session/state are restored after recovery. Verification: `uv run pytest tests/agent/mcp/test_manager.py --no-cov -v` → 30 passed; `uv run ruff check app/agent/mcp/manager.py tests/agent/mcp/test_manager.py` → all checks passed.
- Codex independently reviewed the upgraded watchdog recovery test and re-ran verification: `uv run pytest tests/agent/mcp/test_manager.py --no-cov -q` (`30 passed`) and `uv run ruff check app/agent/mcp/manager.py tests/agent/mcp/test_manager.py` (`All checks passed`). Phase 1 can be treated as closed; remaining cleanup around draining cancelled liveness/shutdown tasks is optional hardening, not a blocker.
- A fresh handover packet for the current state was created at `D:\ai-agents\handover_to_antigravity_2.md` so the user can continue with Antigravity 2.0 after losing prior chat history.
- Phase 2 Vault Gatekeeper service layer has been started and verified. `app/services/vault_gatekeeper.py` is now the single in-process writer abstraction for agent-created Obsidian notes. It validates v7 vault folders, rejects traversal/direct `_index.md` writes/unsafe Windows reserved filenames, normalizes required frontmatter, serializes writes through an async lock, writes atomically, detects duplicate note IDs across the vault, and incrementally updates the containing folder `_index.md`.
- `app/core/config.py` now includes `OPENAGENTD_OBSIDIAN_VAULT_DIR`, defaulting near the configured wiki root and overridable for `D:\ai-agents\ObsidianVault`.
- `tests/services/test_vault_gatekeeper.py` covers gatekeeper path safety, Windows filename safety, frontmatter normalization, create/overwrite behavior, duplicate-ID rejection, concurrent serialized writes, index updates, and note lookup by ID.
- Verification for the Vault Gatekeeper service layer passed:
  - `uv run pytest tests/services/test_wiki.py tests/services/test_vault_gatekeeper.py --no-cov -q` (`55 passed`)
  - `uv run ruff check app/services/vault_gatekeeper.py tests/services/test_vault_gatekeeper.py app/core/config.py`
  - `uv run ruff format --check app/services/vault_gatekeeper.py tests/services/test_vault_gatekeeper.py app/core/config.py`
  - `uv run ty check app/services/vault_gatekeeper.py app/core/config.py`
- Vault Gatekeeper semantics were hardened for v1 agent writes:
  - note identity is now `folder/slug`
  - `note_id` is optional frontmatter metadata only and no longer participates in duplicate detection
  - write serialization stays at a single process-wide gatekeeper singleton lock
  - create-path index update failures now use best-effort rollback: if note creation succeeded but `_index.md` update fails, the gatekeeper attempts to delete the just-created note, logs rollback failures as `vault_write_rollback_failed`, and still propagates the original index error
- OpenAgentd now includes a new lead-only builtin tool `vault_write` for structured, durable Obsidian note creation through the gatekeeper. The tool:
  - accepts only whitelisted vault folders
  - does not expose `writer`, `overwrite`, or `last_summarized_at` in the tool schema
  - injects `writer` from `state.metadata["agent_name"]` with fallback `agent:unknown`
  - maps duplicate/path/index failures to stable agent-readable messages instead of generic errors
- `vault_write` is registered in the default builtin tool registry and auto-injected into lead agents alongside `note`, `todo_manage`, and `schedule_task`; member agents do not receive it.
- Verification for the `vault_write` integration passed:
  - `uv run pytest tests/services/test_wiki.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_note_tool.py tests/agent/tools/test_vault_write_tool.py tests/agent/test_loader.py --no-cov -q` (`144 passed`)
  - `uv run ruff check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_write.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_write_tool.py tests/agent/tools/test_note_tool.py tests/agent/test_loader.py`
  - `uv run ruff format --check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_write.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_write_tool.py tests/agent/tools/test_note_tool.py tests/agent/test_loader.py`
  - `uv run ty check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_write.py app/agent/loader.py`
- Human Ingest/Reconcile v1 is now implemented as a service + CLI, not an agent tool. `app/services/vault_ingest.py` scans only direct child Markdown files inside the seven v7 vault folders, skips subfolders/non-UTF-8/malformed-frontmatter notes with warnings/errors, preserves note bodies and existing/custom frontmatter fields, merge-adds missing v7 fields for human notes, and repairs folder `_index.md` files by appending missing links and removing stale links. It intentionally does not update `MAP_OF_CONTENT.md`, add `vault_read`/`vault_search`, add a watcher, expose a public route, or integrate recall.
- `openagentd vault ingest` now runs a dry-run report by default, while `openagentd vault ingest --apply` writes normalized frontmatter and repaired indexes. The ingest service uses the process-wide `get_vault_gatekeeper()` singleton lock and atomic writes so it coordinates with `vault_write` instead of creating a separate writer lane.
- Verification for Human Ingest/Reconcile v1 passed:
  - `uv run pytest tests/services/test_vault_ingest.py --no-cov -v` (`13 passed`)
  - `uv run pytest tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_write_tool.py tests/agent/tools/test_note_tool.py tests/agent/test_loader.py --no-cov -q` (`108 passed`)
  - `uv run pytest tests/cli/test_vault.py tests/cli/test_cli.py::TestBuildParser::test_vault_ingest_subcommand_defaults_to_dry_run tests/cli/test_cli.py::TestBuildParser::test_vault_ingest_subcommand_accepts_apply --no-cov -q` (`4 passed`)
  - `uv run ruff check app/services/vault_ingest.py tests/services/test_vault_ingest.py app/cli/main.py app/cli/commands/vault.py tests/cli/test_vault.py tests/cli/test_cli.py`
  - `uv run ruff format --check app/services/vault_ingest.py tests/services/test_vault_ingest.py app/cli/main.py app/cli/commands/vault.py tests/cli/test_vault.py tests/cli/test_cli.py`
  - `uv run ty check app/services/vault_ingest.py app/cli/commands/vault.py`
- A full `uv run pytest tests/cli/test_vault.py tests/cli/test_cli.py --no-cov -q` run was attempted but interrupted in existing Windows process/signal-oriented CLI tests; the new vault CLI parser/command tests were run directly and passed.
- Current execution priority after Human Ingest/Reconcile is **Vault Recall**: add vault read/search service and controlled `vault_read`/`vault_search` agent tools so OpenAgentd can retrieve from the Obsidian vault.
- Vault Recall v1 is now fully implemented, architecturally reviewed, refactored, and verified. OpenAgentd can retrieve from the Obsidian vault through controlled lead-only builtin tools:
  - `app/services/markdown_text.py` provides shared frontmatter parsing, Vietnamese-aware token sets (`exact` + folded no-diacritic tokens including `đ/Đ` handling), lightweight Markdown snippet cleanup, and shared DRY helpers (`score_token_overlap`, `extract_title_from_body_or_slug`).
  - `app/services/vault_search.py` provides on-disk vault search with a small mtime/size cache, stat-before-after guard, cache pruning, retry-on-transient-read errors, normalized tag filtering including Obsidian-style subtags, deterministic empty-query listing, and direct `read_note()` for deep reads. Now cleanly reuses `score_token_overlap` and `extract_title_from_body_or_slug` from `markdown_text.py`.
  - `app/agent/tools/builtin/vault_search.py` exposes `vault_search` with strongly typed `query` parameter (default `""`), specifically catches `VaultPathError` instead of generic `ValueError`, and returns path/title/type/tags/score/snippet.
  - `app/agent/tools/builtin/vault_read.py` exposes `vault_read` with folder/slug/include_frontmatter/max_chars, reads directly from disk, supports frontmatter hiding, and falls back to warned raw output for malformed frontmatter while still truncating to `max_chars`.
  - `wiki_search` scoring now uses the shared `TokenSets` exact/folded logic via `score_token_overlap()` while `_tokenize()` remains backward compatible for old tests.
  - `vault_ingest` now reuses the shared vault frontmatter parser and `extract_title_from_body_or_slug()` instead of duplicate implementations.
  - `vault_read` and `vault_search` are registered in the builtin registry and auto-injected for lead agents alongside `vault_write`; member agents do not receive them automatically.
- Verification for Vault Recall v1 passed:
  - `uv run pytest tests/services/test_vault_ingest.py tests/services/test_markdown_text.py tests/services/test_vault_search.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_search_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/tools/test_vault_write_tool.py tests/agent/tools/test_note_tool.py tests/agent/tools/test_wiki_search.py tests/agent/hooks/test_memory_injection_hook.py tests/agent/test_loader.py --no-cov -q` (All 168 tests passed!)
  - `uv run ruff check` and `uv run ruff format --check` passed cleanly.
  - Targeted `uv run ty check app/services/markdown_text.py app/services/vault_search.py app/services/vault_ingest.py app/agent/tools/builtin/vault_search.py app/agent/tools/builtin/vault_read.py app/agent/hooks/wiki_injection.py app/agent/loader.py` passed cleanly, while the full app type-check still has pre-existing Windows/POSIX portability tech debt.
- Hermes connector sidecar adapter v1 is now implemented as a proposal-only boundary:
  - `app/services/hermes.py` defines a swappable `HermesClient` protocol, `HttpHermesClient`, request/proposal dataclasses, error taxonomy (`HermesUnavailableError`, `HermesConnectionError`, `HermesTimeoutError`, `HermesSchemaError`), loopback-only HTTP transport validation, optional `X-Hermes-Token`, health check, context/max-intent clamping, response normalization, body truncation, forbidden-field rejection, `status="draft"` override, path validation, and existing-note conflict detection.
  - `app/agent/tools/builtin/hermes_propose.py` exposes a lead-only proposal tool that returns structured JSON-ish output with `valid_intents`, `conflicts`, `invalid_intents`, warnings, and pending approval ids; it never calls `vault_write` or writes to the vault.
  - `app/core/config.py` now includes Hermes config knobs: `OPENAGENTD_HERMES_ENABLED`, `OPENAGENTD_HERMES_BASE_URL`, `OPENAGENTD_HERMES_TOKEN`, `OPENAGENTD_HERMES_TIMEOUT_SECONDS`, `OPENAGENTD_HERMES_MAX_CONTEXT_CHARS`, and `OPENAGENTD_HERMES_MAX_BODY_CHARS_PER_INTENT`.
  - `hermes_propose` is registered in the builtin registry and auto-injected for lead agents only; member agents do not receive it automatically.
  - V1 intentionally supports new-note proposals only. Existing target paths are reported as `exists_conflict`; update workflows (`vault_update`, overwrite, batch write) remain out of scope.
- Verification for Hermes connector v1 passed:
  - `uv run pytest tests/services/test_hermes.py tests/agent/tools/test_hermes_propose_tool.py tests/services/test_vault_search.py tests/agent/tools/test_vault_search_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/tools/test_vault_write_tool.py tests/agent/test_loader.py --no-cov -q`
  - `uv run pytest tests/services/test_vault_ingest.py tests/services/test_markdown_text.py tests/services/test_vault_search.py tests/services/test_vault_gatekeeper.py tests/services/test_hermes.py tests/agent/tools/test_hermes_propose_tool.py tests/agent/tools/test_vault_search_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/tools/test_vault_write_tool.py tests/agent/tools/test_note_tool.py tests/agent/tools/test_wiki_search.py tests/agent/hooks/test_memory_injection_hook.py tests/agent/test_loader.py --no-cov -q`
  - `uv run ruff check app/services/hermes.py app/agent/tools/builtin/hermes_propose.py app/agent/tools/builtin/__init__.py app/agent/loader.py app/core/config.py tests/services/test_hermes.py tests/agent/tools/test_hermes_propose_tool.py tests/agent/test_loader.py`
  - `uv run ruff format --check app/services/hermes.py app/agent/tools/builtin/hermes_propose.py app/agent/tools/builtin/__init__.py app/agent/loader.py app/core/config.py tests/services/test_hermes.py tests/agent/tools/test_hermes_propose_tool.py tests/agent/test_loader.py`
  - `uv run ty check app/services/hermes.py app/agent/tools/builtin/hermes_propose.py app/agent/loader.py app/core/config.py`
- Claude Opus 4.6 reviewed Hermes connector v1 and found one valid P1 before ship: `app/services/hermes.py` caught broad `Exception` around `validate_vault_note_path`. Codex verified and fixed this by narrowing the catch to `VaultPathError`, with a regression test proving unexpected validator errors are no longer swallowed. Opus also claimed `as_vault_write_params()` returning `status` would break `vault_write`, but Codex verified this is false because `vault_write` accepts `status`, so no change was made there.
- Verification for the Hermes P1 fix passed:
  - `uv run pytest tests/services/test_hermes.py tests/agent/tools/test_hermes_propose_tool.py --no-cov -q`
  - `uv run pytest tests/services/test_vault_ingest.py tests/services/test_markdown_text.py tests/services/test_vault_search.py tests/services/test_vault_gatekeeper.py tests/services/test_hermes.py tests/agent/tools/test_hermes_propose_tool.py tests/agent/tools/test_vault_search_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/tools/test_vault_write_tool.py tests/agent/tools/test_note_tool.py tests/agent/tools/test_wiki_search.py tests/agent/hooks/test_memory_injection_hook.py tests/agent/test_loader.py --no-cov -q`
  - `uv run ruff check app/services/hermes.py tests/services/test_hermes.py`
  - `uv run ruff format --check app/services/hermes.py tests/services/test_hermes.py`
  - `uv run ty check app/services/hermes.py`
- Hermes connector v1 is now accepted and closed after independent review:
  - Claude Opus 4.6 post-P1-fix verdict: `Ship`; no remaining P0/P1 blockers. P2 items (`shared httpx.AsyncClient`, mixed valid+forbidden test) are tracked as non-blocking tech debt.
  - Gemini 3.5 Flash regression/checklist verdict: `Accepted & Closed`; Hermes tests, Vault/Second Brain regression, ruff/format, targeted type check, lead-only injection, UX output, and no-write boundary all passed.
- Hermes approval/review queue v1 is now implemented and verified:
  - `app/services/hermes_approval.py` provides a per-process in-memory queue scoped by `session_id`, with opaque `pending_id` values, terminal statuses (`approved`, `rejected`, `failed`), and an `asyncio.Lock` around enqueue/list/approve/reject operations to prevent double approve/reject races.
  - `hermes_propose` now has a deliberate side effect: it enqueues normalized valid Hermes intents and returns pending ids plus previews, conflicts, invalid intents, warnings, and `evicted_count`. It no longer returns `vault_write_params` directly.
  - Queue limit is `50` pending entries per session. When enqueue exceeds the limit, the oldest pending entries in that session are marked `rejected` with reason `superseded_by_queue_limit`, and `hermes_propose` reports the eviction count.
  - New lead-only tools are registered and auto-injected: `hermes_pending_list`, `hermes_pending_approve`, and `hermes_pending_reject`; member agents do not receive them.
  - Approval revalidates the final vault path, fails clearly if the note already exists, never exposes overwrite/update, never calls Hermes, and writes through `get_vault_gatekeeper().write_note(...)` with writer `agent:<approver>` from `_state.metadata["agent_name"]` or `agent:unknown`.
  - Rejection marks the entry `rejected` and stores the optional reason without writing to the vault. `failed` is terminal; retry requires calling `hermes_propose` again.
  - Architectural boundary: approval queue is the Hermes review flow, not a vault-wide security gate. `vault_write` remains available to lead agents for non-Hermes notes and can still be called directly.
- Verification for Hermes approval/review queue v1 passed:
  - `uv run pytest tests/services/test_hermes.py tests/agent/tools/test_hermes_propose_tool.py --no-cov -q` (`16 passed`)
  - `uv run pytest tests/services/test_hermes_approval.py tests/agent/tools/test_hermes_pending_tools.py --no-cov -q` (`14 passed`)
  - `uv run pytest tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_write_tool.py tests/agent/test_loader.py --no-cov -q` (`101 passed`)
  - `uv run pytest tests/services/test_hermes.py tests/agent/tools/test_hermes_propose_tool.py tests/services/test_hermes_approval.py tests/agent/tools/test_hermes_pending_tools.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_write_tool.py tests/agent/test_loader.py --no-cov -q` (`131 passed`)
  - `uv run ruff check app/services/hermes_approval.py app/agent/tools/builtin tests/services/test_hermes_approval.py tests/agent/tools/test_hermes_pending_tools.py tests/agent/tools/test_hermes_propose_tool.py tests/agent/test_loader.py`
  - `uv run ruff format --check app/services/hermes_approval.py app/agent/tools/builtin tests/services/test_hermes_approval.py tests/agent/tools/test_hermes_pending_tools.py tests/agent/tools/test_hermes_propose_tool.py tests/agent/test_loader.py`
  - `uv run ty check app/services/hermes_approval.py app/agent/tools/builtin/hermes_propose.py app/agent/tools/builtin/hermes_pending.py app/agent/loader.py`
- Hermes approval/review queue v1 is accepted and closed after independent review:
  - Claude Opus 4.6 verdict: `Ship`; no P0/P1 blockers. Non-blocking items tracked: queue lock held during disk I/O, duplicate state/writer helper logic, preview exposing vault-write-equivalent fields under `preview`, and missing approval-specific `VaultIndexUpdateError` rollback test.
  - Gemini 3.5 Flash regression/checklist verdict: `Accepted`; no P0/P1 blockers. Gemini confirmed scope boundaries, no direct Hermes-to-vault write path, lead-only injection/member exclusion, queue limit eviction, terminal state handling, no-overwrite approval, and writer attribution.
- Hermes query/recall v1 is now implemented and verified:
  - `app/services/hermes.py` now supports read-only Hermes query/recall through `HermesQueryRequest`, `HermesQueryItem`, `HermesQueryResult`, `query_recall()`, `normalize_hermes_query_response()`, and `HttpHermesClient.query_recall()` using POST `/v1/query`.
  - Query/recall reuses the existing Hermes connector safety boundary: loopback-only HTTP, health check, optional token, timeout/connection/schema error taxonomy, context clamping, and max result clamping to `1..20`.
  - Query response normalization accepts `answer`, `items`, `warnings`, and `model_info`; recall items expose path/title/excerpt/score/tags only and reject write-control fields such as `vault_write_params`, `writer`, `overwrite`, `write_intents`, and `pending_id`.
  - `app/agent/tools/builtin/hermes_query.py` exposes a lead-only read-only tool. It never writes to the vault, never enqueues approvals, never calls `vault_write`, and does not draft skills. New-note proposals still use `hermes_propose`.
  - `hermes_query` is registered in the builtin registry and auto-injected for lead agents only; member agents do not receive it.
- Verification for Hermes query/recall v1 passed:
  - `uv run pytest tests/services/test_hermes.py tests/agent/tools/test_hermes_query_tool.py tests/agent/test_loader.py --no-cov -q` (`86 passed`)
  - `uv run pytest tests/services/test_hermes.py tests/agent/tools/test_hermes_query_tool.py tests/agent/tools/test_hermes_propose_tool.py tests/services/test_hermes_approval.py tests/agent/tools/test_hermes_pending_tools.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_write_tool.py tests/agent/test_loader.py --no-cov -q` (`138 passed`)
  - `uv run ruff check app/services/hermes.py app/agent/tools/builtin/hermes_query.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_hermes.py tests/agent/tools/test_hermes_query_tool.py tests/agent/test_loader.py`
  - `uv run ruff format --check app/services/hermes.py app/agent/tools/builtin/hermes_query.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_hermes.py tests/agent/tools/test_hermes_query_tool.py tests/agent/test_loader.py`
  - `uv run ty check app/services/hermes.py app/agent/tools/builtin/hermes_query.py app/agent/loader.py`
- Claude Opus 4.6 reviewed Hermes query/recall v1 and gave verdict `Ship`; no P0/P1 blockers. Opus confirmed the read-only boundary and noted two P2s: non-finite scores could emit non-standard JSON tokens, and forbidden-field query items currently hard-fail the whole result instead of soft-skipping bad items.
- Codex fixed the non-finite score P2 by clamping NaN/Infinity scores to `0.0` in `app/services/hermes.py`, with a regression test. Verification passed:
  - `uv run pytest tests/services/test_hermes.py::test_normalize_query_response_clamps_non_finite_scores --no-cov -q`
  - `uv run pytest tests/services/test_hermes.py tests/agent/tools/test_hermes_query_tool.py --no-cov -q` (`17 passed`)
  - `uv run ruff check app/services/hermes.py tests/services/test_hermes.py`
  - `uv run ruff format --check app/services/hermes.py tests/services/test_hermes.py`
  - `uv run ty check app/services/hermes.py`
- Gemini 3.5 Flash final regression/checklist verdict for Hermes query/recall v1: `Accepted (Ship)`; no P0/P1 blockers. Gemini verified read-only boundary, `/v1/query` service contract, minimal output fields, forbidden write-control rejection, NaN/Infinity score clamping, lead-only injection, and no regression to `hermes_propose`, approval queue, loader registry, or `vault_write`. Remaining P2: forbidden-field query items hard-fail the whole result instead of soft-skipping bad items; accepted as v2 UX tech debt.
- Second Brain Read/Write Tool Observability v1 is now implemented and verified:
  - `app/agent/tools/builtin/_observability.py` adds a shared helper for builtin Second Brain tool spans and Prometheus metrics. It annotates the active `execute_tool ...` span with `openagentd.second_brain.tool`, `openagentd.second_brain.outcome`, and low-risk attrs, and marks caught semantic tool errors as span `ERROR`.
  - `app/core/metrics.py` now exposes `openagentd_second_brain_tool_calls_total{tool,status}` and `openagentd_second_brain_tool_duration_seconds{tool,status}` using low-cardinality `tool,status` labels and HTTP-style latency buckets.
  - `app/agent/hooks/otel.py` now preserves a tool span already marked `ERROR` by the tool helper instead of unconditionally overwriting it with `OK` after a string return.
  - Instrumented tools: `vault_write`, `vault_search`, `vault_read`, `hermes_propose`, `hermes_query`, `hermes_pending_list`, `hermes_pending_approve`, and `hermes_pending_reject`.
  - Telemetry records only paths/folders, lengths, counts, limits, booleans, outcomes, and status. It does not record note body, query text, Hermes context text, note title, reject reason, or pending ids.
  - No API/UI/dashboard/persistence/alerting was added. Hermes/vault write boundaries are unchanged.
- Verification for Second Brain Read/Write Tool Observability v1 passed:
  - `uv run pytest tests/agent/hooks/test_otel_hook.py tests/core/test_metrics.py --no-cov -q` (`28 passed`)
  - `uv run pytest tests/agent/tools/test_vault_write_tool.py tests/agent/tools/test_vault_search_tool.py tests/agent/tools/test_vault_read_tool.py --no-cov -q` (`19 passed`)
  - `uv run pytest tests/agent/tools/test_hermes_propose_tool.py tests/agent/tools/test_hermes_query_tool.py tests/agent/tools/test_hermes_pending_tools.py --no-cov -q` (`21 passed`)
  - `uv run pytest tests/services/test_observability_service.py tests/api/routes/test_observability_route.py tests/agent/test_loader.py --no-cov -q` (`91 passed`)
  - `uv run ruff check app/agent/tools/builtin app/agent/hooks/otel.py app/core/metrics.py tests/agent/tools tests/agent/hooks/test_otel_hook.py tests/core/test_metrics.py`
  - `uv run ruff format --check app/agent/tools/builtin app/agent/hooks/otel.py app/core/metrics.py tests/agent/tools tests/agent/hooks/test_otel_hook.py tests/core/test_metrics.py`
  - Targeted `uv run ty check app/agent/tools/builtin/_observability.py app/agent/tools/builtin/vault_write.py app/agent/tools/builtin/vault_search.py app/agent/tools/builtin/vault_read.py app/agent/tools/builtin/hermes_propose.py app/agent/tools/builtin/hermes_query.py app/agent/tools/builtin/hermes_pending.py app/agent/hooks/otel.py app/core/metrics.py`
  - Broad `uv run ty check app/agent/tools/builtin app/agent/hooks/otel.py app/core/metrics.py` still fails only on pre-existing Windows/POSIX diagnostics in `app/agent/tools/builtin/shell.py` (`signal.SIGKILL`, `os.killpg`, `os.getpgid`), not on this observability patch.
- Second Brain Read/Write Tool Observability v1 is accepted and closed after independent review:
  - Claude Opus 4.6 verdict: `Ship with P2`; no P0/P1 blockers. Non-blocking items tracked: `hermes_propose` latency includes in-memory enqueue time, and `_tracer_with_exporter()` is duplicated across tool tests.
  - Gemini 3.5 Flash verdict: `Accepted (Ship with P2)`; no P0/P1 blockers. Gemini confirmed regression safety, unchanged write boundaries, correct semantic error preservation, low-cardinality metrics, privacy-safe attributes, and adequate helper/tool/hook test coverage.
- MCP Runtime Observability Port v2 is implemented on branch `codex/mcp-runtime-observability-port-v2`. The old patch was not reused mechanically because the current MCP manager now has OAuth/auth_required and streamable HTTP behavior. Current planning artifacts:
  - Design doc: `docs/superpowers/specs/2026-06-06-mcp-runtime-observability-port-v2-design.md`
  - Implementation plan: `docs/superpowers/plans/2026-06-06-mcp-runtime-observability-port-v2.md`
  - Status: implemented and targeted verification passed.
  - Claude Opus review found two valid P1 plan issues before coding: liveness probes could race active MCP tool calls, and retry-count getter/setter callbacks were overcomplicated. The spec/plan were revised to add an internal active tool-call activity gate covering both generated MCP tools and MCP app bridge calls, and to keep retry count owned by `_run_server()`.
  - Gemini 3.5 Flash re-review accepted the revised spec/plan as ready for TDD implementation. Codex then added one extra plan hardening item before coding: update `app/agent/mcp/tools.py` to type MCP sessions by a minimal `call_tool()` protocol so `_TrackedMCPClientSession` is valid under targeted `ty check`.
  - Implementation details:
    - `MCPServerStatus` and `/api/mcp` status responses now expose `auto_restart_count`, `manual_restart_count`, `last_restart_reason`, `last_restart_at`, `last_failure_at`, `flapping`, and `warning`.
    - `MCPManager` now retries non-auth runtime failures with bounded backoff, marks flapping after repeated failures, clears stale flapping warnings after a stable liveness window, and preserves observability history across explicit restart calls.
    - Liveness probes use an activity gate so `session.list_tools()` does not overlap active generated MCP tool calls or MCP app bridge calls.
    - OAuth/auth_required paths remain terminal and do not increment restart counters or mark flapping.
  - Verification passed:
    - `uv run pytest tests/agent/mcp/test_manager.py tests/api/test_mcp_routes.py --no-cov -q`
    - `uv run pytest tests/agent/mcp/test_tools.py --no-cov -q`
    - `uv run pytest tests/api/routes/test_observability_route.py tests/services/test_observability_service.py tests/agent/test_loader.py --no-cov -q`
    - `uv run ruff check app/agent/mcp/manager.py app/agent/mcp/tools.py app/api/routes/mcp.py app/api/schemas/mcp.py tests/agent/mcp/test_manager.py tests/api/test_mcp_routes.py`
    - `uv run ruff format --check app/agent/mcp/manager.py app/agent/mcp/tools.py app/api/routes/mcp.py app/api/schemas/mcp.py tests/agent/mcp/test_manager.py tests/api/test_mcp_routes.py`
    - `uv run ty check app/agent/mcp/manager.py app/agent/mcp/tools.py app/api/routes/mcp.py app/api/schemas/mcp.py`
- Vault Update v1 is now implemented and verified:
  - `VaultGatekeeper.update_note(...)` updates existing notes under the existing gatekeeper lock with atomic writes and optimistic SHA-256 conflict detection.
  - `vault_read(include_update_token=True)` returns a `sha256` token for the full raw note content without changing default read output.
  - `vault_update` is lead-only and supports structured body replacement, body append, and allowlisted metadata updates while preserving custom frontmatter.
  - `title`, `type`, `id`, `created_at`, `folder`, and `slug` remain read-only in v1; no index update, API/UI, batch, delete, rename, move, Hermes direct write, or approval queue integration was added.
  - Design doc: `docs/superpowers/specs/2026-06-03-vault-update-v1-design.md`; implementation plan: `docs/superpowers/plans/2026-06-05-vault-update-v1.md`.
- Verification for Vault Update v1 passed:
  - `uv run pytest tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_update_tool.py tests/agent/tools/test_vault_read_tool.py --no-cov -q` (`43 passed`)
  - `uv run pytest tests/agent/tools/test_vault_write_tool.py tests/agent/tools/test_vault_search_tool.py tests/agent/test_loader.py --no-cov -q` (`84 passed`)
  - `uv run pytest tests/services/test_observability_service.py tests/api/routes/test_observability_route.py --no-cov -q` (`21 passed`)
  - `uv run ruff check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_update.py app/agent/tools/builtin/vault_read.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_update_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/test_loader.py`
  - `uv run ruff format --check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_update.py app/agent/tools/builtin/vault_read.py app/agent/tools/builtin/__init__.py app/agent/loader.py tests/services/test_vault_gatekeeper.py tests/agent/tools/test_vault_update_tool.py tests/agent/tools/test_vault_read_tool.py tests/agent/test_loader.py`
  - `uv run ty check app/services/vault_gatekeeper.py app/agent/tools/builtin/vault_update.py app/agent/tools/builtin/vault_read.py app/agent/loader.py`
- Hermes Skill Drafting v1 is implemented and verified on branch `codex/hermes-skill-drafting-v1`. Design doc: `docs/superpowers/specs/2026-06-05-hermes-skill-drafting-v1-design.md`; implementation plan: `docs/superpowers/plans/2026-06-06-hermes-skill-drafting-v1.md`.
  - `agent_fs.write_skill(..., create=True)` now uses create-only atomic publish semantics so existing `SKILL.md` files are not overwritten by approval races. `validate_skill_name()` exposes the shared agent_fs name policy for skill draft normalization.
  - Hermes skill drafting contract is added to `app/services/hermes.py` through `HermesSkillDraftRequest`, `HermesSkillDraftProposal`, `HermesSkillDraftResult`, `draft_skills()`, and HTTP POST `/v1/skill-drafts`. Hermes supplies raw `name`, `description`, and `body` only; OpenAgentd owns validation/rendering/write.
  - `app/services/hermes_skill_drafting.py` provides the in-memory per-process `HermesSkillDraftQueue`, scoped by `session_id`, capped at 50 total entries per session, using UUID pending ids, terminal statuses, terminal-entry pruning, and oldest-pending eviction with reason `superseded_by_queue_limit`.
  - New lead-only tools are registered and auto-injected: `hermes_skill_draft`, `hermes_skill_pending_list`, `hermes_skill_pending_approve`, and `hermes_skill_pending_reject`. Member frontmatter attempts are skipped and logged with `lead_only_tool_skipped`.
  - Approval creates only new `SKILLS_DIR/{name}/SKILL.md` through `agent_fs.write_skill(..., create=True)` and invalidates the skill cache. It does not call Hermes, does not auto-load/grant/install the skill, and does not update/overwrite/delete/rename/move existing skills.
  - Runtime logs, ToolStart stream arguments, tool observability attributes, and metrics redact or omit sensitive `task`, `context`, body preview/content, description text, reject reason, and pending ids. ToolEnd and tool result output may include bounded `body_preview` and `pending_id` as the lead review surface.
  - No API/UI/DB/persistence/batch approval/Hermes direct filesystem write/raw filesystem write from Hermes tool was added.
- Verification for Hermes Skill Drafting v1:
  - Targeted Hermes/skill/loader tests passed. Full suite on Windows is not clean due to pre-existing portability/environment failures, with no failures classified as regressions from Hermes Skill Drafting v1.
  - Targeted tests ran:
    - `uv run pytest tests/services/test_agent_fs.py tests/services/test_hermes.py tests/services/test_hermes_skill_drafting.py --no-cov -q` (`51 passed`)
    - `uv run pytest tests/agent/test_hermes_skill_redaction.py tests/agent/tools/test_hermes_skill_tools.py tests/agent/test_loader.py --no-cov -q` (`82 passed`)
    - `uv run pytest tests/services/test_hermes_approval.py tests/agent/tools/test_hermes_propose_tool.py tests/agent/tools/test_hermes_pending_tools.py tests/agent/tools/test_hermes_query_tool.py tests/agent/tools/test_skill_loader.py --no-cov -q` (`47 passed`)
  - Lint/typecheck verified:
    - `uv run ruff check app/services/agent_fs.py app/services/hermes.py app/services/hermes_skill_drafting.py app/agent/agent_loop/tool_executor.py app/agent/hooks/stream_publisher.py app/agent/tools/builtin/hermes_skill.py app/agent/tools/builtin/__init__.py app/agent/tools/builtin/skill.py app/agent/loader.py tests/services/test_agent_fs.py tests/services/test_hermes.py tests/services/test_hermes_skill_drafting.py tests/agent/test_hermes_skill_redaction.py tests/agent/tools/test_hermes_skill_tools.py tests/agent/tools/test_skill_loader.py tests/agent/test_loader.py`
    - `uv run ty check app/services/agent_fs.py app/services/hermes.py app/services/hermes_skill_drafting.py app/agent/agent_loop/tool_executor.py app/agent/hooks/stream_publisher.py app/agent/tools/builtin/hermes_skill.py app/agent/tools/builtin/skill.py app/agent/loader.py`
  - Neighboring regression fix included: `discover_skills()` now reports skill file paths using POSIX-style relative paths on Windows (`web-research/SKILL.md`).
- **Windows Portability and Shell Hardening v1 is committed locally as `7cc9c48a`.** Fixed Windows-specific portability issues across 13+ test and source files:
  - Solved `signal.SIGKILL` and `os.killpg`/`os.getpgid` AttributeError errors on Windows by using dynamically resolved signal proxies (`_SIGKILL`) and fallback `proc.kill()` calls.
  - Hardened POSIX shell path lookup in `shell_runtime.py` to prioritize Git Bash installation paths relative to PATH executable or common locations, completely avoiding the WSL bash stub (`system32/bash.exe` or `WindowsApps/bash.exe`) which caused WSL path translation issues.
  - Eliminated "over-skipping" in `test_shell.py` by enabling `TestSandboxCommandScan` on Windows. Used `.as_posix()` and double quotes to make POSIX commands (`cat`, `tail`, `sleep`) fully parseable by Git Bash.
  - Resolved `shlex.split` quote preservation issues under `posix=False` (on Windows) by automatically stripping outer single and double quotes from path tokens before sandbox validation.
  - Speeded up and stabilized background process tests on Windows by tweaking `fast_bg` warmup delays (using 100ms instead of 5ms on Windows) and adding a tiny sleep before querying background stdout.
  - Cleaned up quality gates: `ruff check` passes cleanly, `ruff format` applied, and all Windows-specific `SIGKILL` unresolved-attribute type checker errors (including `app/cli/commands/stop.py`) resolved under `ty check app/`.
  - Resolved other late-stage Windows portability issues: added directory mtime delay in `test_skill_loader.py` to fix Windows NTFS resolution collision; updated `snapshot_service.py` to recursively modify Git read-only files to writable before running `shutil.rmtree`; normalized relative path backslashes to POSIX-style slashes in `seed.py`; skipped invalid WSL/bash shell runs and executable permission checks in `test_install_sh.py` on Windows hosts; and fixed scheduler test synchronization races.

## Audit Reconciliation — 2026-08-13

Historical note from the 13/08 session. The 2026-08-19 section below supersedes the git-sync claims in this block.

## Audit Reconciliation — 2026-08-19

This section supersedes any conflicting historical claim above, including the 13/08 “origin/main is in sync” sentence.

- `handover_to_codex.md` and `handover_to_antigravity_2.md` are historical. Do not treat them as the next-task list. Do not re-implement vault gatekeeper, Hermes proposal/queue/query/skill, MCP watchdog, or Windows shell hardening.
- After the 19/08 push+CI+Wave C the GitHub pins are: OpenAgentd `08c8c892`, browser-harness `ec8957b9e`, root `ai-agents` `aebfae8`. Older pins in this file (`913c1cd1`, `045d431`, `7cc9c48a`, `6cbd58cda`) are historical. Before the 19/08 push, GitHub `LNK27` was frozen at 2026-06 (`ai-agents` `0435335`, OpenAgentd `336e1464`, browser-harness `933e28c59`). The **Codex briefing** at the top of this file is the SHA source of truth.
- Local-only leftover: `browser-harness/test_browser.py` stays untracked. Do not add it.
- Canonical SQLite is `D:\ai-agents\OpenAgentd\.openagentd\data\openagentd.db`, now Alembic **`00000010`**, `integrity_check=ok`. A second DB exists at `%USERPROFILE%\.local\share\openagentd\openagentd.db` (`00000007`). Do not start two servers against both. Do not migrate the home DB unless asked.
- Project `.env` must set `OPENAGENTD_OBSIDIAN_VAULT_DIR=D:\ai-agents\ObsidianVault`. Without it, vault tools write the empty `.openagentd\ObsidianVault`. This is set locally; do not commit `.env`.
- Wave D live E2E (CLI/API + Vite cockpit on `:5173` proxying `:4082`) verified: ingest/search/write, human inbox note, coding-mode shell **ask** (not AutoAllow). OpenAgentd Core CI is green on `913c1cd1`.
- Wave C Bun is installed: official `bun.exe` 1.3.14 via winget (`Oven-sh.Bun`). User PATH prepends the WinGet `bun-windows-x64` folder so `bun.exe` wins over the leftover npm `bun.ps1` shim. Do not use the npm shim. `web/` uses `bun install --frozen-lockfile`.
- Wave C code: `normalizeBaseUrl` treats empty / `"undefined"` / `"null"` as unset (`/api`). Desktop-notification isolated tests now use `fileURLToPath` + `process.execPath` so Windows Bun 1.3.14 finds the worker file. Targeted web gates: `base-url` + isolated notification tests pass; `bun run lint` and `bun run typecheck` pass. Full `bun test --parallel` still flakes UI timeouts on this 16GB laptop (16x workers); those are not the Codex `"undefined"` regressions.
- Fork drift remains a separate project: OpenAgentd ~30 ahead / ~1579 behind `lthoangg/OpenAgentd` `v1.133.0`. browser-harness ~841 behind `browser-use`. Do not mix with Second Brain or ADR-002.
- GitHub had no open issues or PRs in `LNK27/ai-agents`, `LNK27/OpenAgentd`, or `LNK27/browser-harness` at audit time.
- Current verified quality gates: backend Core CI green on `913c1cd1` (`ruff` / `ruff format` / `ty` / pytest). Local `bun run lint` + `bun run typecheck` pass on Wave C. Focused `base-url` + desktop-notification isolated tests pass. The complete local pytest suite is still not a desktop-terminal proof (~64s cutoff historically); GitHub Core is the backend proof. Full `bun test --parallel` flakes UI timeouts on 16 workers — environment, not a Wave C regression.
- `test_trigger_paused_task_enables_it` was an intermittent test race: it observed dispatch start while the background firing task still had status `running`. The test now waits for persisted terminal recurring state (`pending`) and passed ten consecutive runs plus its scheduler/API/CLI group.
- Phase 2 implementation that exists in code: Vault Gatekeeper, ingest/reconcile, read/search/update, Hermes proposal-only HTTP adapter, manual Hermes approval queue, read-only Hermes query, tool observability, and Hermes skill-draft queue. Their live upstream Hermes connection is not verified by this audit.
- ADR-002 remains unimplemented: no `scripts/hermes_mcp_bridge.py`, no `hermes-bridge` entry in active `mcp.json`, no auto-approve setting/rules/tests, and no ADR-003 D8 amendment. Plan 1 items `codebase-memory`, Headroom, and Loop Engineering are also absent from the project implementation.
- For a future Hermes bridge config, use only supported `${VAR}` references. The MCP config parser does not resolve bash-style `${VAR:-default}` expressions; code/default settings must supply fallback values instead.

## Next Implementation Steps

1. ~~Close the remaining MCP watchdog/liveness gap~~ — **DONE** (2026-05-22). Crash-after-ready recovery verified by test.
2. ~~Implement Phase 2: OpenAgentd Vault Gatekeeper service layer~~ — **DONE** (2026-05-22). Backend service supports sequential writes, metadata frontmatter normalization, path validation, duplicate detection, and incremental index updates.
3. ~~Wire the Vault Gatekeeper into a controlled OpenAgentd entrypoint~~ — **DONE** (2026-05-22). Lead-only builtin `vault_write` now provides the agent-side structured write surface without exposing raw filesystem writes or a public HTTP route.
4. ~~Implement Phase 2: Human Ingest/Reconcile service~~ — **DONE** (2026-05-24). Service + CLI normalize manual Obsidian notes and repair folder indexes without adding recall/search/read yet.
5. ~~Implement Phase 2: Vault Recall service and controlled `vault_read` / `vault_search` tools~~ — **DONE** (2026-05-26). Lead agents can now search/list and deep-read Obsidian vault notes without exposing a raw filesystem surface.
6. ~~Integrate Hermes connector as a sidecar API adapter producing write-intents only~~ — **DONE** (2026-05-29). Lead agents can request Hermes write-intent proposals through `hermes_propose`; Hermes cannot write directly to the vault.
7. ~~Implement Hermes approval/review queue v1~~ — **DONE** (2026-05-30). Lead agents can review, approve, or reject Hermes pending intents before queue-mediated vault writes; `vault_write` remains available for non-Hermes notes.
8. ~~Implement Hermes query/recall v1~~ — **DONE** (2026-06-02). Lead agents can ask Hermes for read-only recall/query results without vault writes, approval queue side effects, or skill drafting.
9. ~~Implement Second Brain Read/Write Tool Observability v1~~ - **DONE** (2026-06-02). Vault/Hermes read/write tools now annotate active tool spans and emit low-cardinality Prometheus metrics without changing tool schemas or write boundaries.
10. ~~Implement MCP Runtime Observability Port v2 from the new design/plan on synced `main`~~ - **DONE** (2026-06-07). MCP status now exposes restart/flapping observability while preserving current OAuth/streamable HTTP semantics.
11. ~~Implement Vault Update v1~~ - **DONE** (2026-06-05). Lead agents can update existing Obsidian notes through `vault_update` using an optimistic `sha256` token from `vault_read(include_update_token=True)`, while preserving custom frontmatter and keeping identity fields read-only.
12. ~~Implement Hermes Skill Drafting v1~~ - **DONE** (2026-06-06). Lead agents can request Hermes skill drafts, review bounded previews, approve one pending draft to create a new `SKILLS_DIR/{name}/SKILL.md`, or reject it without writing. Hermes still cannot write files directly.
13. ~~Windows Full-Suite Portability Hardening v1 committed as `7cc9c48a`~~ — targeted checks passed 13/08; Core CI on GitHub is the current full-suite proof.
14. ~~Wave B migrate (project DB) + Wave D CLI/API E2E~~ — **DONE** (2026-08-19). Project DB is `00000010`. Vault path set. Live ingest/search/write + permission ask verified. Core lint/tests green on `913c1cd1`.
15. ~~Wave C Bun + `base-url` `"undefined"` guard~~ — **DONE** (2026-08-19). Official `bun.exe` 1.3.14, guard + tests, isolated notification worker path on Windows, Vite via bun on `:5173` proxies `/api/health/live` → 200, no `undefined/api`.
16. **Next (Codex): rotate the leaked Google browser-harness key** (user must supply a new key; do not print/commit secrets). Then optional `PRAGMA foreign_keys=ON` + Windows migrate lock (backup project DB first). Wave E (ADR-003 + Hermes Bridge) stays blocked until a live Hermes gateway exists. Do not mix upstream-sync with the Bridge. Do not re-implement vault/hermes/windows harden. Do not treat the live `:4082` / `:5173` processes as unfinished work — they are the running stack.


## Update Protocol

Update this file continuously:

- At session start: read it first and use it as project memory.
- During work: update it after meaningful decisions, implementation milestones, blockers, or changed assumptions.
- Before ending a task: update `Last updated`, `Implementation Status`, and `Next Implementation Steps`.
- Keep the file concise. Move detailed logs elsewhere if it grows too large, but keep this file as the authoritative current snapshot.
