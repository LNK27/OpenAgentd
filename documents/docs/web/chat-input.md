---
title: Chat Input & Message Queue
description: How the frontend queues messages while the lead is working and drains them after each turn.
status: stable
updated: 2026-05-14
---

# Chat Input & Message Queue

**Sources:** `web/src/stores/useTeamStore/`, `web/src/components/FloatingInputBar.tsx`, `web/src/components/PendingMessageQueue.tsx`, `web/src/components/InputBar.mentions.ts`, `web/src/components/InputBar.overlay.tsx`

---

## Consecutive message behaviour

The input bar (`FloatingInputBar` + `InputBar`) is never disabled. Submitting while the agent is busy does not block or discard the message — it enters a client-side queue.

**Guard condition** (`sendMessage` in `useTeamStore/index.ts`):

```
lead.status === "working"  →  enqueue
lead.status !== "working"  →  POST /api/team/chat immediately
```

Only the **lead's** status matters. Members running background sub-tasks do not block new input.

---

## Queue lifecycle

| Step | What happens |
|------|-------------|
| User submits while lead is busy | Message pushed to `_pendingMessages` (no API call, no optimistic block) |
| SSE `done` event fires | All pending messages combined into one turn (`\n\n` join), files merged, sent as a single `POST /api/team/chat` |
| User clicks × on a queued item | Removed from store; text restored to the input bar |
| `newSession()` called | Queue cleared |

The drain happens in `sse-reducer.ts` inside the `done` case — after flushing `currentBlocks`, the entire queue is consumed at once. This means two queued messages ("then say hi" + "also summarise") become one combined turn, not two sequential ones.

---

## `PendingMessage` shape

```ts
interface PendingMessage {
  id: string      // stable id (pm-<timestamp>), used as React key and for removal
  content: string
  files?: File[]
}
```

Stored in `useTeamStore._pendingMessages: PendingMessage[]`.

---

## UI

`PendingMessageQueue` renders directly above the input bar (both mobile and desktop). It starts collapsed as a `QUEUE · N messages awaiting` banner; clicking the banner expands the queued message details **above** the banner so the banner remains adjacent to the input. Each expanded item shows a clock icon, truncated message preview, optional file count badge, and an × button. Clicking × calls `removePendingMessage(id)` and restores the text via `InputBarHandle.setValue()`.

The desktop floating composer starts as a compact action strip and expands on focus, `Ctrl+I`, New Chat focus, attachment/content insertion, or the Chat affordance. While the lead is streaming, the composer may still minimize when empty and blurred; the compact strip remains recoverable with File, Voice, Chat/Expand, and Send/Stop controls. The streaming placeholder tells the user they can queue a follow-up, type `/stop`, or click stop.

The `InputBarHandle` ref exposes:
- `focus()` — expand the floating composer when needed, then focus the textarea
- `setValue(text)` — expand the floating composer when needed, inject text, and trigger height recalculation

`newSession()` aborts any active team SSE stream and resets the live roster/scroll state before focusing the empty composer, so stale tokens or scroll affordances from the previous session do not leak into the fresh chat.

---

## `@`-mention file/folder picker

Typing `@` (at start of input or after whitespace) opens a picker of workspace files and folders. Same UX as opencode / Cursor / Claude.

| Aspect | Detail |
|---|---|
| Trigger | `@` preceded by start-of-string or whitespace. Email-like `user@host` does **not** trigger. |
| Sources | Files come from `GET /api/team/{sid}/files` (normal mode) or `GET /api/team/workspace/files/list?workspace=…` (`/coding`). Folders are derived from path prefixes client-side. Cached 30s by TanStack Query. |
| Ranking | Fuzzy subsequence via `fuzzysort` (so `dockcom` matches `docker-compose.yml`). Directories get a small bonus so `@src` surfaces the `src/` directory above its children. Empty query lists top-level folders alphabetically. |
| Inserted text | Plain `@path ` for files, `@dir/ ` for directories. The textarea stays plain-text — no structured chips inside the value. |
| Picker row | A lucide `Folder` (accent-tinted) or `File` (subtle-tinted) icon, then the path with the parent directory dimmed and the basename in full text colour. Directories show a trailing `/`. |
| Visual chip | A transparent mirror `<div>` behind the textarea paints a soft accent background at each committed mention's position. The chip renders **only** when the token resolves to a known workspace file or folder — `@@`, `@nonexistent`, and `@foo@bar` produce no chip, matching opencode's exact-match pill semantics. Trailing sentence punctuation (`,` `.` `;` `:` `!` `?` `)`) is stripped before resolution so "look at @README.md, please" chips just `@README.md` and leaves the comma plain. The actively-typed mention is also excluded so the chip doesn't flash on every keystroke before the user commits. |

Helpers live in `InputBar.mentions.ts` (`findActiveMention`, `findCommittedMentions`, `rankFileRefs`). The overlay is `InputBar.overlay.tsx`. The query hook is `useFileRefsQuery.ts`.

---

## Voice transcript insertion

Voice input reuses the normal text input path. The mic button records browser
audio, sends it to `POST /api/speech/transcribe`, then appends the returned
transcript to the existing draft via the `onTranscript` callback (handled in
`InputBar`). It does **not** call `sendMessage` automatically.

If the input already contains text, the transcript is appended with a space
rather than replacing the draft. See [`voice-input.md`](./voice-input.md) for
the full state machine and backend contract.
