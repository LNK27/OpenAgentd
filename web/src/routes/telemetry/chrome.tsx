/**
 * Page-level chrome: header, loading/error states.
 * Used by both the summary and trace-detail routes inside `/telemetry`.
 */

import { Activity, AlertTriangle, Loader2 } from 'lucide-react'

export function PageHeader({
  isFetching,
  left,
  subtitle,
  right,
}: {
  isFetching: boolean
  left?: React.ReactNode
  subtitle?: string
  right: React.ReactNode
}) {
  return (
    <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-3 border-b border-(--color-border) bg-(--bg-page) px-4">
      {left}
      <Activity size={15} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
      <h1 className="flex-1 truncate text-sm font-semibold text-(--color-text)">Telemetry</h1>
      <div className="hidden min-w-0 items-center gap-1.5 text-(--color-text-muted) md:flex">
        <span className="truncate text-xs">{subtitle ?? 'Span aggregates & latency'}</span>
        {isFetching && (
          <Loader2
            size={13}
            className="ml-1 animate-spin"
            aria-label="Refreshing"
          />
        )}
      </div>
      <div className="flex items-center gap-2">{right}</div>
    </header>
  )
}

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex h-64 items-center justify-center text-(--color-text-muted)">
      <Loader2 size={18} className="mr-2 animate-spin" />
      <span className="text-sm">{label}</span>
    </div>
  )
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string
  onRetry: () => void
}) {
  return (
    <div className="rounded-xl border border-(--color-error-subtle) bg-(--color-error-subtle)/30 p-5">
      <div className="flex items-start gap-3">
        <AlertTriangle size={18} className="mt-0.5 shrink-0 text-(--color-error)" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-(--color-text)">
            Could not load observability data
          </p>
          <p className="mt-1 text-xs text-(--color-text-muted)">{message}</p>
          <button
            onClick={onRetry}
            className="mt-3 rounded-md border border-(--color-border) bg-(--bg-card) px-3 py-1.5 text-xs font-medium text-(--color-text) transition-colors hover:bg-(--bg-key)"
          >
            Retry
          </button>
        </div>
      </div>
    </div>
  )
}
