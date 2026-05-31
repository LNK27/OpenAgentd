---
title: Shell commands from chat
description: Run opencode-style `!command` shell commands from the OpenAgentd composer or API without asking the model to decide on a tool call.
status: stable
updated: 2026-05-31
---

# Shell commands from chat

Start a message with `!` to run the rest of the message as a shell command:

```text
!git status --short
!pwd
!pytest -q
```

OpenAgentd dispatches the command directly through the built-in shell tool. The
current turn does **not** call the model first and does not ask the agent whether
to run a tool.

## What is saved in history

Shell sends are stored as normal shell-tool history so the UI, replay, and future
model context stay structured:

1. visible user row: `!<command>`
2. assistant shell tool call with the command arguments
3. shell tool result

Future model turns see an opencode-style synthetic user marker — `The following
tool was executed by the user` — followed by the shell tool call/result. This
keeps command output as tool output rather than user-authored text, while the UI
continues to show the original `!command`.

## Attachments and undo

`!command` sends cannot include file uploads. Use a normal prompt when you need
to attach files.

In coding sessions, a `!command` is a normal visible user turn for `/undo` and
`/redo`: undo can target the `!command` row and restore the associated workspace
snapshot just like any other user turn.

## API

POST to `/api/team/chat` with form data:

| Field | Value |
|-------|-------|
| `message` | `!git status --short` or `git status --short` |
| `shell` | `true` |
| `session_id` | optional existing session UUID |
| `mode`, `workspace` | optional; required for coding mode as usual |

The endpoint returns `202 Accepted` with the `session_id`. Subscribe to
`GET /api/team/{session_id}/stream` for `tool_start`, `tool_output_delta`,
`tool_end`, and `done` events.

## Manual smoke test

```bash
uv run python -m manual.bang_shell
uv run python -m manual.bang_shell --command "pwd && echo oad-bang-shell-ok"
```
