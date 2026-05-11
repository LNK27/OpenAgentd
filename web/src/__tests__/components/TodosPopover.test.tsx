import { afterEach, describe, expect, it } from 'bun:test'
import { cleanup, render, screen } from '@testing-library/react'
import { TodosPopover } from '@/components/TodosPopover'
import type { TodoItem } from '@/api/types'

afterEach(cleanup)

describe('TodosPopover', () => {
  it('renders empty status columns when there are no tasks', () => {
    render(
      <TodosPopover
        open
        onOpenChange={() => {}}
        todos={[]}
        sessionId="session-123"
      />,
    )

    expect(screen.queryByText('No tasks yet — ask the agent to plan')).toBeNull()
    expect(screen.getByRole('region', { name: 'Pending tasks' })).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Working tasks' })).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Done tasks' })).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Cancelled tasks' })).toBeTruthy()
    expect(screen.getAllByText('Nothing here')).toHaveLength(4)
  })

  it('renders a kanban board with dependency and agent metadata', () => {
    const todos: TodoItem[] = [
      {
        task_id: 'task_1',
        content: 'Inspect the todo system',
        status: 'completed',
        priority: 'high',
        dependencies: [],
        assigned_to: 'explorer#1',
        claimed_by: 'explorer#1',
      },
      {
        task_id: 'task_2',
        content: 'Implement the dependency change',
        status: 'pending',
        priority: 'medium',
        dependencies: ['task_1'],
        assigned_to: 'executor#1',
        claimed_by: null,
      },
    ]

    render(
      <TodosPopover
        open
        onOpenChange={() => {}}
        todos={todos}
        sessionId="session-123"
      />,
    )

    expect(screen.getByText('Task board')).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Pending tasks' })).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Working tasks' })).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Done tasks' })).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Cancelled tasks' })).toBeTruthy()
    expect(screen.getByText('Implement the dependency change')).toBeTruthy()
    expect(screen.getByText('executor#1')).toBeTruthy()
    expect(screen.getAllByText('task_1').length).toBeGreaterThanOrEqual(1)
  })
})
