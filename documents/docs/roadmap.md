---
title: Roadmap
description: Public roadmap for OpenAgentd — what's next, what we're considering, and what we've decided not to do, with reasons.
status: living
updated: 2026-05-25
---

# Roadmap

OpenAgentd is Apache 2.0 and developed in the open. This page lists what we're
planning, considering, or deliberately *not* doing. For everything already
shipped, see [`features.md`](./features.md) — that doc is the authoritative
record of what the product does today.

## How we plan

- **No dated promises.** One maintainer, real life. We use `Soon`, `Later`,
  `Considering` instead of versions so a slip doesn't become a broken promise.
- **`features.md` is the past. `roadmap.md` is the future.** When an item
  ships, its row moves to `features.md` with the version tag, and the row here
  is deleted.
- **Disagree publicly.** If a `Considering`, `Deferred`, or `Won't do` item is
  important to you, open an issue tagged `roadmap` with the use case. Most
  decisions here flip with one good reason.
- **Champions move things up.** A `Considering` item with a willing
  designer/tester usually becomes `Soon`.

## Status

| Status | Meaning |
|---|---|
| **Soon** | Committed for the next release. Code likely in flight. |
| **Later** | We intend to do this; no release picked yet. |
| **Considering** | On the table; needs a design call or a user pull first. |
| **Deferred** | Was on the list, paused for the reason given. |
| **Won't do** | Out of scope, with a reason. Reopen with a use case. |

---

## What's next

The shortlist for the next release. Everything else lives in the pillar tables
below.

- Inject queued message into a running turn (today the queue activates only between turns).
- Per-response running token total + cumulative session total, persisted through `/compact`.
- Group "explored" tool calls so long inspector logs stay scannable.
- Menubar: prev / next session, prev / next coding project.
- UI state persisted on disk under `{STATE_DIR}/ui.json` instead of `localStorage`.
- Fenced code blocks inside markdown files render correctly.
- New providers: Qwen, LMStudio, Anthropic OAuth.
- Migration imports for Claude Code, Codex CLI, opencode.

---

## Cockpit and chat UX

| Item | Status | Notes |
|---|---|---|
| Codeblock-in-markdown rendering fix | Soon | Fenced code blocks inside `.md` render wrong. Renderer/sanitizer bug. |
| Group "explored" tool calls | Soon | Collapse repeated `read` / `grep` / `glob` into one summary node — cuts inspector noise on long sessions and makes the agent's actual decisions easier to scan. |
| Menubar prev/next session + project | Soon | Keyboard navigation across sessions and (in coding mode) workspaces. |
| UI state persisted on disk | Soon | OpenAgentd is on-machine — UI prefs belong in `{STATE_DIR}/ui.json`, not `localStorage`. Keep device-specific bits separate. |
| Line-range mentions (`@file.py:42-58`) | Later | Extension of the shipped `@file` auto-attach. Select lines in the workspace files panel, diff view, or `@file` preview → composer pill `@file.py:42-58` → backend slices N–M instead of attaching the whole file. Lets the user point precisely at code and add a comment around it (*"this [@app/main.py:42-58] should handle the None case"*) without dumping the whole file into context. Single-line shorthand: `@file.py:42`. |
| Multi-window (same sidecar) | Considering | Multi-client SSE is already supported; needs a Tauri shell change. |
| Configurable theme / color UI | Considering | Wait until the v1 theme is final. |
| Export / share a session (HTML or Markdown) | Considering | Frequently requested shape; small effort. Local-only by default — render a static HTML file the user shares however they want, no third-party hosting. |
| Global "Stop all agents" panic button | Considering | Safety net once teams grow. |
| Customizable keybinds | Considering | A `keybinds.yaml` under config; Settings already has the surface. Power-user request. |
| `!cmd` shell directly from composer | Considering | Overlaps with the `shell` tool. Low pull. |

Shipped cockpit features: [`features.md §1`](./features.md#1-the-desktop-cockpit).

## Agents and teams

| Item | Status | Notes |
|---|---|---|
| Inject queued message into a running turn | Soon | Splice at the next LLM-step boundary; not mid-tool-call. |
| Agent asks the user a question | Later | Real "ask user" tool — pauses the loop, prompts the UI, resumes on answer. |
| `/goal` mode with structured-output evaluator | Later | Planner + executor + evaluator. Evaluator uses provider-native structured output, no free-text parsing. Tight scope, no backtracking in v1. |
| `/btw` — fork a session for a side question | Deferred | Useful but low pull. Re-evaluate when 3+ users ask. |

Shipped team features: [`features.md §2`](./features.md#2-agents-and-teams).

## Coding workspace

| Item | Status | Notes |
|---|---|---|
| Git worktree support | Later | One worktree per coding session, auto-pruned on session delete. Unblocks parallel agents on the same repo without filesystem contention. |
| Auto-format after write/edit | Considering | Run language formatters (`prettier`, `ruff`, `gofmt`, etc.) on files the agent writes. Stops "agent change reverted by save hook" loops in strict-formatted projects. |
| LSP servers for coding mode | Considering | Surface diagnostics back to the agent loop. High cost, marginal value vs. a good `grep` + `read` loop today — revisit when a user pulls hard. |

Shipped coding features: [`features.md §3`](./features.md#3-the-coding-workspace).

## Memory

| Item | Status | Notes |
|---|---|---|
| Running token totals persisted through `/compact` | Soon | Today the running count resets on summarization. Keep it in summary metadata. |
| Per-project wiki memory | Later | `wiki/projects/{workspace_hash}/` auto-scoped when a coding workspace is attached. |
| Cross-session conversation search | Considering | Full-text search over past session transcripts (not just the wiki). Surfaces "did we already solve this?" without forcing the dream agent to promote everything. |
| Dream agent writes skills, not just wiki pages | Considering | Extension of the existing consolidation loop — when the dream agent sees a repeated pattern, emit a draft `SKILL.md` the user can review and accept. |
| Broader wiki / memory rework | Considering | Hold until per-project wiki ships and reveals a concrete gap. |

Shipped memory features: [`features.md §4`](./features.md#4-memory-and-context).

## Providers and extensions

| Item | Status | Notes |
|---|---|---|
| Qwen (API key + qwencode) | Soon | |
| LMStudio | Soon | |
| Anthropic Claude OAuth | Soon | Pro/Max subscription path alongside the existing API key. |
| Migration imports (Claude Code, Codex CLI, opencode) | Soon | We already migrate from OpenClaw and Hermes. Add the three big competitors so a switch is one command, not a manual rewrite of `AGENTS.md` + agent files. |
| Voice memo transcription (uploaded audio) | Considering | Today voice input is push-to-talk only. Allow dropping an `.m4a` / `.mp3` into chat and have it transcribed locally via the existing Whisper path. |
| Tighter Router9 integration | Considering | Already supported as a provider; clarify what "tighter" means before scoping. |
| `discover_skill` + drop blanket auto-injection | Considering | Risk: adds latency and non-determinism on every turn. Likely compromise: keep tiny always-on skills auto-injected, expose the rest via `discover_skill`. |
| Audio generation tool | Won't do | No concrete use case identified. Reopen with one. |

Shipped providers and extensions: [`features.md §5`](./features.md#5-providers-and-models), [`§7`](./features.md#7-extension-surface).

## Observability and cost

| Item | Status | Notes |
|---|---|---|
| Per-response + cumulative token total in chat | Soon | Beside each assistant reply; aggregated for the session. |
| Per-provider cost calculation | Later | Per-call $ for API-key providers via a pricing table. OAuth subscriptions display "subscription", not a fake number. |
| Telemetry rework / consolidation | Considering | Hold until tokens and cost ship and the real gap is visible. |

Shipped observability features: [`features.md §9`](./features.md#9-observability).

## Embed, integrations, and SDKs

| Item | Status | Notes |
|---|---|---|
| Typed JS/TS SDK over the existing REST + SSE API | Considering | We already document the API; an SDK is a thin generated wrapper. Lowers the bar for community-built frontends and integrations. |
| GitHub integration (mention the agent in issues / PRs) | Considering | Runs in a GitHub Actions runner against a repo, posts back. Big shift; depends on the decouple decision below. |
| GitLab CI integration | Considering | Same shape as the GitHub item; same dependency. |
| ACP (Agent Client Protocol) support | Considering | Emerging standard for editor ↔ agent communication. Worth tracking, not yet worth committing. |

Shipped API surface: [`features.md §12`](./features.md#12-embed-and-api).

## Distribution and architecture

The largest pending decision. Most items here depend on a single fork:
*do we make the CLI / server a first-class remote backend that any frontend
(desktop, mobile, channels) can point at?* If yes, the rest of this section
unlocks. If no, OpenAgentd stays desktop-first and most of these become
permanent `Won't do`s.

| Item | Status | Notes |
|---|---|---|
| Decouple CLI / server from the desktop shell (`base_url`) | Considering | Fork in the road. Don't pick up unless committing to multi-frontend. |
| Built-in Tailscale to the sidecar | Considering | Only meaningful if the decouple decision lands first. |
| Deep link `openagentd://` scheme | Considering | No concrete use case identified — open an issue if you have one. |
| Mobile app (iOS / Android) | Considering | Depends on the decouple decision. Web UI is already phone-first. |
| Messaging channels (Telegram, Slack, Discord, Signal, …) | Considering | Each channel is a multi-week integration with its own auth + lifecycle + formatting rules. A gateway approach scales better than one-off integrations — defer the whole class until the decouple decision lands and a per-channel champion appears. |
| Windows desktop | Won't do | Removed in v1.23.0. Use WSL2 + CLI. Reopen if a maintainer commits. |
| Docker image | Won't do | Removed in v1.23.0. Revisit with concrete self-hoster demand. |
| Port hot paths to Rust | Won't do | LLM latency dominates; Python isn't the bottleneck. Rewrite a specific function if needed, not "parts". |

Shipped distribution features: [`features.md §11`](./features.md#11-distribution-and-updates).

---

## How to contribute to the roadmap

- **Push back on a status.** If `Won't do` or `Deferred` is wrong for your
  use case, open an issue tagged `roadmap` with the concrete scenario.
- **Champion a `Considering` item.** Commit to design + testing and it
  usually moves to `Soon`.
- **Suggest a new item.** Open an issue; if it lands here, we'll add a row
  with status and a one-line rationale.

When an item ships, its row moves to [`features.md`](./features.md) under the
right pillar with the `[vX.Y.Z]` tag, and disappears from this page. The
`updated:` date in the frontmatter gets bumped.
