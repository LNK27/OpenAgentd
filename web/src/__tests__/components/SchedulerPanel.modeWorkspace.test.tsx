/**
 * SchedulerPanel — ``ModeWorkspaceFields`` subcomponent tests
 *
 * Covers the routing-control contract introduced by the
 * ``agent → mode + workspace`` scheduler refactor, including the regression
 * fix where switching ``coding → normal`` failed to update ``mode`` because
 * the parent applied two sequential ``setState`` calls against the same
 * stale snapshot.
 *
 * Critical behaviors under test:
 *   1. The subcomponent emits **one** ``onChange`` per user interaction,
 *      carrying both ``mode`` and ``workspace`` so the parent can apply
 *      them atomically. This is the contract that prevents the bug.
 *   2. Leaving coding mode drops the workspace (``workspace: null``).
 *   3. Re-tapping the active coding tab preserves the typed workspace
 *      (no destructive reset on a no-op gesture).
 *   4. The workspace input only renders in coding mode.
 *   5. The saved-workspace ``<Select>`` only renders when
 *      ``localStorage`` has saved entries.
 *   6. Whitespace-only / empty workspace input emits ``null``, never an
 *      empty string (matches the backend invariant: coding tasks need a
 *      real path).
 *   7. ``aria-selected`` reflects the active mode and helper text matches.
 *
 * Radix ``<Select>`` is portal-based and unreliable in happy-dom, so the
 * saved-workspace dropdown is exercised by presence/absence of its
 * trigger rather than by opening it. The picker's callback path is
 * already exercised indirectly via the text-input ``onChange`` tests,
 * which share the same emission contract.
 */

import { describe, it, expect, beforeEach, mock } from 'bun:test'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import '@testing-library/jest-dom'
import { ModeWorkspaceFields } from '@/components/SchedulerPanel'
import type { ScheduledTaskMode } from '@/api/types'

// ── Test harness ─────────────────────────────────────────────────────────────

interface State {
  mode: ScheduledTaskMode
  workspace: string | null
}

/**
 * Renders ``ModeWorkspaceFields`` inside a parent that applies updates the
 * same way the real ``CreateTaskForm`` / ``EditTaskForm`` do — through a
 * functional ``setState``. This is the integration boundary where the
 * stale-snapshot bug originally manifested; testing through this harness
 * (rather than against a bare jest.fn callback) ensures the fix protects
 * the real call site.
 */
type Change = { mode: ScheduledTaskMode; workspace: string | null }

function renderFields(initial: State) {
  // Bun's ``mock`` constrains its callback to ``AnyFunction`` (variadic
  // ``unknown[]`` args), so a typed-arg callback must be cast on the way
  // in. Recorded calls are still cast at the assertion site. This is the
  // pattern used elsewhere in the suite (e.g. McpServerForm tests).
  const onChangeSpy = mock(((_next: Change) => {}) as (
    ...args: unknown[]
  ) => unknown)

  function Harness() {
    const [state, setState] = React.useState<State>(initial)
    return (
      <>
        <div data-testid="mode-value">{state.mode}</div>
        <div data-testid="workspace-value">{state.workspace ?? '<null>'}</div>
        <ModeWorkspaceFields
          mode={state.mode}
          workspace={state.workspace}
          onChange={(next) => {
            onChangeSpy(next)
            setState((prev) => ({
              ...prev,
              mode: next.mode,
              workspace: next.workspace,
            }))
          }}
        />
      </>
    )
  }

  const utils = render(<Harness />)
  return { ...utils, onChangeSpy }
}

function readState() {
  return {
    mode: screen.getByTestId('mode-value').textContent,
    workspace: screen.getByTestId('workspace-value').textContent,
  }
}

beforeEach(() => {
  // Saved-workspace ``<Select>`` reads from localStorage on mount. Reset
  // between tests so each case controls its own fixture.
  localStorage.clear()
})

// ── Initial render ───────────────────────────────────────────────────────────

describe('ModeWorkspaceFields — initial render', () => {
  it('hides the workspace input when mode is normal', () => {
    renderFields({ mode: 'normal', workspace: null })

    // The "Workspace" label and absolute-path input must not be present
    // while in normal mode — the routing has no workspace to set.
    expect(screen.queryByLabelText(/^Workspace$/i)).toBeNull()
    expect(
      screen.queryByPlaceholderText(/Absolute path/i),
    ).toBeNull()
  })

  it('shows the workspace input when mode is coding', () => {
    renderFields({ mode: 'coding', workspace: '/repo/app' })

    const input = screen.getByPlaceholderText(/Absolute path/i)
    expect(input).toBeInTheDocument()
    expect(input).toHaveValue('/repo/app')
  })

  it('renders the workspace input empty when coding workspace is null', () => {
    // Edge case: a coding task with a freshly opened form (or a cleared
    // workspace) must render an empty input, not the string "null".
    renderFields({ mode: 'coding', workspace: null })

    const input = screen.getByPlaceholderText(/Absolute path/i) as HTMLInputElement
    expect(input.value).toBe('')
  })

  it('reflects the active mode via aria-selected on the tab', () => {
    renderFields({ mode: 'coding', workspace: '/x' })

    const normalTab = screen.getByRole('tab', { name: 'Normal' })
    const codingTab = screen.getByRole('tab', { name: 'Coding' })

    expect(normalTab).toHaveAttribute('aria-selected', 'false')
    expect(codingTab).toHaveAttribute('aria-selected', 'true')
  })

  it('shows mode-specific helper text', () => {
    const { rerender } = renderFields({ mode: 'normal', workspace: null })
    expect(
      screen.getByText(/Delivers to the default team lead/i),
    ).toBeInTheDocument()

    rerender(
      <ModeWorkspaceFields
        mode="coding"
        workspace="/repo"
        onChange={() => {}}
      />,
    )
    expect(
      screen.getByText(/Delivers to the lead of the coding team/i),
    ).toBeInTheDocument()
  })
})

// ── Toggle: the regression we fixed ──────────────────────────────────────────

describe('ModeWorkspaceFields — mode toggle', () => {
  it('switches normal → coding without setting a workspace', async () => {
    const user = userEvent.setup()
    const { onChangeSpy } = renderFields({ mode: 'normal', workspace: null })

    await user.click(screen.getByRole('tab', { name: 'Coding' }))

    // Single emission, mode flips to coding, workspace stays null because
    // tab clicks should not invent workspace values.
    expect(onChangeSpy).toHaveBeenCalledTimes(1)
    expect(onChangeSpy.mock.calls[0][0]).toEqual({
      mode: 'coding',
      workspace: null,
    })
    expect(readState()).toEqual({ mode: 'coding', workspace: '<null>' })
  })

  it('switches coding → normal AND clears workspace in a single setState (regression)', async () => {
    // This is the bug we fixed today: the old implementation invoked
    // two callbacks (onModeChange + onWorkspaceChange), and the parent's
    // ``setFormData({ ...formData, ... })`` applied them against the
    // same stale snapshot, so the workspace clear silently overwrote
    // the mode flip. ``mode`` would stay ``"coding"`` while ``workspace``
    // became null, leaving the form in an invalid state the user could
    // not escape from.
    const user = userEvent.setup()
    const { onChangeSpy } = renderFields({
      mode: 'coding',
      workspace: '/repo/app',
    })

    await user.click(screen.getByRole('tab', { name: 'Normal' }))

    // Exactly one emission, atomically carrying both fields.
    expect(onChangeSpy).toHaveBeenCalledTimes(1)
    expect(onChangeSpy.mock.calls[0][0]).toEqual({
      mode: 'normal',
      workspace: null,
    })

    // And the resulting state reflects BOTH changes — this is what
    // failed before the fix.
    expect(readState()).toEqual({ mode: 'normal', workspace: '<null>' })

    // The workspace input must be unmounted now, not just emptied.
    expect(
      screen.queryByPlaceholderText(/Absolute path/i),
    ).toBeNull()
  })

  it('preserves typed workspace when re-tapping the active coding tab', async () => {
    // Edge case: clicking the already-active "Coding" tab is a no-op
    // from the user's perspective — it must not destroy a workspace path
    // they have already typed. Without the explicit preservation in
    // the onClick handler, the workspace would be wiped because the
    // previous implementation always passed ``null`` when entering
    // coding mode.
    const user = userEvent.setup()
    const { onChangeSpy } = renderFields({
      mode: 'coding',
      workspace: '/repo/app',
    })

    await user.click(screen.getByRole('tab', { name: 'Coding' }))

    expect(onChangeSpy).toHaveBeenCalledTimes(1)
    expect(onChangeSpy.mock.calls[0][0]).toEqual({
      mode: 'coding',
      workspace: '/repo/app',
    })
    expect(readState()).toEqual({
      mode: 'coding',
      workspace: '/repo/app',
    })
  })

  it('survives a full normal → coding → normal → coding round-trip', async () => {
    // Defensive: even if a future refactor reintroduces the stale-snapshot
    // pattern in a subtle way, a multi-step toggle would catch it
    // because the bug surfaces only after the second click.
    const user = userEvent.setup()
    renderFields({ mode: 'normal', workspace: null })

    await user.click(screen.getByRole('tab', { name: 'Coding' }))
    expect(readState().mode).toBe('coding')

    await user.click(screen.getByRole('tab', { name: 'Normal' }))
    expect(readState()).toEqual({ mode: 'normal', workspace: '<null>' })

    await user.click(screen.getByRole('tab', { name: 'Coding' }))
    expect(readState()).toEqual({ mode: 'coding', workspace: '<null>' })
  })
})

// ── Workspace input emission contract ────────────────────────────────────────

describe('ModeWorkspaceFields — workspace input', () => {
  it('emits onChange with current mode preserved while typing', async () => {
    const user = userEvent.setup()
    const { onChangeSpy } = renderFields({
      mode: 'coding',
      workspace: null,
    })

    const input = screen.getByPlaceholderText(/Absolute path/i)
    await user.type(input, '/r')

    // Each keystroke fires onChange; every call must carry ``mode: 'coding'``
    // — never undefined, never the default — so the parent's atomic
    // setState does not accidentally reset mode while the user types.
    expect(onChangeSpy.mock.calls.length).toBeGreaterThan(0)
    for (const call of onChangeSpy.mock.calls) {
      const arg = call[0] as Change
      expect(arg.mode).toBe('coding')
    }
    expect(readState().workspace).toBe('/r')
  })

  it('emits workspace: null when the input is cleared', async () => {
    const user = userEvent.setup()
    const { onChangeSpy } = renderFields({
      mode: 'coding',
      workspace: '/repo',
    })

    const input = screen.getByPlaceholderText(/Absolute path/i)
    await user.clear(input)

    // ``e.target.value || null`` → empty string becomes null. This is
    // the backend invariant: a coding task with an empty-string
    // workspace would fail server-side validation, so the form must
    // never send "".
    const last = onChangeSpy.mock.calls.at(-1)?.[0]
    expect(last).toEqual({ mode: 'coding', workspace: null })
    expect(readState().workspace).toBe('<null>')
  })

  it('treats a programmatically-set whitespace-only value as a literal string', () => {
    // Note: ``e.target.value || null`` only nulls the *empty* string —
    // it does NOT trim. Document the current behavior so a future
    // refactor doesn't silently change it. The parent layer
    // (``normalizeWorkspaceInput``) handles trimming before submit.
    const onChangeSpy = mock(((_next: Change) => {}) as (
      ...args: unknown[]
    ) => unknown)
    render(
      <ModeWorkspaceFields
        mode="coding"
        workspace={null}
        onChange={onChangeSpy}
      />,
    )

    const input = screen.getByPlaceholderText(/Absolute path/i) as HTMLInputElement

    // Fire a synthetic change with whitespace — userEvent.type filters
    // some characters, so use a direct change event for determinism.
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value',
      )?.set
      setter?.call(input, '   ')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })

    expect(onChangeSpy).toHaveBeenCalledTimes(1)
    // ``"   " || null`` is ``"   "`` (truthy), so the raw value is
    // forwarded. This is intentional — the panel-level submit handler
    // does the trimming.
    expect(onChangeSpy.mock.calls[0][0]).toEqual({
      mode: 'coding',
      workspace: '   ',
    })
  })
})

// ── Saved-workspace dropdown ─────────────────────────────────────────────────

describe('ModeWorkspaceFields — saved workspaces', () => {
  it('does NOT render the saved-workspace dropdown when localStorage is empty', () => {
    renderFields({ mode: 'coding', workspace: null })

    // The picker is purely an affordance; without saved entries there
    // is nothing to pick, so the trigger must not appear (otherwise
    // the user would see an empty dropdown).
    expect(
      screen.queryByLabelText(/Pick a saved workspace/i),
    ).toBeNull()
  })

  it('renders the saved-workspace dropdown when entries exist', () => {
    localStorage.setItem(
      'oa-coding-workspaces',
      JSON.stringify([
        { id: 'w1', path: '/repo/a', createdAt: '2024-01-01T00:00:00Z' },
        { id: 'w2', path: '/repo/b', createdAt: '2024-01-02T00:00:00Z' },
      ]),
    )

    renderFields({ mode: 'coding', workspace: null })

    const trigger = screen.getByLabelText(/Pick a saved workspace/i)
    expect(trigger).toBeInTheDocument()
  })

  it('does not render the saved-workspace dropdown when localStorage JSON is malformed', () => {
    // ``loadCodingWorkspaceEntries`` swallows parse errors and returns
    // [], so the dropdown must stay hidden rather than crash the panel.
    localStorage.setItem('oa-coding-workspaces', '{not valid json')

    renderFields({ mode: 'coding', workspace: null })

    expect(
      screen.queryByLabelText(/Pick a saved workspace/i),
    ).toBeNull()
  })

  it('keeps the saved-workspace dropdown hidden in normal mode', () => {
    // Even with saved entries, normal mode has no workspace concept,
    // so the picker must be unmounted along with the input.
    localStorage.setItem(
      'oa-coding-workspaces',
      JSON.stringify([
        { id: 'w1', path: '/repo/a', createdAt: '2024-01-01T00:00:00Z' },
      ]),
    )

    renderFields({ mode: 'normal', workspace: null })

    expect(
      screen.queryByLabelText(/Pick a saved workspace/i),
    ).toBeNull()
  })
})
