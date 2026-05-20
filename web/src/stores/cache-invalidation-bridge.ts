/**
 * Cache-invalidation bridge.
 *
 * The team store's SSE reducer enqueues domain events on its
 * ``cacheInvalidations`` queue rather than calling
 * ``queryClient.invalidateQueries`` directly — that keeps the store
 * free of TanStack imports and decouples streaming logic from the
 * cache layer.
 *
 * This module owns the small mapping from those domain events to
 * concrete TanStack invalidation calls.  ``routes/team.tsx`` wires a
 * Zustand subscriber that drains the queue on change and hands the
 * events to ``applyCacheInvalidations``.
 *
 * Kept as a pure function (no React, no hooks) so it can be unit
 * tested with a mock ``QueryClient`` and so the React component
 * stays a thin glue layer.
 */
import type { InfiniteData, QueryClient } from '@tanstack/react-query'
import type { CacheInvalidation } from '@/stores/useTeamStore'
import type { SessionPageResponse, WorkspaceGitDiffResponse } from '@/api/types'
import { getCodingWorkspaceGitDiff } from '@/api/client'
import { queryKeys } from '@/queries'

/**
 * Translate domain cache-invalidation events into TanStack
 * ``invalidateQueries`` calls.  One ``invalidateQueries`` call per
 * event — TanStack's invalidation is idempotent, so duplicate events
 * (e.g. two ``schedule_task`` calls in the same turn) are cheap.
 *
 * Unknown ``event.kind`` values are a TypeScript error at compile
 * time; the exhaustive switch ensures every variant of
 * ``CacheInvalidation`` has an explicit branch.
 */
type BridgeQueryClient = Pick<
  QueryClient,
  'invalidateQueries' | 'getQueryData' | 'setQueryData'
>

export function applyCacheInvalidations(
  queryClient: BridgeQueryClient,
  events: readonly CacheInvalidation[],
): void {
  for (const event of events) {
    switch (event.kind) {
      case 'wiki':
        queryClient.invalidateQueries({ queryKey: queryKeys.wiki.all() })
        break
      case 'workspace_files':
        queryClient.invalidateQueries({ queryKey: queryKeys.team.files(event.sessionId) })
        break
      case 'coding_workspace':
        // Coding sidebar shows files + git diff side by side; refresh
        // both panels off the same domain event so the UI catches up
        // immediately after a file mutation or /undo + /redo.
        queryClient.invalidateQueries({ queryKey: queryKeys.coding.files(event.workspace) })
        queryClient.invalidateQueries({ queryKey: queryKeys.coding.diff(event.workspace) })
        queryClient.invalidateQueries({ queryKey: queryKeys.coding.status(event.workspace) })
        break
      case 'coding_workspace_paths':
        // Same coverage as ``coding_workspace`` for files + status —
        // those are cheap full refreshes (~30–100ms typical, capped
        // at 500 entries). The diff query, however, is the expensive
        // one (whole-repo ``git diff -- .`` can hit 800ms on large
        // repos), so we patch its cache directly using a scoped
        // backend call covering only the changed paths.
        queryClient.invalidateQueries({
          queryKey: queryKeys.coding.files(event.workspace),
        })
        queryClient.invalidateQueries({
          queryKey: queryKeys.coding.status(event.workspace),
        })
        void patchCodingDiffForPaths(queryClient, event.workspace, event.paths)
        break
      case 'scheduler':
        queryClient.invalidateQueries({ queryKey: queryKeys.scheduler.list() })
        break
      case 'todos':
        queryClient.invalidateQueries({ queryKey: queryKeys.todos(event.sessionId) })
        break
      case 'team_agents':
        queryClient.invalidateQueries({ queryKey: queryKeys.teamAgents() })
        break
    }
  }
}

/**
 * Splice a per-path git diff into the cached whole-repo diff so the
 * Coding Workspace sidebar refreshes after a tool_end touches a
 * specific file — without paying the full ``git diff -- .`` refetch.
 *
 * Strategy: read the cached diff string, drop any per-file sections
 * whose ``b/<path>`` matches one of ``paths``, then append the
 * server's scoped diff for those paths. Order of files in the diff is
 * cosmetic, so appending is fine.
 *
 * Falls back to a full invalidation when:
 *   - there's no cached diff yet (nothing to splice into);
 *   - the scoped diff fetch fails;
 *   - the cached value isn't shaped as we expect.
 *
 * Best-effort: a failed splice does not leak — invalidating in the
 * catch branch causes a normal whole-repo refresh on next read.
 */
async function patchCodingDiffForPaths(
  queryClient: BridgeQueryClient,
  workspace: string,
  paths: string[],
): Promise<void> {
  if (paths.length === 0) return
  const key = queryKeys.coding.diff(workspace)
  const cached = queryClient.getQueryData<WorkspaceGitDiffResponse>(key)

  // No cached data → the sidebar will fetch a full diff when it
  // mounts; no point doing a scoped fetch we'd just discard.
  if (!cached || !cached.is_git_repo) return

  let scoped: WorkspaceGitDiffResponse
  try {
    scoped = await getCodingWorkspaceGitDiff(workspace, paths)
  } catch {
    queryClient.invalidateQueries({ queryKey: key })
    return
  }

  const merged = mergeScopedDiff(cached.diff, scoped.diff, paths)
  queryClient.setQueryData<WorkspaceGitDiffResponse>(key, {
    ...cached,
    diff: merged,
    truncated: cached.truncated || scoped.truncated,
    untracked: nextUntracked(cached.untracked, scoped.untracked, paths),
  })
}

const DIFF_HEADER_RE = /\ndiff --git a\/(.+?) b\/.+?(?=\ndiff --git |$)/gs
const FIRST_DIFF_HEADER_RE = /^diff --git a\/(.+?) b\/.+?(?=\ndiff --git |$)/s

/**
 * Split a unified diff string into ``[paths_dropped_for_replacement,
 * keeper_text]`` so the caller can append the new scoped diff.
 *
 * The diff format is one ``diff --git a/<path> b/<path>`` block per
 * file; we use that header as a section boundary. Splitting via
 * ``\ndiff --git `` is robust because line-starts are guaranteed not
 * to appear anywhere else in valid output.
 */
export function mergeScopedDiff(
  existingDiff: string,
  scopedDiff: string,
  paths: string[],
): string {
  if (!existingDiff) return scopedDiff
  const pathSet = new Set(paths)

  // Walk the existing diff section-by-section, keeping only sections
  // whose path is NOT in ``paths``. The new content for those paths
  // comes from ``scopedDiff``.
  const kept: string[] = []

  // The first ``diff --git`` may be at index 0 (no leading newline);
  // subsequent ones are preceded by a newline. Handle both.
  let cursor = 0
  const firstMatch = FIRST_DIFF_HEADER_RE.exec(existingDiff)
  if (firstMatch) {
    const path = firstMatch[1]
    if (!pathSet.has(path)) kept.push(firstMatch[0])
    cursor = firstMatch[0].length
  }

  const rest = existingDiff.slice(cursor)
  for (const match of rest.matchAll(DIFF_HEADER_RE)) {
    const path = match[1]
    if (!pathSet.has(path)) kept.push(match[0])
  }

  // Append the scoped diff so the changed paths appear in their new
  // form. Trim a leading newline on the scoped block since ``kept``
  // entries (after the first) already start with one.
  const keptText = kept.join('')
  const scoped = scopedDiff.startsWith('\n') ? scopedDiff : scopedDiff
  if (!keptText) return scoped
  if (!scoped) return keptText
  return scoped.startsWith('\n') || keptText.endsWith('\n')
    ? keptText + scoped
    : keptText + '\n' + scoped
}

/**
 * Merge an untracked-files list with a scoped update. Paths covered
 * by the splice are taken from the scoped response; other entries
 * carry over from the cached value untouched.
 */
function nextUntracked(
  cached: string[] | undefined,
  scoped: string[] | undefined,
  paths: string[],
): string[] | undefined {
  if (!cached && !scoped) return undefined
  const pathSet = new Set(paths)
  const carry = (cached ?? []).filter((p) => !pathSet.has(p))
  return [...carry, ...(scoped ?? [])]
}

/**
 * Patch the cached team session list when a ``title_update`` SSE event
 * arrives.  The list is an infinite query, so cached data is shaped as
 * ``InfiniteData<SessionPageResponse>`` (``{ pages, pageParams }``) — we
 * map each page's ``data`` array, not the wrapper.  An earlier version
 * typed the cache as ``SessionResponse[]`` and silently no-op'd; the
 * sidebar only refreshed on reload.
 *
 * No-ops when the matching session id is absent from every page (e.g.
 * cache was cleared between the SSE event and this patch) — TanStack
 * skips updates whose updater returns the same reference.
 */
export function patchSessionTitle(
  queryClient: Pick<QueryClient, 'setQueriesData'>,
  sessionId: string,
  title: string,
): void {
  queryClient.setQueriesData<InfiniteData<SessionPageResponse>>(
    { queryKey: queryKeys.team.sessions.all() },
    (old) => old && {
      ...old,
      pages: old.pages.map((page) => ({
        ...page,
        data: page.data.map((s) => s.id === sessionId ? { ...s, title } : s),
      })),
    },
  )
}
