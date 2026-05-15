/**
 * useTauriDrag — manual `data-tauri-drag-region` replacement.
 *
 * Why not the attribute?
 * ──────────────────────
 * `data-tauri-drag-region` is the easy path, but it has a known
 * footgun: ``mousedown`` on a drag-region element pre-empts child
 * click handlers, so interactive descendants (buttons / links / custom
 * chips that don't end up as ``<button>`` / ``<input>``) stop being
 * clickable. The Tauri v2 docs document this and offer a manual
 * alternative based on ``window.startDragging()`` —
 * https://v2.tauri.app/learn/window-customization/#manual-implementation-of-data-tauri-drag-region
 *
 * What this hook returns
 * ──────────────────────
 * ``onMouseDown`` props for a draggable container. The handler starts
 * a window drag whenever the user pressed on **non-interactive** chrome
 * — empty space, the title text, layout wrappers — and does nothing
 * when they pressed on or inside an interactive element. Double-click
 * toggles maximize, just like the native title bar.
 *
 * Why not the simpler ``target !== currentTarget`` check?
 * ──────────────────────────────────────────────────────
 * Headers in this app are usually laid out with intermediate wrapper
 * ``<div>``s (chip containers, button groups). Pressing on the empty
 * gap inside a wrapper makes ``event.target`` the **wrapper**, not the
 * ``<header>``. A naïve ``target === currentTarget`` guard would then
 * refuse to drag from those gaps, while still dragging from the few
 * raw pixels of the ``<header>`` itself (typically a thin strip below
 * the wrapped row) — which is exactly the "only the bottom strip
 * drags" symptom we hit before.
 *
 * We instead climb the DOM from the event target up to
 * ``currentTarget`` and ask: "did the user actually press an
 * interactive thing?" If no, start the drag.
 *
 * Browser fallback
 * ────────────────
 * Outside Tauri the hook returns ``{}``; consumers spread it and
 * receive no extra props, leaving the element untouched.
 */
import { useCallback } from 'react'

import { getPlatform } from '@/hooks/use-platform'

type DragProps = {
  onMouseDown?: (event: React.MouseEvent<HTMLElement>) => void
}

/** Dynamically import the Tauri window API. We import lazily so the
 *  module isn't included in the browser bundle's critical path; the
 *  first drag attempt resolves it. */
async function startDragging(): Promise<void> {
  const { getCurrentWindow } = await import('@tauri-apps/api/window')
  await getCurrentWindow().startDragging()
}

async function toggleMaximize(): Promise<void> {
  const { getCurrentWindow } = await import('@tauri-apps/api/window')
  await getCurrentWindow().toggleMaximize()
}

/** Tags any element whose pressdown should *not* trigger a window
 *  drag. Interactive native elements (button/a/input/select/textarea)
 *  and anything that opts out via ``data-no-drag`` (e.g. custom chips
 *  that aren't ``<button>``s). Bare wrappers — divs, spans, headers —
 *  fall through to the drag handler. */
const INTERACTIVE_SELECTOR =
  'button, a, input, select, textarea, [role="button"], [data-no-drag]'

function isInteractive(target: EventTarget | null, boundary: Element): boolean {
  if (!(target instanceof Element)) return false
  // ``closest`` walks the target up through ancestors. We constrain
  // the lookup to inside the drag boundary so an interactive ancestor
  // *outside* the header doesn't spuriously suppress our drag.
  const interactive = target.closest(INTERACTIVE_SELECTOR)
  return interactive !== null && boundary.contains(interactive)
}

export function useTauriDrag(): DragProps {
  const { isTauri } = getPlatform()

  const onMouseDown = useCallback(
    (event: React.MouseEvent<HTMLElement>) => {
      // Skip when the user pressed on (or inside) any interactive
      // descendant. Buttons / links / chips keep their click events;
      // everything else (bare divs, gaps, title spans) drags.
      if (isInteractive(event.target, event.currentTarget)) return
      // Left button only.
      if (event.buttons !== 1) return
      // Double-click maximizes, matching the native title-bar gesture.
      if (event.detail === 2) {
        void toggleMaximize()
        return
      }
      void startDragging()
    },
    [],
  )

  if (!isTauri) return {}
  return { onMouseDown }
}
