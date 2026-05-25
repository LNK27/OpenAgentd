import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test'
import type React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const navigate = mock(() => {})
const updateSessionTitleMutate = mock(() => {})
let sessionsData = [
  {
    id: 'session-1',
    title: 'Old title',
    agent_name: 'lead',
    created_at: '2026-05-13T00:00:00Z',
    updated_at: '2026-05-13T00:00:00Z',
    mode: 'normal',
  },
]

class IntersectionObserverStub {
  observe() {}
  disconnect() {}
}

globalThis.IntersectionObserver = IntersectionObserverStub as unknown as typeof IntersectionObserver

mock.module('@tanstack/react-router', () => ({
  useNavigate: () => navigate,
}))

mock.module('@/hooks/use-mobile', () => ({
  useIsMobile: () => false,
}))

mock.module('@/hooks/useReducedMotion', () => ({
  useReducedMotion: () => true,
}))

const Icon = () => null
mock.module('lucide-react', () => ({
  Folder: Icon,
  HelpCircle: Icon,
  Loader2: Icon,
  Pencil: Icon,
  Plus: Icon,
  RefreshCw: Icon,
  Search: Icon,
  Settings: Icon,
  Trash2: Icon,
}))

mock.module('framer-motion', () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    aside: ({ children, ...props }: React.ComponentProps<'aside'>) => <aside {...props}>{children}</aside>,
    div: ({ children, ...props }: React.ComponentProps<'div'>) => <div {...props}>{children}</div>,
    p: ({ children, ...props }: React.ComponentProps<'p'>) => <p {...props}>{children}</p>,
  },
}))

mock.module('@/components/ThemeToggle', () => ({
  ThemeToggle: () => <button aria-label="Theme: System. Click to cycle." />,
}))

mock.module('@/components/HealthDot', () => ({
  HealthDot: () => <div aria-label="Connected" />,
}))

mock.module('@/components/ui/sidebar-item', () => ({
  SidebarItem: ({ label, onClick }: { label: string; onClick?: () => void }) => <button onClick={onClick}>{label}</button>,
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

mock.module('@/queries', () => ({
  queryKeys: {
    team: {
      sessions: {
        all: () => ['team', 'sessions'],
        infinite: () => ['team', 'sessions', 'infinite'],
        detail: (id: string) => ['team', 'sessions', id],
      },
    },
  },
  useTeamSessionsQuery: () => ({
    data: { pages: [{ data: sessionsData }] },
    isFetching: false,
    isLoading: false,
    isError: false,
    isSuccess: true,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: mock(() => {}),
    refetch: mock(() => {}),
  }),
  useDeleteTeamSessionMutation: () => ({ mutate: mock(() => {}) }),
  useUpdateTeamSessionTitleMutation: () => ({
    mutate: updateSessionTitleMutate,
    isPending: false,
    isError: false,
  }),
}))

describe('Sidebar session title editing', () => {
  beforeEach(() => {
    sessionsData = [
      {
        id: 'session-1',
        title: 'Old title',
        agent_name: 'lead',
        created_at: '2026-05-13T00:00:00Z',
        updated_at: '2026-05-13T00:00:00Z',
        mode: 'normal',
      },
    ]
    navigate.mockClear()
    updateSessionTitleMutate.mockClear()
  })

  afterEach(() => cleanup())

  async function renderSidebar() {
    const { Sidebar } = await import('@/components/Sidebar')
    return render(<Sidebar currentSessionId="session-1" />)
  }

  it('opens the title editor from the edit affordance and submits a trimmed title', async () => {
    const user = userEvent.setup()
    await renderSidebar()

    await user.click(screen.getByLabelText('Edit session Old title'))
    const input = screen.getByLabelText('Session title')
    await user.clear(input)
    await user.type(input, '  New title  ')
    await user.click(screen.getByRole('button', { name: /^save$/i }))

    expect(updateSessionTitleMutate).toHaveBeenCalledWith(
      { id: 'session-1', title: 'New title' },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    )
  })

  it('opens the title editor on session-card double click', async () => {
    const user = userEvent.setup()
    await renderSidebar()

    await user.dblClick(screen.getByText('Old title'))

    expect(screen.getByText('Edit session title')).toBeTruthy()
    expect((screen.getByLabelText('Session title') as HTMLInputElement).value).toBe('Old title')
  })

  it('blocks blank title submissions', async () => {
    const user = userEvent.setup()
    await renderSidebar()

    await user.click(screen.getByLabelText('Edit session Old title'))
    const input = screen.getByLabelText('Session title')
    await user.clear(input)
    await user.type(input, '   ')

    expect(screen.getByRole('button', { name: /^save$/i }).hasAttribute('disabled')).toBe(true)
    await user.keyboard('{Enter}')
    expect(updateSessionTitleMutate).not.toHaveBeenCalled()
  })
})
