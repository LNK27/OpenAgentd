/**
 * TodosPopover — task-list popover surfaced from the team-chat topbar.
 *
 * Trigger uses the ``TopbarAction`` primitive for visual consistency
 * with Files/Agents in the same row. The popover content follows the
 * paper-card chrome: ``--color-surface`` body, ``--color-border``
 * outline, ``rounded-md`` corners, mono-uppercase header to match
 * other panel titles in the app (Sidebar "Recent", etc.).
 *
 * Status icons are lucide outlines (``Check``/``X``/``Play``/``Circle``)
 * sized at 12px, colored by role:
 *   - completed  → ``--color-success``
 *   - cancelled  → ``--color-text-subtle``
 *   - in_progress → ``--color-accent``
 *   - pending    → ``--color-text-muted``
 *
 * Priority badges drop the raw red/amber Tailwind colors in favor of
 * design tokens — ``--color-error`` (high), ``--color-warning``
 * (medium), ``--bg-key`` (low) — so the panel respects light/dark
 * theme without per-color overrides.
 *
 * Board view groups tasks by status and shows dependency / agent metadata so
 * team handoffs are visible without opening logs.
 */

import { Check, Circle, Link2, ListTodo, Play, UserRound, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { TopbarAction } from '@/components/ui/topbar-action'
import type { TodoItem } from '@/api/types'

// ── Status icon mapping ──────────────────────────────────────────────────────

const STATUS_ICON: Record<TodoItem['status'], LucideIcon> = {
  completed: Check,
  cancelled: X,
  in_progress: Play,
  pending: Circle,
}

const STATUS_ICON_COLOR: Record<TodoItem['status'], string> = {
  completed: 'text-(--color-success)',
  cancelled: 'text-(--color-text-subtle)',
  in_progress: 'text-(--color-accent)',
  pending: 'text-(--color-text-muted)',
}

const STATUS_COLUMNS: TodoItem['status'][] = [
  'pending',
  'in_progress',
  'completed',
  'cancelled',
]

const STATUS_LABEL: Record<TodoItem['status'], string> = {
  pending: 'Pending',
  in_progress: 'Working',
  completed: 'Done',
  cancelled: 'Cancelled',
}

const STATUS_COLUMN_ACCENT: Record<TodoItem['status'], string> = {
  pending: 'text-(--color-text-muted)',
  in_progress: 'text-(--color-accent)',
  completed: 'text-(--color-success)',
  cancelled: 'text-(--color-text-subtle)',
}

// ── Priority badge mapping ───────────────────────────────────────────────────

const PRIORITY_BADGE_CLASS: Record<TodoItem['priority'], string> = {
  high: 'bg-(--color-error)/10 text-(--color-error)',
  medium: 'bg-(--color-warning)/10 text-(--color-warning)',
  low: 'bg-(--bg-key) text-(--color-text-subtle)',
}

function getAgentLabel(todo: TodoItem): string | null {
  return todo.claimed_by ?? todo.assigned_to ?? null
}

// ── Component ────────────────────────────────────────────────────────────────

interface TodosPopoverProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  todos: TodoItem[]
  /** When null/undefined the trigger is disabled (no active session). */
  sessionId: string | null
}

export function TodosPopover({
  open,
  onOpenChange,
  todos,
  sessionId,
}: TodosPopoverProps) {
  const completedCount = todos.filter((t) => t.status === 'completed').length
  const hasInProgress = todos.some((t) => t.status === 'in_progress')
  const todosByStatus = STATUS_COLUMNS.map((status) => ({
    status,
    todos: todos.filter((todo) => todo.status === status),
  }))

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      {/* base-ui composes via the ``render`` prop (not Radix's
          ``asChild``). Passing the TopbarAction element here lets
          base-ui forward its trigger props onto the primitive button
          we already styled, so the topbar control matches Files /
          Agents one-for-one. */}
      <PopoverTrigger
        render={
          <TopbarAction
            Icon={ListTodo}
            label="Todos"
            indicator={hasInProgress}
            title={sessionId ? 'Task list (Ctrl+T)' : 'No active session'}
            aria-label="Task list"
          />
        }
        disabled={!sessionId}
      />
      <PopoverContent
        side="bottom"
        align="end"
        // ``ring-0`` cancels the shadcn PopoverContent default
        // ``ring-1 ring-foreground/10`` (a near-black hairline that
        // clashes with the paper-card aesthetic). Outline is owned by
        // the ``--color-border`` ring instead, matching the rest of
        // the restyled surfaces.
        className="w-[min(calc(100vw-1rem),64rem)] overflow-hidden rounded-md bg-(--color-surface) p-0 shadow-md ring-1 ring-(--color-border)"
      >
        {/* Header: mono-uppercase title + completion counter. */}
        <div className="flex items-center justify-between border-b border-(--color-border) px-3 py-2">
          <span className="font-mono text-[10px] font-medium uppercase tracking-wider text-(--color-text-muted)">
            Task board
          </span>
          {todos.length > 0 && (
            <span className="font-mono text-[10px] text-(--color-text-subtle)">
              {completedCount}/{todos.length} done
            </span>
          )}
        </div>

        <div className="scrollbar-none flex h-[min(76vh,36rem)] min-h-[28rem] flex-col overflow-x-auto overflow-y-hidden p-3">
          {todos.length === 0 && (
            <p className="mb-3 text-center font-(family-name:--font-hand) text-base text-(--color-text-subtle)">
              No tasks yet — ask the agent to plan
            </p>
          )}
            <div className="grid min-h-0 min-w-[46rem] flex-1 grid-cols-4 divide-x divide-(--color-border)">
              {todosByStatus.map(({ status, todos: columnTodos }) => {
                const Icon = STATUS_ICON[status]
                const iconColor = STATUS_ICON_COLOR[status]
                return (
                  <section
                    key={status}
                    aria-label={`${STATUS_LABEL[status]} tasks`}
                    className="flex min-h-0 flex-col px-3 first:pl-0 last:pr-0"
                  >
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-1.5">
                        <Icon size={12} aria-hidden="true" className={iconColor} />
                        <h3 className="truncate font-mono text-[10px] font-medium uppercase tracking-wider text-(--color-text-muted)">
                          {STATUS_LABEL[status]}
                        </h3>
                      </div>
                      <span className={`font-mono text-[9px] ${STATUS_COLUMN_ACCENT[status]}`}>
                        {columnTodos.length}
                      </span>
                    </div>

                    <div
                      className={
                        columnTodos.length === 0
                          ? 'flex flex-1 items-center justify-center'
                          : 'scrollbar-none min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain pr-2'
                      }
                    >
                      {columnTodos.length === 0 ? (
                        <p className="text-center font-(family-name:--font-hand) text-sm text-(--color-text-subtle)">
                          Nothing here
                        </p>
                      ) : (
                        columnTodos.map((todo) => {
                          const dependencies = todo.dependencies ?? []
                          const agent = getAgentLabel(todo)
                          const isDone =
                            todo.status === 'completed' || todo.status === 'cancelled'
                          return (
                            <article
                              key={todo.task_id}
                              className="border-b border-(--color-border) pb-3 last:border-b-0 last:pb-0"
                            >
                              <div className="mb-1.5 flex items-start justify-between gap-2">
                                <span className="font-mono text-[9px] uppercase tracking-wide text-(--color-text-muted)">
                                  {todo.task_id}
                                </span>
                                <span
                                  className={`shrink-0 rounded px-1 py-0.5 font-mono text-[9px] font-medium uppercase ${
                                    PRIORITY_BADGE_CLASS[todo.priority]
                                  }`}
                                >
                                  {todo.priority}
                                </span>
                              </div>

                              <p
                                className={`text-xs leading-snug ${
                                  isDone
                                    ? 'text-(--color-text-subtle) line-through'
                                    : 'text-(--color-text)'
                                }`}
                              >
                                {todo.content}
                              </p>

                              <div className="mt-2 space-y-1 font-mono text-[9px] uppercase tracking-wide text-(--color-text-muted)">
                                <div className="flex items-center gap-1.5">
                                  <UserRound size={10} aria-hidden="true" />
                                  <span>{agent ?? 'Unassigned'}</span>
                                </div>
                                <div className="flex items-start gap-1.5">
                                  <Link2 size={10} aria-hidden="true" className="mt-0.5" />
                                  <span>
                                    {dependencies.length > 0
                                      ? dependencies.join(', ')
                                      : 'No dependencies'}
                                  </span>
                                </div>
                              </div>
                            </article>
                          )
                        })
                      )}
                    </div>
                  </section>
                )
              })}
            </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}
