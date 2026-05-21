# OpenAgentd Second Brain Context Snapshot

Last updated: 2026-05-21

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

Phase 1 is partially implemented.

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
- Git worktree already had unrelated added files: `run.ps1` and `web/package-lock.json`. Do not revert them without user approval.

## Next Implementation Steps

1. Verify the end-to-end integration and run tests on OpenAgentd with all Phase 1 components.
2. Implement Phase 2: OpenAgentd Vault Gatekeeper (queued writes, path validation, metadata frontmatter normalization).
3. Implement Phase 2: Human Ingest/Reconcile service to parse and index manual notes.

## Update Protocol

Update this file continuously:

- At session start: read it first and use it as project memory.
- During work: update it after meaningful decisions, implementation milestones, blockers, or changed assumptions.
- Before ending a task: update `Last updated`, `Implementation Status`, and `Next Implementation Steps`.
- Keep the file concise. Move detailed logs elsewhere if it grows too large, but keep this file as the authoritative current snapshot.
