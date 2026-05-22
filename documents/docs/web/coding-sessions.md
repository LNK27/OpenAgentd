---
title: Coding Sessions UI
description: Coding-mode session restore, workspace sidebar pagination, and reload/error handling.
status: stable
updated: 2026-05-22
---

# Coding sessions UI

**Sources:** `web/src/components/CodingSidebar.tsx`, `web/src/components/TeamChatView/index.tsx`, `web/src/stores/useTeamStore/`, `web/src/stores/cache-invalidation-bridge.ts`, `web/src/queries/useSessionsQuery.ts`, `app/api/routes/team/chat.py`, `app/services/chat_service.py`

## Session restore and New

- `/cockpit` and workspace-backed `/coding` auto-resolve to the latest matching top-level team session, creating an empty persisted session only when none exists.
- Explicit New actions (`Ctrl+N`, topbar `+`, workspace `+`) force creation instead of resolving latest, except when the current session is already empty and idle.
- Queryless `/coding/{session_id}` remains valid. The frontend loads session detail to recover the persisted workspace and falls back to the current lead name when the backend omits `agent_name` for empty sessions.
- Opening bare `/coding` without a workspace shows the launcher and hides the composer.

## Sidebar session lists

- Coding session lists are scoped per workspace. Expanded workspaces fetch `GET /api/team/sessions?mode=coding&workspace=...` with a page size of 5.
- `Load more` appears at the bottom of the expanded workspace list.
- Collapsed workspaces do not eagerly fetch their own pages; they show running sessions already present in the global session cache.
- New coding sessions are prepended only into the global cache and the matching workspace cache. Workspace prepends keep a short stale window so a 5-row list can temporarily show 6 rows instead of immediately dropping the previous fifth row.
- Deleting a session selects the next available session when possible instead of attempting to reload the deleted session.

## Running and reload states

- Session list/detail/history responses include `running`, derived from the in-memory stream store, so restored active sessions show the chat pending indicator immediately.
- During browser reload/unload, the frontend marks the page as unloading on `beforeunload` and `pagehide`, aborts the active stream, and suppresses only unload-time stream errors. Real active-page `error` events still produce the normal Agent error toast.

## Command palette scope

The command palette omits custom slash commands, Focus Chat Input, and the lead self-switch command. Slash commands remain available from the composer `/` picker, `Ctrl+I` still focuses the composer, and worker-agent view commands remain in the palette.
