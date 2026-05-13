import { beforeEach, describe, expect, it } from 'bun:test'
import {
  codingSessionSearch,
  findCodingWorkspaceById,
  findCodingWorkspaceId,
  loadCodingWorkspaceEntries,
  loadCodingWorkspaces,
  loadLastCodingWorkspace,
  saveCodingWorkspace,
  saveLastCodingWorkspace,
  shouldResetCodingWorkspaceSession,
  shouldRestoreLastCodingWorkspace,
  workspaceFromSessionDetail,
} from '@/utils/workspace'

const STORAGE_KEY = 'oa-coding-workspaces'

describe('coding workspace persistence', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('preserves creation order when an existing workspace is selected again', () => {
    const first = saveCodingWorkspace('/repo/alpha')
    const second = saveCodingWorkspace('/repo/beta')

    const selectedAgain = saveCodingWorkspace('/repo/alpha')

    expect(selectedAgain.createdAt).toBe(first.createdAt)
    expect(loadCodingWorkspaces()).toEqual(['/repo/alpha', '/repo/beta'])
    expect(loadCodingWorkspaceEntries().map((entry) => entry.createdAt)).toEqual([
      first.createdAt,
      second.createdAt,
    ])
  })

  it('migrates legacy string entries without reordering them', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(['/repo/old-a', '/repo/old-b']))

    expect(loadCodingWorkspaces()).toEqual(['/repo/old-a', '/repo/old-b'])

    saveCodingWorkspace('/repo/old-b')

    const entries = loadCodingWorkspaceEntries()
    expect(entries.map((entry) => entry.path)).toEqual(['/repo/old-a', '/repo/old-b'])
    expect(Date.parse(entries[0].createdAt)).toBeLessThan(Date.parse(entries[1].createdAt))
  })

  it('keeps stable ids so /coding?w=... can resolve the stored path', () => {
    const saved = saveCodingWorkspace('/repo/project')

    expect(findCodingWorkspaceById(saved.id)).toBe('/repo/project')
    expect(findCodingWorkspaceById('missing')).toBeNull()
  })

  it('remembers the last opened coding workspace', () => {
    saveLastCodingWorkspace('/repo/alpha')
    const beta = saveLastCodingWorkspace('/repo/beta')

    expect(loadLastCodingWorkspace()).toEqual(beta)
    expect(loadCodingWorkspaces()).toEqual(['/repo/alpha', '/repo/beta'])
  })

  it('returns null when the last workspace id no longer points to a saved workspace', () => {
    const saved = saveLastCodingWorkspace('/repo/project')
    localStorage.setItem(STORAGE_KEY, JSON.stringify([{ ...saved, id: 'other' }]))

    expect(loadLastCodingWorkspace()).toBeNull()
  })

  it('builds session route search from the session workspace first', () => {
    const sessionWorkspace = '/repo/session-workspace'
    const activeWorkspace = '/repo/active-workspace'

    expect(codingSessionSearch(sessionWorkspace, activeWorkspace)).toEqual({
      w: findCodingWorkspaceId(sessionWorkspace),
    })
  })

  it('falls back to the active workspace for session route search', () => {
    const activeWorkspace = '/repo/active-workspace'

    expect(codingSessionSearch(null, activeWorkspace)).toEqual({
      w: findCodingWorkspaceId(activeWorkspace),
    })
  })

  it('does not build session route search when no workspace is known', () => {
    expect(codingSessionSearch(null, null)).toBeUndefined()
  })

  it('resets stale chat state only when changing coding workspaces without a session', () => {
    expect(shouldResetCodingWorkspaceSession('coding', undefined, '/repo/a', '/repo/b')).toBe(true)
    expect(shouldResetCodingWorkspaceSession('coding', 'sid', '/repo/a', '/repo/b')).toBe(false)
    expect(shouldResetCodingWorkspaceSession('normal', undefined, '/repo/a', '/repo/b')).toBe(false)
    expect(shouldResetCodingWorkspaceSession('coding', undefined, '/repo/a', '/repo/a')).toBe(false)
  })

  it('restores the last workspace only on the bare coding route', () => {
    expect(shouldRestoreLastCodingWorkspace('coding', undefined, null, '/coding')).toBe(true)
    expect(shouldRestoreLastCodingWorkspace('coding', 'sid', null, '/coding')).toBe(false)
    expect(shouldRestoreLastCodingWorkspace('coding', undefined, 'w123', '/coding')).toBe(false)
    expect(shouldRestoreLastCodingWorkspace('normal', undefined, null, '/coding')).toBe(false)
  })

  it('does not restore while navigating away from coding mode', () => {
    expect(shouldRestoreLastCodingWorkspace('coding', undefined, null, '/')).toBe(false)
    expect(shouldRestoreLastCodingWorkspace('coding', undefined, null, '/cockpit')).toBe(false)
  })

  it('does not reuse a previous workspace while direct session details are loading', () => {
    expect(workspaceFromSessionDetail('coding', 'sid', null, undefined)).toBeNull()
  })

  it('uses route workspace before session detail workspace when present', () => {
    expect(workspaceFromSessionDetail('coding', 'sid', '/repo/route', '/repo/session')).toBe('/repo/route')
  })

  it('uses loaded session workspace for direct coding session links', () => {
    expect(workspaceFromSessionDetail('coding', 'sid', null, '/repo/session')).toBe('/repo/session')
  })
})
