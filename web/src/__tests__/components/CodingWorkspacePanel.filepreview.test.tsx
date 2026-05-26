import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test'
import type React from 'react'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { WorkspaceFileInfo } from '@/api/types'

const WORKSPACE = '/repo/project'
const readme: WorkspaceFileInfo = { path: 'README.md', name: 'README.md', size: 24, mtime: 1, mime: 'text/markdown' }
const image: WorkspaceFileInfo = { path: 'assets/logo.png', name: 'logo.png', size: 100, mtime: 1, mime: 'image/png' }
const binary: WorkspaceFileInfo = { path: 'dist/app.bin', name: 'app.bin', size: 100, mtime: 1, mime: 'application/octet-stream' }
const filesResponse = { workspace: WORKSPACE, truncated: false, files: [readme, image, binary] }

const Icon = () => null
mock.module('lucide-react', () => ({
  Check: Icon,
  ChevronRight: Icon,
  Copy: Icon,
  Download: Icon,
  ExternalLink: Icon,
  FileText: Icon,
  Folder: Icon,
  GitCompare: Icon,
  Loader2: Icon,
  RefreshCw: Icon,
  X: Icon,
}))
mock.module('@/hooks/useReducedMotion', () => ({ useReducedMotion: () => false }))
mock.module('framer-motion', () => ({
  motion: {
    aside: ({ children, className, 'aria-label': ariaLabel }: { children: React.ReactNode; className?: string; 'aria-label'?: string }) => (
      <aside className={className} aria-label={ariaLabel}>{children}</aside>
    ),
  },
}))
mock.module('@/utils/workspace', () => ({ workspaceLabel: (path: string) => path.split('/').at(-1) ?? path }))

beforeEach(() => {
  globalThis.fetch = mock(async (input: unknown) => {
    const url = String(input)
    if (url.includes('/workspace/files/list')) return new Response(JSON.stringify(filesResponse))
    if (url.includes('/workspace/files/read')) return new Response('const value = 1\n// comment\nreturn value')
    if (url.includes('/workspace/git-diff')) return new Response(JSON.stringify({ workspace: WORKSPACE, is_git_repo: false, diff: '' }))
    return new Response(null, { status: 404 })
  }) as typeof fetch
})

afterEach(cleanup)

async function renderWorkspacePanel(onFileSelect = mock(() => {}), selectedFilePath: string | null = null) {
  const { CodingWorkspacePanel } = await import('@/components/CodingWorkspacePanel')
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  await act(async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <CodingWorkspacePanel workspace={WORKSPACE} open initialTab="files" selectedFilePath={selectedFilePath} onFileSelect={onFileSelect} onClose={() => {}} />
      </QueryClientProvider>,
    )
  })
}

async function renderViewer(file: WorkspaceFileInfo | null = readme, onAddComment = mock(() => {})) {
  const { CodingFileViewerPanel } = await import('@/components/CodingFileViewerPanel')
  await act(async () => {
    render(<CodingFileViewerPanel workspace={WORKSPACE} file={file} onClose={() => {}} onAddComment={onAddComment} />)
  })
}

describe('Coding workspace two-layer file preview', () => {
  it('keeps the workspace file tree visible and emits selected file to parent', async () => {
    const user = userEvent.setup()
    const onFileSelect = mock(() => {})
    await renderWorkspacePanel(onFileSelect)
    await waitFor(() => expect(screen.getByText('README.md')).toBeTruthy())

    await user.click(screen.getByTitle('README.md'))

    expect(onFileSelect).toHaveBeenCalledWith(readme)
    expect(screen.getByRole('button', { name: /files/i })).toBeTruthy()
    expect(screen.getByText('README.md')).toBeTruthy()
  })

  it('highlights the selected file path and emits null when clicked again', async () => {
    const user = userEvent.setup()
    const onFileSelect = mock(() => {})
    await renderWorkspacePanel(onFileSelect, 'README.md')
    await waitFor(() => expect(screen.getByTitle('README.md')).toBeTruthy())

    expect(screen.getByTitle('README.md').className).toContain('text-(--color-accent)')
    await user.click(screen.getByTitle('README.md'))

    expect(onFileSelect).toHaveBeenCalledWith(null)
  })

  it('renders text files with a read-only IDE-style line-number gutter', async () => {
    await renderViewer(readme)

    await waitFor(() => expect(screen.getByText('const')).toBeTruthy())
    expect(screen.getAllByText('1').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('2')).toBeTruthy()
    expect(screen.getByText('3')).toBeTruthy()
    expect(screen.getByText('// comment')).toBeTruthy()
    expect(screen.getByText('return')).toBeTruthy()
  })

  it('renders images inline in the separate file viewer panel', async () => {
    await renderViewer(image)
    const img = screen.getByRole('img', { name: 'logo.png' }) as HTMLImageElement
    expect(img.src).toContain('workspace/files/read')
    expect(img.src).toContain('logo.png')
  })

  it('shows binary fallback links in the separate file viewer panel', async () => {
    await renderViewer(binary)
    expect(screen.getByText('No inline preview for this file type')).toBeTruthy()
    expect(screen.getByRole('link', { name: /open in new tab/i })).toBeTruthy()
    expect(screen.getAllByRole('link', { name: /download/i }).length).toBeGreaterThanOrEqual(1)
  })

  it('copy button fetches text content and writes it to the clipboard', async () => {
    const user = userEvent.setup()
    const writeText = mock(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })

    await renderViewer(readme)
    await user.click(screen.getByRole('button', { name: /copy file contents/i }))

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('const value = 1\n// comment\nreturn value'))
  })

  it('lets users select preview lines and add a line comment reference', async () => {
    const user = userEvent.setup()
    const onAddComment = mock(() => {})
    await renderViewer(readme, onAddComment)
    await waitFor(() => expect(screen.getByText('const')).toBeTruthy())

    await user.click(screen.getByRole('button', { name: /const value = 1/i }))
    await user.click(screen.getByRole('button', { name: /add comment for line 1/i }))

    expect(onAddComment).toHaveBeenCalledWith('README.md', 1, 1)
  })
})
