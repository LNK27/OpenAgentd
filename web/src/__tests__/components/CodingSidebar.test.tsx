import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test'
import type React from 'react'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { findCodingWorkspaceId, loadLastCodingWorkspace } from '@/utils/workspace'

const navigate = mock(() => {})
const browseWorkspaces = mock(async () => ({
  path: '/repo/project',
  parent: '/repo',
  directories: [],
}))
const validateWorkspace = mock(async () => ({ workspace: '/repo/project' }))

mock.module('@tanstack/react-router', () => ({
  useNavigate: () => navigate,
}))

const Icon = () => null
mock.module('lucide-react', () => ({
  FolderCode: Icon,
  Home: Icon,
  Loader2: Icon,
  PanelLeftClose: Icon,
  Plus: Icon,
  RefreshCw: Icon,
}))

mock.module('@/api/client', () => ({
  browseWorkspaces,
  validateWorkspace,
}))

mock.module('@/stores/useTeamStore', () => ({
  useTeamStore: { getState: () => ({ newSession: mock(() => {}) }) },
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
  useTeamSessionsQuery: () => ({
    data: { pages: [{ data: [] }] },
    isFetching: false,
    refetch: mock(() => {}),
  }),
  useDeleteTeamSessionMutation: () => ({ mutate: mock(() => {}) }),
}))

describe('CodingSidebar workspace trust flow', () => {
  beforeEach(() => {
    localStorage.clear()
    navigate.mockClear()
    browseWorkspaces.mockClear()
    validateWorkspace.mockClear()
    browseWorkspaces.mockImplementation(async () => ({
      path: '/repo/project',
      parent: '/repo',
      directories: [],
    }))
    validateWorkspace.mockImplementation(async () => ({ workspace: '/repo/project' }))
  })

  afterEach(cleanup)

  async function renderCodingSidebar() {
    const { CodingSidebar } = await import('@/components/CodingSidebar')
    let view: ReturnType<typeof render> | undefined
    await act(async () => {
      view = render(<CodingSidebar openWorkspaceDialogKey={1} />)
      await Promise.resolve()
    })
    return view
  }

  it('does not navigate or save the last workspace until the user trusts the validated directory', async () => {
    const user = userEvent.setup()
    await renderCodingSidebar()

    const openButton = await screen.findByRole('button', { name: /open this folder/i })
    await user.click(openButton)

    expect(validateWorkspace).toHaveBeenCalledWith('/repo/project')
    expect(screen.getByText('Trust this workspace?')).toBeTruthy()
    expect(screen.getByText('/repo/project')).toBeTruthy()
    expect(navigate).not.toHaveBeenCalled()
    expect(loadLastCodingWorkspace()).toBeNull()

    await user.click(screen.getByRole('button', { name: /trust and open/i }))

    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith({
        to: '/coding',
        search: { w: findCodingWorkspaceId('/repo/project') },
      })
    })
    expect(loadLastCodingWorkspace()?.path).toBe('/repo/project')
  })

  it('lets the user go back from the trust warning without opening the workspace', async () => {
    const user = userEvent.setup()
    await renderCodingSidebar()

    await user.click(await screen.findByRole('button', { name: /open this folder/i }))
    await user.click(screen.getByRole('button', { name: /back/i }))

    expect(screen.getByText('Open workspace')).toBeTruthy()
    expect(navigate).not.toHaveBeenCalled()
    expect(loadLastCodingWorkspace()).toBeNull()
  })

  it('shows validation errors without showing the trust confirmation', async () => {
    const user = userEvent.setup()
    validateWorkspace.mockImplementation(async () => {
      throw new Error('Workspace does not exist')
    })

    await renderCodingSidebar()

    await user.click(await screen.findByRole('button', { name: /open this folder/i }))

    expect(await screen.findByText('Workspace does not exist')).toBeTruthy()
    expect(screen.queryByText('Trust this workspace?')).toBeNull()
    expect(navigate).not.toHaveBeenCalled()
    expect(loadLastCodingWorkspace()).toBeNull()
  })
})
