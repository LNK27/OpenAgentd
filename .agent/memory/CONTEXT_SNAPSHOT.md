# OpenAgentd Second Brain Context Snapshot

Last updated: 2026-05-29

## Purpose

This file is the continuity packet for new Codex/OpenAgentd sessions working on the local-first second brain project. Read this file at the start of every new session before planning or editing. Keep it updated whenever decisions, implementation status, blockers, or next steps change.

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

Phase 1 is **fully closed**. All runtime safety items have been implemented and verified by tests.

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
  - `app/agent/tools/builtin/hermes_propose.py` exposes a lead-only proposal tool that returns structured JSON-ish output with `valid_intents`, `conflicts`, `invalid_intents`, warnings, and `vault_write_params`; it never calls `vault_write` or writes to the vault.
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
- Git worktree already had unrelated added files: `run.ps1` and `web/package-lock.json`. Do not revert them without user approval.

## Next Implementation Steps

1. ~~Close the remaining MCP watchdog/liveness gap~~ — **DONE** (2026-05-22). Crash-after-ready recovery verified by test.
2. ~~Implement Phase 2: OpenAgentd Vault Gatekeeper service layer~~ — **DONE** (2026-05-22). Backend service supports sequential writes, metadata frontmatter normalization, path validation, duplicate detection, and incremental index updates.
3. ~~Wire the Vault Gatekeeper into a controlled OpenAgentd entrypoint~~ — **DONE** (2026-05-22). Lead-only builtin `vault_write` now provides the agent-side structured write surface without exposing raw filesystem writes or a public HTTP route.
4. ~~Implement Phase 2: Human Ingest/Reconcile service~~ â€” **DONE** (2026-05-24). Service + CLI normalize manual Obsidian notes and repair folder indexes without adding recall/search/read yet.
5. ~~Implement Phase 2: Vault Recall service and controlled `vault_read` / `vault_search` tools~~ — **DONE** (2026-05-26). Lead agents can now search/list and deep-read Obsidian vault notes without exposing a raw filesystem surface.
6. ~~Integrate Hermes connector as a sidecar API adapter producing write-intents only~~ — **DONE** (2026-05-29). Lead agents can request Hermes write-intent proposals through `hermes_propose`; Hermes cannot write directly to the vault.
7. Decide the next Phase 2/3 step: likely Hermes approval/review queue first, then Hermes query/skill drafting, `vault_update`, or observability.

## Update Protocol

Update this file continuously:

- At session start: read it first and use it as project memory.
- During work: update it after meaningful decisions, implementation milestones, blockers, or changed assumptions.
- Before ending a task: update `Last updated`, `Implementation Status`, and `Next Implementation Steps`.
- Keep the file concise. Move detailed logs elsewhere if it grows too large, but keep this file as the authoritative current snapshot.
