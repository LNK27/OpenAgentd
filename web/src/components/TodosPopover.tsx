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
 * Empty state borrows the hand-drawn Caveat idiom used by AgentView
 * and TileArea so the visual voice stays consistent.
 */

import { Check, Circle, ListTodo, Play, X } from 'lucide-react'
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

// Sort: in_progress first, then pending, completed, cancelled.
const STATUS_ORDER: Record<TodoItem['status'], number> = {
  in_progress: 0,
  pending: 1,
  completed: 2,
  cancelled: 3,
}

// ── Priority badge mapping ───────────────────────────────────────────────────

const PRIORITY_BADGE_CLASS: Record<TodoItem['priority'], string> = {
  high: 'bg-(--color-error)/10 text-(--color-error)',
  medium: 'bg-(--color-warning)/10 text-(--color-warning)',
  low: 'bg-(--bg-key) text-(--color-text-subtle)',
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
  const sorted = [...todos].sort(
    (a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status],
  )

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
        className="w-80 overflow-hidden rounded-md bg-(--color-surface) p-0 shadow-md ring-1 ring-(--color-border)"
      >
        {/* Header: mono-uppercase title + completion counter. */}
        <div className="flex items-center justify-between border-b border-(--color-border) px-3 py-2">
          <span className="font-mono text-[10px] font-medium uppercase tracking-wider text-(--color-text-muted)">
            Tasks
          </span>
          {todos.length > 0 && (
            <span className="font-mono text-[10px] text-(--color-text-subtle)">
              {completedCount}/{todos.length} done
            </span>
          )}
        </div>

        {todos.length === 0 ? (
          // Hand-drawn Caveat empty state — matches AgentView /
          // TileArea idiom for the rest of the restyled empty surfaces.
          <div className="px-3 py-8 text-center">
            <p className="font-(family-name:--font-hand) text-base text-(--color-text-subtle)">
              No tasks yet —
              <br />
              ask the agent to plan
            </p>
          </div>
        ) : (
          <ul className="max-h-80 overflow-y-auto py-1">
            {sorted.map((todo) => {
              const Icon = STATUS_ICON[todo.status]
              const iconColor = STATUS_ICON_COLOR[todo.status]
              const isDone =
                todo.status === 'completed' || todo.status === 'cancelled'
              return (
                <li
                  key={todo.task_id}
                  className="flex items-start gap-2 px-3 py-1.5"
                >
                  <Icon
                    size={12}
                    aria-hidden="true"
                    className={`mt-0.5 shrink-0 ${iconColor}`}
                  />
                  <span
                    className={`flex-1 text-xs leading-snug ${
                      isDone
                        ? 'text-(--color-text-subtle) line-through'
                        : 'text-(--color-text)'
                    }`}
                  >
                    {todo.content}
                  </span>
                  <span
                    className={`shrink-0 self-start rounded px-1 py-0.5 font-mono text-[9px] font-medium uppercase ${
                      PRIORITY_BADGE_CLASS[todo.priority]
                    }`}
                  >
                    {todo.priority}
                  </span>
                </li>
              )
            })}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  )
}
