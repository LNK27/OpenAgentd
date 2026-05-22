---
title: Chat Input & Message Queue
description: How queued follow-up messages work while the team lead is streaming.
status: stable
updated: 2026-05-22
---

# Chat Input & Message Queue

**Sources:** `web/src/stores/useTeamStore/`, `web/src/components/FloatingInputBar.tsx`, `web/src/components/PendingMessageQueue.tsx`, `web/src/components/InputBar.mentions.ts`, `web/src/components/InputBar.overlay.tsx`, `web/src/components/AgentView.tsx` (`renderMentionSegments`), `app/api/routes/team/_helpers.py` (`collect_mention_attachments`)

---

## Consecutive message behaviour

The input bar (`FloatingInputBar` + `InputBar`) is never disabled. Submitting text while the lead is busy persists the message to the backend queue; it is not kept only in browser memory.

**Guard condition** (`sendMessage` in `useTeamStore/index.ts`):

```
lead.status === "working"  →  enqueue
lead.status !== "working"  →  POST /api/team/chat immediately
```

Only the **lead's** status matters. Members running background sub-tasks do not block new input.

Attachments are not queued while the lead is working. The UI asks the user to wait for the current response to finish before sending files.

---

## Queue lifecycle

| Step | What happens |
|------|-------------|
| User submits text while lead is busy | `POST /api/team/chat` stores a hidden `SessionMessage` with `extra.queue_status="queued"` and returns its `message_id` |
| Lead finishes its current activation | Backend emits `queued_turn_start`, pops queued rows in order, keeps the same SSE connection alive, and sends each queued message to the lead mailbox immediately. Team-level `done` still waits for all members to finish; the queue handoff does not wait for every member status to become `idle`. |
| User clicks `/stop` while messages are queued | Backend releases queued rows into normal visible history, removes their queued metadata, stops the stream, and does not activate those messages. Frontend reloads the session so the released messages can be edited with `/undo` or followed by a new message. |
| User reloads or switches sessions | Session history includes queued rows; the frontend rehydrates `_pendingMessages` for the active session |
| User clicks × on a queued item | Frontend removes it and calls `DELETE /api/team/sessions/{session_id}/queued-messages/{message_id}` |
| `newSession()` called | Queue cleared |

Queued messages are never concatenated. Multiple queued messages become separate user rows and separate lead activations unless the user clicks `/stop`, which pauses the queue by converting pending rows into normal history without running them. Queues are session-scoped, so switching from session A to session B does not display A's queued messages under B.

Session Settings may override the lead model and thinking level for the current chat. Sends include those settings, and queued rows keep the effective model metadata so history labels stay tied to the original turn.

---

## `PendingMessage` shape

```ts
interface PendingMessage {
  id: string      // backend message id, used for cancellation
  sessionId?: string | null
  content: string
}
```

Stored in `useTeamStore._pendingMessages: PendingMessage[]`.

---

## UI

`PendingMessageQueue` renders queued messages inside the conversation timeline below the streaming assistant response. Each queued item uses the normal right-aligned user bubble shape with a small × button (labelled "Edit queued message") and a `Queued` label. Clicking × dispatches a `queue:restore-draft` `CustomEvent`; `TeamChatView` listens for it and moves the queued text back into the composer (overwriting any current draft, matching `/undo` semantics) before removing the queued row — so the user can edit or resend instead of losing what they typed.

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
| Picker row | A lucide `Folder` or `File` icon, then the path with the parent directory dimmed and the basename in full text colour. Directories show a trailing `/`. |

### Syntax-highlight rendering

Committed mentions are coloured like editor tokens — no background tint:

| Kind | Colour token | Detection |
|---|---|---|
| File | `--accent-blue-text` | default (no trailing `/`) |
| Folder | `--accent-orange-text` | token ends in `/` |

The textarea is rendered with `color: transparent` + `caret-color: var(--color-text)`, and a mirror `<div>` (`InputBar.overlay.tsx`) paints all glyphs — non-mention text in `--color-text`, mention spans in the kind-specific colour. Standard syntax-highlighter pattern (CodeMirror / react-simple-code-editor). Selection is restored via the `selection:` Tailwind variant so highlighted text stays visible.

`--color-accent` is **not** used for mentions — in the dark palette it equals `--color-text` and would be invisible. The dedicated `--accent-blue-text` / `--accent-orange-text` tokens are theme-safe.

The same colours apply in rendered user message bubbles (`AgentView.tsx` → `renderMentionSegments`). Kind is inferred from the trailing slash (immutable per-message), not from a live `fileRefs` lookup — historical messages keep their colours even after the referenced path is renamed or removed.

Tokens chip **only** when they resolve to a known workspace ref — `@@`, `@nonexistent`, and `@foo@bar` produce no chip. Trailing sentence punctuation (`,` `.` `;` `:` `!` `?` `)`) is stripped before resolution. The actively-typed mention is excluded so the colour doesn't flash on every keystroke.

### Send-time auto-attachment

When the message is dispatched (`POST /api/team/chat`, immediate path only — queued messages are not re-parsed at activation), the backend resolves committed mentions against the session workspace and may attach the referenced file as a `RawAttachment`:

| Mention | Auto-attach behaviour |
|---|---|
| Text file (`.md`, `.txt`, `.json`, …) | Inlined into the prompt with a head + tail window capped at 32K chars (see [API — mention attachments](../api/index.md#mention-auto-attachment)). |
| Document (`.pdf`, `.docx`) | Same — markitdown-converted then truncated head + tail. |
| Image (`.png`, `.jpg`, …) | Reference only. Agent uses its vision-aware `Read` tool on demand. |
| Folder | Reference only. Agent uses `LS` / `Glob` / `Read` on demand. |
| Unresolvable path | Silently skipped — also no chip. |

Helpers live in `InputBar.mentions.ts` (`findActiveMention`, `findCommittedMentions`, `rankFileRefs`). The overlay is `InputBar.overlay.tsx`. The query hook is `useFileRefsQuery.ts`. Backend resolution is `app/api/routes/team/_helpers.py::collect_mention_attachments`.

---

## Voice transcript insertion

Voice input reuses the normal text input path. The mic button records browser
audio, sends it to `POST /api/speech/transcribe`, then appends the returned
transcript to the existing draft via the `onTranscript` callback (handled in
`InputBar`). It does **not** call `sendMessage` automatically.

If the input already contains text, the transcript is appended with a space
rather than replacing the draft. See [`voice-input.md`](./voice-input.md) for
the full state machine and backend contract.
