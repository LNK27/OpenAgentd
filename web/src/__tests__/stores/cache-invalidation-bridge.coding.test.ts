/**
 * Bridge handling for ``coding_workspace_paths`` — Optimization 2.
 *
 * Splits into its own file because it mocks ``@/api/client`` (the
 * bridge calls ``getCodingWorkspaceGitDiff`` to fetch the scoped diff
 * for splicing). The original bridge test file imports the real
 * client; mocking after import is racy.
 *
 * Covers:
 *   1. Files + status caches invalidated (cheap, full refresh).
 *   2. Cached diff is patched IN PLACE — no full diff invalidation.
 *   3. Path-bearing sections in the cached diff are replaced with the
 *      scoped server response (drop-and-append semantics).
 *   4. No-op when the cache is empty (nothing to splice into).
 *   5. Failed scoped fetch falls back to a full diff invalidation.
 */

import { describe, it, expect, mock, beforeEach } from 'bun:test'

// Inter-file isolation note: ``mock.module("@/api/client", …)`` below
// would leak into other test files if Bun ran them in the same
// worker process. We rely on ``bun test --parallel`` to spawn a
// fresh worker per file — see the same note in
// ``useTeamStore.async.test.ts``.

/* eslint-disable @typescript-eslint/no-explicit-any */
const mockGetDiff = mock(() =>
  Promise.resolve({
    workspace: '/tmp/proj',
    is_git_repo: true,
    diff: '',
    untracked: [],
    truncated: false,
  }),
) as any
;(mock as any).module('@/api/client', () => ({
  getCodingWorkspaceGitDiff: mockGetDiff,
  // Stubs for other exports the bridge module shouldn't trigger but
  // that the type system pulls in.
  postTeamChat: mock(() => Promise.resolve()) as any,
  postTeamCommand: mock(() => Promise.resolve()) as any,
  teamStream: mock(() => {}) as any,
  teamStatus: mock(() => Promise.resolve(null)) as any,
  teamHistory: mock(() =>
    Promise.resolve({ lead: { messages: [] }, members: [], has_more: false, next_cursor: null }),
  ) as any,
  listCodingWorkspaceFiles: mock(() => Promise.resolve({ files: [], truncated: false })) as any,
  getCodingWorkspaceStatus: mock(() => Promise.resolve(null)) as any,
}))
/* eslint-enable @typescript-eslint/no-explicit-any */

import { applyCacheInvalidations, mergeScopedDiff } from '@/stores/cache-invalidation-bridge'
import { queryKeys } from '@/queries'
import { QueryClient } from '@tanstack/react-query'
import type { WorkspaceGitDiffResponse } from '@/api/types'

const WS = '/tmp/proj'

function flushMicrotasks(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

beforeEach(() => {
  mockGetDiff.mockReset()
  mockGetDiff.mockImplementation(() =>
    Promise.resolve({
      workspace: WS,
      is_git_repo: true,
      diff: '',
      untracked: [],
      truncated: false,
    }),
  )
})

// ── mergeScopedDiff — pure splice ────────────────────────────────────────────

describe('mergeScopedDiff', () => {
  const headerA = 'diff --git a/foo b/foo\nindex 1..2 100644\n--- a/foo\n+++ b/foo\n@@ -1 +1 @@\n-a\n+b'
  const headerB = '\ndiff --git a/bar b/bar\nindex 3..4 100644\n--- a/bar\n+++ b/bar\n@@ -1 +1 @@\n-x\n+y'
  const headerC = '\ndiff --git a/baz b/baz\nindex 5..6 100644\n--- a/baz\n+++ b/baz\n@@ -1 +1 @@\n-m\n+n'

  it('returns the scoped diff verbatim when the existing diff is empty', () => {
    expect(mergeScopedDiff('', 'diff --git a/x b/x\n+new', ['x'])).toBe('diff --git a/x b/x\n+new')
  })

  it('drops the matching per-file section and appends the scoped replacement', () => {
    const existing = headerA + headerB
    const scoped = 'diff --git a/foo b/foo\n+++ updated'
    const out = mergeScopedDiff(existing, scoped, ['foo'])
    // ``foo`` section gone from kept text, ``bar`` preserved, scoped appended.
    expect(out).not.toContain('-a\n+b')
    expect(out).toContain('diff --git a/bar b/bar')
    expect(out).toContain('+++ updated')
  })

  it('keeps untouched per-file sections in place', () => {
    const existing = headerA + headerB + headerC
    const out = mergeScopedDiff(existing, 'diff --git a/bar b/bar\n+new bar', ['bar'])
    // foo + baz survive; bar is replaced by the scoped block.
    expect(out).toContain('-a\n+b') // foo intact
    expect(out).toContain('-m\n+n') // baz intact
    expect(out).not.toContain('-x\n+y') // bar dropped
    expect(out).toContain('+new bar')
  })

  it('appends scoped sections for paths absent from the existing diff (new file)', () => {
    // The scoped fetch may carry a diff for a freshly-created file
    // that has no prior diff section to replace.
    const existing = headerA
    const scoped = 'diff --git a/new.ts b/new.ts\nnew file mode 100644\n+content'
    const out = mergeScopedDiff(existing, scoped, ['new.ts'])
    expect(out).toContain('diff --git a/foo b/foo') // existing kept
    expect(out).toContain('diff --git a/new.ts b/new.ts') // new appended
  })

  it('drops sections without re-appending when scoped diff is empty (path reverted to clean)', () => {
    // User modified foo then undid the changes — scoped diff is empty
    // because foo is now identical to HEAD; foo's section must
    // disappear from the cached diff entirely.
    const existing = headerA + headerB
    const out = mergeScopedDiff(existing, '', ['foo'])
    expect(out).not.toContain('diff --git a/foo b/foo')
    expect(out).toContain('diff --git a/bar b/bar')
  })
})

// ── coding_workspace_paths event handling ────────────────────────────────────

describe('applyCacheInvalidations — coding_workspace_paths', () => {
  it('invalidates files + status (cheap full refresh) but NOT diff', async () => {
    const client = new QueryClient()
    const calls: { queryKey: readonly unknown[] }[] = []
    // Override the bound method directly — ``mock(client.x.bind(client))``
    // confuses bun's mock type inference. The cast is intentional:
    // we don't need the full TanStack signature, just call capture.
    /* eslint-disable @typescript-eslint/no-explicit-any */
    client.invalidateQueries = ((args: any) => {
      calls.push(args)
      return Promise.resolve()
    }) as any
    /* eslint-enable @typescript-eslint/no-explicit-any */

    // No cached diff → splice short-circuits, doesn't touch diff cache.
    applyCacheInvalidations(client, [
      { kind: 'coding_workspace_paths', workspace: WS, paths: ['src/a.ts'] },
    ])
    await flushMicrotasks()

    const keys = calls.map((c) => c.queryKey)
    expect(keys).toContainEqual(queryKeys.coding.files(WS))
    expect(keys).toContainEqual(queryKeys.coding.status(WS))
    // No diff invalidation — the splice path owns that cache.
    expect(keys).not.toContainEqual(queryKeys.coding.diff(WS))
  })

  it('patches the cached diff via setQueryData when cache is populated', async () => {
    const client = new QueryClient()
    const cached: WorkspaceGitDiffResponse = {
      workspace: WS,
      is_git_repo: true,
      diff:
        'diff --git a/foo b/foo\n@@ -1 +1 @@\n-old\n+keep\n' +
        '\ndiff --git a/bar b/bar\n@@ -1 +1 @@\n-x\n+y',
      untracked: [],
      truncated: false,
    }
    client.setQueryData(queryKeys.coding.diff(WS), cached)

    mockGetDiff.mockImplementation(() =>
      Promise.resolve({
        workspace: WS,
        is_git_repo: true,
        diff: 'diff --git a/foo b/foo\n@@ -1 +1 @@\n-old\n+NEW',
        untracked: [],
        truncated: false,
      }),
    )

    applyCacheInvalidations(client, [
      { kind: 'coding_workspace_paths', workspace: WS, paths: ['foo'] },
    ])
    await flushMicrotasks()

    expect(mockGetDiff).toHaveBeenCalledWith(WS, ['foo'])
    const after = client.getQueryData<WorkspaceGitDiffResponse>(queryKeys.coding.diff(WS))!
    // foo's hunk was replaced; bar untouched.
    expect(after.diff).toContain('+NEW')
    expect(after.diff).not.toContain('+keep')
    expect(after.diff).toContain('+y')
  })

  it('is a no-op on the diff cache when there is no cached entry', async () => {
    const client = new QueryClient()
    applyCacheInvalidations(client, [
      { kind: 'coding_workspace_paths', workspace: WS, paths: ['foo'] },
    ])
    await flushMicrotasks()

    // No scoped fetch performed — we'd just throw the result away
    // since the panel will fetch a full diff on mount anyway.
    expect(mockGetDiff).not.toHaveBeenCalled()
    expect(client.getQueryData(queryKeys.coding.diff(WS))).toBeUndefined()
  })

  it('falls back to a full diff invalidation when the scoped fetch fails', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.coding.diff(WS), {
      workspace: WS,
      is_git_repo: true,
      diff: 'diff --git a/foo b/foo\n+x',
      untracked: [],
      truncated: false,
    } satisfies WorkspaceGitDiffResponse)

    const calls: { queryKey: readonly unknown[] }[] = []
    /* eslint-disable @typescript-eslint/no-explicit-any */
    client.invalidateQueries = ((args: any) => {
      calls.push(args)
      return Promise.resolve()
    }) as any
    /* eslint-enable @typescript-eslint/no-explicit-any */

    mockGetDiff.mockImplementation(() => Promise.reject(new Error('boom')))

    applyCacheInvalidations(client, [
      { kind: 'coding_workspace_paths', workspace: WS, paths: ['foo'] },
    ])
    await flushMicrotasks()

    const keys = calls.map((c) => c.queryKey)
    expect(keys).toContainEqual(queryKeys.coding.diff(WS))
  })

  it('is a no-op on the diff cache when is_git_repo is false', async () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.coding.diff(WS), {
      workspace: WS,
      is_git_repo: false,
      diff: '',
      untracked: [],
      truncated: false,
    } satisfies WorkspaceGitDiffResponse)

    applyCacheInvalidations(client, [
      { kind: 'coding_workspace_paths', workspace: WS, paths: ['foo'] },
    ])
    await flushMicrotasks()

    // Non-git workspaces have no per-file diffs to splice — saves a
    // pointless backend round-trip.
    expect(mockGetDiff).not.toHaveBeenCalled()
  })
})
