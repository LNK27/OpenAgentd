/**
 * TokenMeter — compact display of input · output · cached token totals.
 *
 * Pencil component `h9NN3Z` (TokenMeter):
 *   [ 12.4k · 3.2k · 8.1k ]   ← all mono, separators muted
 *
 * - Mono font, 11px
 * - Numbers in `--color-text`
 * - "·" separators in `--color-text-muted`
 * - Padding 4×10, gap 6, radius-sm
 *
 * Cached is rendered only when > 0 to keep the pill quiet during the
 * first turn of a new session.
 */

import { cn } from '@/lib/utils'
import { formatTokens } from '@/utils/format'

export interface TokenMeterProps {
  input: number
  output: number
  cached?: number
  /** Show a pulsing dot to signal that values are still climbing. */
  pulsing?: boolean
  className?: string
  /** Title attribute override (defaults to a verbose tooltip). */
  title?: string
}

export function TokenMeter({
  input,
  output,
  cached = 0,
  pulsing = false,
  className,
  title,
}: TokenMeterProps) {
  const tooltip =
    title ??
    `Prompt: ${input.toLocaleString()} · Output: ${output.toLocaleString()}${
      cached > 0 ? ` · Cached: ${cached.toLocaleString()}` : ''
    }`

  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 rounded-sm px-2.5 py-1 font-mono text-[11px] leading-none',
        className,
      )}
      title={tooltip}
      aria-label={tooltip}
    >
      <span className="text-(--color-text)">{formatTokens(input)}</span>
      <span aria-hidden="true" className="text-(--color-text-muted)">·</span>
      <span className="text-(--color-text)">{formatTokens(output)}</span>
      {cached > 0 && (
        <>
          <span aria-hidden="true" className="text-(--color-text-muted)">·</span>
          <span className="text-(--color-text)">{formatTokens(cached)}</span>
        </>
      )}
      {pulsing && (
        <span
          aria-hidden="true"
          className="ml-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-(--color-accent)"
        />
      )}
    </div>
  )
}
