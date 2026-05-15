/**
 * useTauriDrag — manual `window.startDragging()` handler.
 *
 * Replaces `data-tauri-drag-region`, which pre-empts child click
 * handlers on bare wrappers and breaks interactive descendants. We
 * walk the DOM with `closest()` and skip the drag when the press
 * landed on (or inside) an interactive element — bare wrapper
 * `<div>`s still drag, real buttons keep their clicks.
 *
 * See: https://v2.tauri.app/learn/window-customization/
 *      #manual-implementation-of-data-tauri-drag-region
 */
import { useCallback } from 'react'

import { getPlatform } from '@/hooks/use-platform'

type DragProps = {
  onMouseDown?: (event: React.MouseEvent<HTMLElement>) => void
}

// Lazy-import keeps the Tauri API out of the browser bundle's
// critical path; the first drag attempt resolves it.
async function startDragging(): Promise<void> {
  const { getCurrentWindow } = await import('@tauri-apps/api/window')
  await getCurrentWindow().startDragging()
}

async function toggleMaximize(): Promise<void> {
  const { getCurrentWindow } = await import('@tauri-apps/api/window')
  await getCurrentWindow().toggleMaximize()
}

// Native interactives + opt-out hook for custom components.
const INTERACTIVE_SELECTOR =
  'button, a, input, select, textarea, [role="button"], [data-no-drag]'

function isInteractive(target: EventTarget | null, boundary: Element): boolean {
  if (!(target instanceof Element)) return false
  const hit = target.closest(INTERACTIVE_SELECTOR)
  return hit !== null && boundary.contains(hit)
}

export function useTauriDrag(): DragProps {
  const { isTauri } = getPlatform()

  const onMouseDown = useCallback((event: React.MouseEvent<HTMLElement>) => {
    if (isInteractive(event.target, event.currentTarget)) return
    if (event.buttons !== 1) return
    if (event.detail === 2) {
      void toggleMaximize()
      return
    }
    void startDragging()
  }, [])

  return isTauri ? { onMouseDown } : {}
}
