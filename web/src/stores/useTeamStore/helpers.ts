/**
 * Cross-slice helpers for the team store.
 *
 * `WIKI_MUTATING_TOOLS`, `SCHEDULER_MUTATING_TOOLS`, and
 * `TODO_MUTATING_TOOLS` enumerate which tools should trigger TanStack
 * Query cache invalidations on ``tool_end``. Read-only tools (`read`,
 * `ls`, `grep`, `glob`) are intentionally excluded from
 * ``WIKI_MUTATING_TOOLS`` because reads do not invalidate the tree
 * cache.
 *
 * `touchesWiki` decides whether a write/edit/rm tool call landed in
 * the agent's ``wiki/`` root (in which case the wiki query cache is
 * invalidated) or in the session workspace (workspace-files cache).
 * Falls back to a substring check when args are still streaming.
 *
 * `revokeBlobUrlsFromBlocks` releases ObjectURLs created for optimistic
 * file attachments when a ``loadSession`` call replaces the live blocks.
 */
import type { ContentBlock } from '@/api/types'
import type { AgentStream } from './types'

// Tools that can mutate the wiki tree when their `path` argument targets
// the `wiki/` root.  Read-only tools (`read`, `ls`, `grep`, `glob`) are
// intentionally excluded — reads do not invalidate the tree cache.
export const WIKI_MUTATING_TOOLS = new Set(['write', 'edit', 'rm'])

// Tools that touch the filesystem in arbitrary ways. ``shell`` / ``bg``
// are included because their commands routinely create, modify, or
// delete files; ``patch`` rewrites multiple files atomically; the
// ``generate_image`` / ``generate_video`` multimodal tools drop their
// outputs straight into the workspace. The coding-workspace sidebar
// must refresh after any of these even when a specific path isn't
// surfaced in the tool args. Read-only tools (``read``, ``ls``,
// ``grep``, ``glob``) are intentionally absent.
//
// Wiki invalidation still piggybacks on ``WIKI_MUTATING_TOOLS`` +
// ``touchesWiki`` because we don't want to evict the wiki cache on
// every shell call.
export const FS_MUTATING_TOOLS = new Set([
  'write',
  'edit',
  'rm',
  'patch',
  'shell',
  'bg',
  'generate_image',
  'generate_video',
])

// Tools that always write to wiki/notes/ — invalidate the wiki tree
// unconditionally on tool_end (no path check needed).
export const NOTE_TOOLS = new Set(['note'])

// Tools that mutate the scheduler.  On tool_end we invalidate the scheduler
// list so the SchedulerPanel reflects the change without a manual refresh.
export const SCHEDULER_MUTATING_TOOLS = new Set(['schedule_task'])

// todo_manage handles all todo mutations (create, update, delete).
export const TODO_MUTATING_TOOLS = new Set(['todo_manage'])

export function touchesWiki(toolName: string, toolArgs: string | undefined): boolean {
  if (!WIKI_MUTATING_TOOLS.has(toolName)) return false
  if (!toolArgs) return false
  try {
    const parsed = JSON.parse(toolArgs) as { path?: unknown }
    const p = typeof parsed.path === 'string' ? parsed.path : ''
    return p.startsWith('wiki/') || p === 'wiki'
  } catch {
    // Args may still be streaming — fall back to substring check
    return toolArgs.includes('"path":"wiki/') || toolArgs.includes('"path": "wiki/')
  }
}

// Helper to revoke blob URLs from blocks to prevent memory leaks
export function revokeBlobUrlsFromBlocks(blocks: ContentBlock[]) {
  for (const block of blocks) {
    if (block.attachments) {
      for (const att of block.attachments) {
        if (att.url?.startsWith('blob:')) {
          URL.revokeObjectURL(att.url)
        }
      }
    }
  }
}

/**
 * Move blocks across the `blocks` / `_revertedSuffix` split to match a
 * new revert boundary.
 *
 * Invariant: ``blocks ∪ _revertedSuffix`` is the full chronological
 * sequence of finalized blocks this agent has produced; nothing is
 * destroyed by a boundary change. Blocks whose source-message
 * timestamp is ``< boundaryTime`` are visible (``blocks``); the
 * remainder sit in ``_revertedSuffix`` ready for /redo to put back.
 *
 * ``boundaryTime`` is the ms timestamp of the user message at the new
 * boundary, or ``null`` when the boundary is cleared (live tip). The
 * function also recomputes ``revertedCount`` (count of user/compaction
 * blocks in the suffix — matches the server-side count of reverted
 * user messages) and ``revertedMessages`` (up-to-3 preview the
 * ``RevertNotice`` UI displays).
 *
 * Exported separately from the store so `undoTeam` / `redoTeam` can
 * apply the boundary locally instead of falling back to a full
 * ``loadSession`` history refetch — that refetch is the dominant
 * source of /undo + /redo latency.
 */
export function applyRevertBoundary(
  stream: AgentStream,
  boundaryTime: number | null,
): void {
  const all = [...stream.blocks, ...(stream._revertedSuffix ?? [])]

  if (boundaryTime === null) {
    // No boundary — everything is visible.
    stream.blocks = all
    stream._revertedSuffix = []
    stream.revertedCount = 0
    stream.revertedMessages = []
    return
  }

  // Find the first block at-or-after the boundary; everything from
  // there on is reverted. Linear scan is fine — `all` is already in
  // chronological order (parseTeamBlocks sorts by created_at, and
  // suffix entries were appended in order they crossed the boundary).
  let splitIdx = all.length
  for (let i = 0; i < all.length; i++) {
    const t = all[i].timestamp?.getTime() ?? 0
    if (t >= boundaryTime) {
      splitIdx = i
      break
    }
  }

  const visible = all.slice(0, splitIdx)
  const reverted = all.slice(splitIdx)
  stream.blocks = visible
  stream._revertedSuffix = reverted

  // Mirror server-side ``revertedMessageCount`` / ``revertedMessagePreview``:
  // count user-role messages (compaction summaries are role='user' on
  // the wire and parseTeamBlocks splits them into a distinct block
  // type, so we include both here for parity).
  const userBlocks = reverted.filter(
    (b) => b.type === 'user' || b.type === 'compaction',
  )
  stream.revertedCount = userBlocks.length
  stream.revertedMessages = userBlocks
    .map((b) => ({
      role: 'user',
      content: b.type === 'compaction' ? 'Session compacted' : (b.content ?? ''),
    }))
    .filter((m) => m.content.trim().length > 0)
}
