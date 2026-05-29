import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test'
import type React from 'react'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { loadLastCodingWorkspace } from '@/utils/workspace'
import { useTeamStore } from '@/stores/useTeamStore'

const navigate = mock(() => {})
const originalFetch = globalThis.fetch
const browseResponse = {
  path: '/repo/project',
  parent: '/repo',
  directories: [],
}
const dialogOpen = mock(async () => '/repo/project')
let isTauri = true
let platformOs = 'macos'
let isMobile = false
let validateError: Error | null = null
const deleteSessionMutate = mock(() => {})
const updateSessionTitleMutate = mock(() => {})
type TestSession = {
  id: string
  title: string | null
  agent_name: string | null
  created_at: string | null
  updated_at: string | null
  mode?: string
  workspace?: string | null
  running?: boolean
}

let sessionsData: TestSession[] = []
let workspaceSessionsData: TestSession[] = []
let workspaceHasNextPage = false
let workspaceIsFetchingNextPage = false
const fetchWorkspaceNextPage = mock(() => {})

mock.module('@tanstack/react-router', () => ({
  useNavigate: () => navigate,
}))

mock.module('@/hooks/use-platform', () => ({
  usePlatform: () => ({ isTauri, os: platformOs, isMacOverlay: isTauri && platformOs === 'macos' }),
  getPlatform: () => ({ isTauri, os: platformOs, isMacOverlay: isTauri && platformOs === 'macos' }),
}))

mock.module('@/hooks/use-mobile', () => ({
  useIsMobile: () => isMobile,
}))

mock.module('framer-motion', () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useReducedMotion: () => false,
  motion: {
    aside: ({ children, animate, initial, exit, transition, ...props }: React.ComponentProps<'aside'> & { animate?: unknown; initial?: unknown; exit?: unknown; transition?: unknown }) => {
      void initial
      void exit
      void transition
      return <aside data-animate={JSON.stringify(animate)} {...props}>{children}</aside>
    },
    div: ({ children, initial, animate, exit, transition, ...props }: React.ComponentProps<'div'> & { initial?: unknown; animate?: unknown; exit?: unknown; transition?: unknown }) => {
      void initial
      void animate
      void exit
      void transition
      return <div {...props}>{children}</div>
    },
  },
}))

mock.module('@tauri-apps/plugin-dialog', () => ({
  open: dialogOpen,
}))

const Icon = () => null
mock.module('lucide-react', () => ({
  Check: Icon,
  ChevronDown: Icon,
  ChevronRight: Icon,
  Copy: Icon,
  Download: Icon,
  ExternalLink: Icon,
  FileText: Icon,
  Folder: Icon,
  GitCompare: Icon,
  Globe: Icon,
  HelpCircle: Icon,
  Loader2: Icon,
  Plus: Icon,
  Search: Icon,
  Settings: Icon,
  Pencil: Icon,
  Trash2: Icon,
  X: Icon,
}))

mock.module('@/components/ThemeToggle', () => ({
  ThemeToggle: () => <button aria-label="Theme: System. Click to cycle." />,
}))

mock.module('@/components/HealthDot', () => ({
  HealthDot: () => <div aria-label="Connected" />,
}))

mock.module('@/components/ui/button', () => ({
  Button: ({ children, variant, ...props }: React.ComponentProps<'button'> & { variant?: string }) => {
    void variant
    return <button {...props}>{children}</button>
  },
}))

mock.module('@/components/ui/dialog', () => ({
  Dialog: ({ open, children }: { open: boolean; children: React.ReactNode }) => (open ? <div>{children}</div> : null),
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}))

mock.module('@/queries/useSessionsQuery', () => ({
  queryKeys: {
    team: {
      sessions: {
        infinite: () => ['team', 'sessions', 'infinite'],
        workspace: (workspace: string) => ['team', 'sessions', 'workspace', workspace],
      },
    },
  },
  useTeamSessionsQuery: () => ({
    data: { pages: [{ data: sessionsData }] },
    isFetching: false,
    refetch: mock(() => {}),
  }),
  useCodingWorkspaceSessionsQuery: () => ({
    data: { pages: [{ data: workspaceSessionsData }] },
    isLoading: false,
    hasNextPage: workspaceHasNextPage,
    isFetchingNextPage: workspaceIsFetchingNextPage,
    fetchNextPage: fetchWorkspaceNextPage,
  }),
  useDeleteTeamSessionMutation: () => ({ mutate: deleteSessionMutate }),
  useUpdateTeamSessionTitleMutation: () => ({
    mutate: updateSessionTitleMutate,
    isPending: false,
    isError: false,
  }),
}))

describe('CodingSidebar workspace trust flow', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionsData = []
    workspaceSessionsData = []
    workspaceHasNextPage = false
    workspaceIsFetchingNextPage = false
    isTauri = true
    platformOs = 'macos'
    isMobile = false
    useTeamStore.setState({ isTeamWorking: false, sessionId: null })
    navigate.mockClear()
    dialogOpen.mockReset()
    dialogOpen.mockImplementation(async () => '/repo/project')
    deleteSessionMutate.mockClear()
    updateSessionTitleMutate.mockClear()
    fetchWorkspaceNextPage.mockClear()
    validateError = null
    globalThis.fetch = mock(async (input: unknown) => {
      const url = String(input)
      if (url.startsWith('/api/team/workspace/browse')) {
        return new Response(JSON.stringify(browseResponse))
      }
      if (url.startsWith('/api/team/workspace/validate')) {
        if (validateError) {
          return new Response(JSON.stringify({ detail: validateError.message }), { status: 422 })
        }
        return new Response(JSON.stringify({ workspace: '/repo/project' }))
      }
      if (url === '/api/team/sessions/resolve') {
        return new Response(JSON.stringify({
          id: 'resolved-session',
          title: null,
          agent_name: null,
          mode: 'coding',
          workspace: '/repo/project',
          created_at: null,
          updated_at: null,
          created: true,
        }))
      }
      return new Response(null, { status: 404 })
    }) as typeof fetch
  })

  afterEach(() => {
    cleanup()
    globalThis.fetch = originalFetch
  })

  async function renderCodingSidebar() {
    const { CodingSidebar } = await import('@/components/CodingSidebar')
    const queryClient = new QueryClient()
    let view: ReturnType<typeof render> | undefined
    await act(async () => {
      view = render(
        <QueryClientProvider client={queryClient}>
          <CodingSidebar openWorkspaceDialogKey={1} />
        </QueryClientProvider>,
      )
      await Promise.resolve()
    })
    return view
  }

  async function renderCodingSidebarForSessions(currentSessionId?: string) {
    const { CodingSidebar } = await import('@/components/CodingSidebar')
    const queryClient = new QueryClient()
    let view: ReturnType<typeof render> | undefined
    await act(async () => {
      view = render(
        <QueryClientProvider client={queryClient}>
          <CodingSidebar currentSessionId={currentSessionId} workspace="/repo/project" />
        </QueryClientProvider>,
      )
      await Promise.resolve()
    })
    return view
  }

  async function renderCodingSidebarWithProps(props: React.ComponentProps<typeof import('@/components/CodingSidebar').CodingSidebar>) {
    const { CodingSidebar } = await import('@/components/CodingSidebar')
    const queryClient = new QueryClient()
    let view: ReturnType<typeof render> | undefined
    await act(async () => {
      view = render(
        <QueryClientProvider client={queryClient}>
          <CodingSidebar {...props} />
        </QueryClientProvider>,
      )
      await Promise.resolve()
    })
    return view!
  }

  it('does not navigate or save the last workspace until the user trusts the validated directory', async () => {
    const user = userEvent.setup()
    let resolveBody: unknown
    globalThis.fetch = mock(async (input: unknown, init: unknown) => {
      const url = String(input)
      if (url.startsWith('/api/team/workspace/browse')) {
        return new Response(JSON.stringify(browseResponse))
      }
      if (url.startsWith('/api/team/workspace/validate')) {
        return new Response(JSON.stringify({ workspace: '/repo/project' }))
      }
      if (url === '/api/team/sessions/resolve') {
        resolveBody = JSON.parse(String((init as RequestInit | undefined)?.body))
        return new Response(JSON.stringify({
          id: 'resolved-session',
          title: null,
          agent_name: null,
          mode: 'coding',
          workspace: '/repo/project',
          created_at: null,
          updated_at: null,
          created: true,
        }))
      }
      return new Response(null, { status: 404 })
    }) as typeof fetch
    await renderCodingSidebar()

    expect(dialogOpen).toHaveBeenCalledWith({
      directory: true,
      multiple: false,
      title: 'Open workspace',
    })

    expect(screen.getByText('Trust this workspace?')).toBeTruthy()
    expect(screen.getByText('/repo/project')).toBeTruthy()
    expect(navigate).not.toHaveBeenCalled()
    expect(loadLastCodingWorkspace()).toBeNull()

    await user.click(screen.getByRole('button', { name: /trust and open/i }))

    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith({
        to: '/coding/$sessionId',
        params: { sessionId: 'resolved-session' },
      })
    })
    expect(resolveBody).toEqual({
      mode: 'coding',
      workspace: '/repo/project',
      model: null,
      thinking_level: null,
    })
    expect(loadLastCodingWorkspace()?.path).toBe('/repo/project')
  })

  it('uses the native desktop folder picker on Linux desktop too', async () => {
    platformOs = 'linux'

    await renderCodingSidebar()

    expect(dialogOpen).toHaveBeenCalledWith({
      directory: true,
      multiple: false,
      title: 'Open workspace',
    })
    expect(screen.getByText('Trust this workspace?')).toBeTruthy()
    expect(screen.getByText('/repo/project')).toBeTruthy()
  })

  it('keeps the mobile drawer visible after a desktop-collapsed coding sidebar crosses the breakpoint', async () => {
    isMobile = true

    const view = await renderCodingSidebarWithProps({
      desktopCollapsed: true,
      mobileOpen: true,
      workspace: '/repo/project',
    })
    const drawer = view.container.querySelector('aside')

    expect(drawer).toBeTruthy()
    expect(drawer?.className).toContain('mobile-safe-top')
    expect(drawer?.className).toContain('w-[min(272px,calc(100vw-2rem))]')
    expect(JSON.parse(drawer?.getAttribute('data-animate') ?? '{}')).toEqual({
      x: 0,
      width: 'min(272px, calc(100vw - 2rem))',
    })
  })

  it('keeps the mobile backdrop below the app header so macOS traffic lights remain usable', async () => {
    isMobile = true

    const view = await renderCodingSidebarWithProps({ mobileOpen: true })
    const backdrop = view.container.querySelector('[aria-hidden="true"]')

    expect(backdrop).toBeTruthy()
    expect(backdrop?.className).toContain('mobile-safe-top')
    expect(backdrop?.className).toContain('bottom-0')
  })

  it('lets the user go back from the trust warning without opening the workspace', async () => {
    const user = userEvent.setup()
    await renderCodingSidebar()

    expect(await screen.findByText('Trust this workspace?')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /back/i }))

    expect(screen.getByText('Open workspace')).toBeTruthy()
    expect(navigate).not.toHaveBeenCalled()
    expect(loadLastCodingWorkspace()).toBeNull()
  })

  it('shows validation errors without showing the trust confirmation', async () => {
    validateError = new Error('Workspace does not exist')

    await renderCodingSidebar()

    expect(await screen.findByText('Workspace does not exist')).toBeTruthy()
    expect(screen.queryByText('Trust this workspace?')).toBeNull()
    expect(navigate).not.toHaveBeenCalled()
    expect(loadLastCodingWorkspace()).toBeNull()
  })

  it('keeps the server-local browser fallback outside desktop', async () => {
    const user = userEvent.setup()
    isTauri = false

    await renderCodingSidebar()

    expect(dialogOpen).not.toHaveBeenCalled()
    expect(await screen.findByText('/repo/project')).toBeTruthy()

    await user.click(screen.getByRole('button', { name: /open this folder/i }))

    expect(screen.getByText('Trust this workspace?')).toBeTruthy()
    expect(dialogOpen).not.toHaveBeenCalled()
    expect(navigate).not.toHaveBeenCalled()
  })

  it('shows a running indicator on every running coding session', async () => {
    sessionsData = [
      {
        id: 'session-2',
        title: 'Background running session',
        agent_name: 'lead',
        created_at: '2026-05-12T00:00:00Z',
        updated_at: '2026-05-12T00:00:00Z',
        mode: 'coding',
        workspace: '/repo/project',
        running: true,
      },
    ]
    workspaceSessionsData = [
      {
        id: 'session-1',
        title: 'Selected idle session',
        agent_name: 'lead',
        created_at: '2026-05-13T00:00:00Z',
        updated_at: '2026-05-13T00:00:00Z',
        mode: 'coding',
        workspace: '/repo/project',
      },
      {
        id: 'session-2',
        title: 'Background running session',
        agent_name: 'lead',
        created_at: '2026-05-12T00:00:00Z',
        updated_at: '2026-05-12T00:00:00Z',
        mode: 'coding',
        workspace: '/repo/project',
        running: true,
      },
    ]

    await renderCodingSidebarForSessions('session-1')

    expect(screen.getByLabelText('Session running')).toBeTruthy()
    expect(screen.getByText('Selected idle session')).toBeTruthy()
    expect(screen.getByText('Background running session')).toBeTruthy()
  })

  it('keeps running sessions visible when a workspace is collapsed', async () => {
    sessionsData = [
      {
        id: 'session-2',
        title: 'Background running session',
        agent_name: 'lead',
        created_at: '2026-05-12T00:00:00Z',
        updated_at: '2026-05-12T00:00:00Z',
        mode: 'coding',
        workspace: '/repo/project',
        running: true,
      },
    ]
    workspaceSessionsData = sessionsData

    await renderCodingSidebarForSessions(undefined)
    await userEvent.setup().click(screen.getByLabelText('Collapse project'))

    expect(screen.getByLabelText('Expand project')).toBeTruthy()
    expect(screen.getByText('Background running session')).toBeTruthy()
    expect(screen.getByLabelText('Workspace has running session')).toBeTruthy()
    expect(screen.getByLabelText('Session running')).toBeTruthy()
  })

  it('does not create a new session when the current coding session is empty and idle', async () => {
    const user = userEvent.setup()
    sessionsData = [
      {
        id: 'session-1',
        title: null,
        agent_name: 'lead',
        created_at: '2026-05-13T00:00:00Z',
        updated_at: '2026-05-13T00:00:00Z',
        mode: 'coding',
        workspace: '/repo/project',
      },
    ]
    workspaceSessionsData = sessionsData
    useTeamStore.setState({
      sessionId: 'session-1',
      isTeamWorking: false,
      agentNames: ['lead'],
      agentStreams: {
        lead: {
          blocks: [],
          currentBlocks: [],
          currentText: '',
          currentThinking: '',
          status: 'idle',
          usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0, cachedTokens: 0 },
          _completionBase: 0,
          model: null,
          lastError: null,
        },
      },
    })
    const fetchSpy = globalThis.fetch as unknown as ReturnType<typeof mock>

    await renderCodingSidebarForSessions('session-1')
    await user.click(screen.getByLabelText('New session in project'))

    expect(fetchSpy).not.toHaveBeenCalledWith('/api/team/sessions/resolve', expect.anything())
    expect(navigate).not.toHaveBeenCalled()
  })

  it('does not show a running indicator for idle coding sessions', async () => {
    sessionsData = [
      {
        id: 'session-1',
        title: 'Idle session',
        agent_name: 'lead',
        created_at: '2026-05-13T00:00:00Z',
        updated_at: '2026-05-13T00:00:00Z',
        mode: 'coding',
        workspace: '/repo/project',
      },
    ]
    workspaceSessionsData = sessionsData

    await renderCodingSidebarForSessions('session-1')

    expect(screen.queryByLabelText('Session running')).toBeNull()
  })

  it('loads more sessions at the bottom of a workspace session list', async () => {
    const user = userEvent.setup()
    sessionsData = [
      {
        id: 'session-1',
        title: 'First page session',
        agent_name: 'lead',
        created_at: '2026-05-13T00:00:00Z',
        updated_at: '2026-05-13T00:00:00Z',
        mode: 'coding',
        workspace: '/repo/project',
      },
    ]
    workspaceSessionsData = sessionsData
    workspaceHasNextPage = true

    await renderCodingSidebarForSessions('session-1')
    await user.click(screen.getByRole('button', { name: /load more/i }))

    expect(fetchWorkspaceNextPage).toHaveBeenCalled()
  })

  it('opens title editing from a coding session card', async () => {
    const user = userEvent.setup()
    sessionsData = [
      {
        id: 'session-1',
        title: 'Old title',
        agent_name: 'lead',
        created_at: '2026-05-13T00:00:00Z',
        updated_at: '2026-05-13T00:00:00Z',
        mode: 'coding',
        workspace: '/repo/project',
      },
    ]
    workspaceSessionsData = sessionsData

    await renderCodingSidebarForSessions('session-1')
    await user.click(screen.getByLabelText('Edit session Old title'))
    const input = screen.getByLabelText('Session title')
    await user.clear(input)
    await user.type(input, 'New title')
    await user.click(screen.getByRole('button', { name: /^save$/i }))

    expect(updateSessionTitleMutate).toHaveBeenCalledWith(
      { id: 'session-1', title: 'New title' },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    )
  })

  it('trims title edits before submitting', async () => {
    const user = userEvent.setup()
    sessionsData = [
      {
        id: 'session-1',
        title: 'Old title',
        agent_name: 'lead',
        created_at: '2026-05-13T00:00:00Z',
        updated_at: '2026-05-13T00:00:00Z',
        mode: 'coding',
        workspace: '/repo/project',
      },
    ]
    workspaceSessionsData = sessionsData

    await renderCodingSidebarForSessions('session-1')
    await user.click(screen.getByLabelText('Edit session Old title'))
    const input = screen.getByLabelText('Session title')
    await user.clear(input)
    await user.type(input, '  New title  ')
    await user.click(screen.getByRole('button', { name: /^save$/i }))

    expect(updateSessionTitleMutate).toHaveBeenCalledWith(
      { id: 'session-1', title: 'New title' },
      expect.anything(),
    )
  })

  it('does not submit empty title edits', async () => {
    const user = userEvent.setup()
    sessionsData = [
      {
        id: 'session-1',
        title: 'Old title',
        agent_name: 'lead',
        created_at: '2026-05-13T00:00:00Z',
        updated_at: '2026-05-13T00:00:00Z',
        mode: 'coding',
        workspace: '/repo/project',
      },
    ]
    workspaceSessionsData = sessionsData

    await renderCodingSidebarForSessions('session-1')
    await user.click(screen.getByLabelText('Edit session Old title'))
    const input = screen.getByLabelText('Session title')
    await user.clear(input)
    await user.type(input, '   ')

    expect(screen.getByRole('button', { name: /^save$/i }).hasAttribute('disabled')).toBe(true)
    await user.keyboard('{Enter}')
    expect(updateSessionTitleMutate).not.toHaveBeenCalled()
  })

  it('selects another coding session after deleting the current one', async () => {
    const user = userEvent.setup()
    sessionsData = [
      {
        id: 'session-1',
        title: 'Delete me',
        agent_name: 'lead',
        created_at: '2026-05-13T00:00:00Z',
        updated_at: '2026-05-13T00:00:00Z',
        mode: 'coding',
        workspace: '/repo/project',
      },
      {
        id: 'session-2',
        title: 'Keep me',
        agent_name: 'lead',
        created_at: '2026-05-12T00:00:00Z',
        updated_at: '2026-05-12T00:00:00Z',
        mode: 'coding',
        workspace: '/repo/project',
      },
    ]
    workspaceSessionsData = sessionsData

    await renderCodingSidebarForSessions('session-1')
    await user.click(screen.getByLabelText('Delete session Delete me'))
    await user.click(screen.getByRole('button', { name: /^delete$/i }))

    expect(deleteSessionMutate).toHaveBeenCalledWith('session-1')
    expect(navigate).toHaveBeenCalledWith({
      to: '/coding/$sessionId',
      params: { sessionId: 'session-2' },
      replace: true,
    })
    expect(loadLastCodingWorkspace()?.path).toBe('/repo/project')
  })

  it('requires confirmation before deleting a coding session', async () => {
    const user = userEvent.setup()
    sessionsData = [
      {
        id: 'session-1',
        title: 'Delete me',
        agent_name: 'lead',
        created_at: '2026-05-13T00:00:00Z',
        updated_at: '2026-05-13T00:00:00Z',
        mode: 'coding',
        workspace: '/repo/project',
      },
    ]
    workspaceSessionsData = sessionsData

    await renderCodingSidebarForSessions('session-1')
    await user.click(screen.getByLabelText('Delete session Delete me'))

    expect(deleteSessionMutate).not.toHaveBeenCalled()
    expect(screen.getByText('Delete session')).toBeTruthy()
    expect(screen.getByText(/will be permanently deleted/i)).toBeTruthy()

    await user.click(screen.getByRole('button', { name: /^delete$/i }))

    expect(deleteSessionMutate).toHaveBeenCalledWith('session-1')
    expect(navigate).toHaveBeenCalledWith({ to: '/coding', replace: true })
  })
})
