export function normalizeWorkspaceInput(value: string): string | null {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

export function workspaceLabel(workspace: string): string {
  const trimmed = workspace.replace(/[\\/]+$/, '')
  if (!trimmed) return workspace
  return trimmed.split(/[\\/]/).pop() || workspace
}

const CODING_WORKSPACES_KEY = 'oa-coding-workspaces'
export const CODING_WORKSPACE_BUSY_MESSAGE = '1 session per workspace can run at a time.'

export interface CodingWorkspaceEntry {
  id: string
  path: string
  createdAt: string
}

function workspaceId(workspace: string): string {
  let hash = 0
  for (let i = 0; i < workspace.length; i += 1) {
    hash = Math.imul(31, hash) + workspace.charCodeAt(i) | 0
  }
  return `w${(hash >>> 0).toString(36)}`
}

function parseEntries(raw: unknown): CodingWorkspaceEntry[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map((item, index) => {
      const fallbackCreatedAt = new Date(index).toISOString()
      if (typeof item === 'string') return { id: workspaceId(item), path: item, createdAt: fallbackCreatedAt }
      if (item && typeof item === 'object' && 'path' in item && typeof item.path === 'string') {
        const id = 'id' in item && typeof item.id === 'string' ? item.id : workspaceId(item.path)
        const createdAt = 'createdAt' in item && typeof item.createdAt === 'string' ? item.createdAt : fallbackCreatedAt
        return { id, path: item.path, createdAt }
      }
      return null
    })
    .filter((item): item is CodingWorkspaceEntry => item !== null)
}

export function loadCodingWorkspaces(): string[] {
  return loadCodingWorkspaceEntries().map((entry) => entry.path)
}

export function loadCodingWorkspaceEntries(): CodingWorkspaceEntry[] {
  try {
    const raw = localStorage.getItem(CODING_WORKSPACES_KEY)
    return parseEntries(raw ? JSON.parse(raw) : [])
  } catch {
    return []
  }
}

export function saveCodingWorkspace(workspace: string): CodingWorkspaceEntry {
  const entries = loadCodingWorkspaceEntries()
  const existing = entries.find((item) => item.path === workspace)
  const entry = existing ?? { id: workspaceId(workspace), path: workspace, createdAt: new Date().toISOString() }
  const next = existing ? entries : [...entries, entry]
    .sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt))
  try {
    localStorage.setItem(CODING_WORKSPACES_KEY, JSON.stringify(next))
    window.dispatchEvent(new CustomEvent('coding-workspaces-changed'))
  } catch {
    // ignore storage failures
  }
  return entry
}

export function findCodingWorkspaceById(id: string | null): string | null {
  if (!id) return null
  return loadCodingWorkspaceEntries().find((entry) => entry.id === id)?.path ?? null
}

export function findCodingWorkspaceId(workspace: string): string {
  return workspaceId(workspace)
}

export function codingSessionSearch(
  sessionWorkspace: string | null | undefined,
  activeWorkspace: string | null | undefined,
): { w: string } | undefined {
  const workspace = sessionWorkspace ?? activeWorkspace
  return workspace ? { w: workspaceId(workspace) } : undefined
}

export function shouldResetCodingWorkspaceSession(
  mode: 'normal' | 'coding',
  sessionId: string | undefined,
  previousWorkspace: string | null,
  workspace: string | null,
): boolean {
  return mode === 'coding' && !sessionId && previousWorkspace !== workspace
}
