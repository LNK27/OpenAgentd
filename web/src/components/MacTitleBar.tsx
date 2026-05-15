/**
 * MacTitleBar — passive platform marker + minimal drag fallback for
 * the macOS traffic-light inset.
 *
 * Background
 * ──────────
 * macOS Tauri uses the **Overlay** title-bar style: the three native
 * traffic-light buttons float over a WebView that extends edge-to-edge.
 * The OS draws the buttons but provides no default drag handle, so the
 * WebView must declare one somewhere along the window's top edge.
 *
 * What this component does
 * ────────────────────────
 * 1. Sets ``html[data-platform=mac-overlay]`` so CSS / other components
 *    can react to the overlay condition.
 * 2. Renders a tiny 70 × 40 px drag pad in the **top-left corner only**
 *    — the empty inset reserved for the OS traffic lights. That zone
 *    is otherwise empty in every route, so the drag handler doesn't
 *    collide with any clickable UI. Routes with their own header
 *    (TeamChatView, AppHeader, telemetry PageHeader) provide drag for
 *    the rest of the top edge via ``useTauriDrag``.
 *
 * Why not a full-width strip?
 * ───────────────────────────
 * A full-width ``fixed top-0`` strip would catch every ``mousedown``
 * event at the top of the viewport. The community-recommended
 * "pointer-events layering" trick (a ``pointer-events-none`` strip
 * with a ``pointer-events-auto`` drag child underneath the buttons)
 * only works when the drag child is *below* the route buttons in
 * stacking order — which is fragile when MacTitleBar mounts at the
 * root and route headers later in the DOM use ``position: fixed``
 * with their own ``z-index`` values. The 70 × 40 corner pad sidesteps
 * the stacking question entirely: it sits in a region that no route
 * draws into, so collisions are impossible.
 */
import { useEffect } from 'react'

import { usePlatform } from '@/hooks/use-platform'
import { useTauriDrag } from '@/hooks/use-tauri-drag'

export function MacTitleBar() {
  const { isMacOverlay } = usePlatform()
  const dragHandlers = useTauriDrag()

  // Sync the platform attribute so other components that need to react
  // to the mac-overlay condition can read it without re-detecting.
  useEffect(() => {
    if (!isMacOverlay) return
    document.documentElement.setAttribute('data-platform', 'mac-overlay')
    return () => {
      document.documentElement.removeAttribute('data-platform')
    }
  }, [isMacOverlay])

  if (!isMacOverlay) return null

  // 70 × 40 px corner pad. Width matches --spacing-mac-traffic-inset
  // and height matches --spacing-app-header. Sits at z-20 — above
  // route headers (no z) but well below modals (z-50). Clicks in
  // this rectangle never hit anything underneath: it's the empty
  // inset every header reserves for the OS-overlaid traffic lights.
  return (
    <div
      {...dragHandlers}
      className="fixed left-0 top-0 z-20 h-10 w-(--spacing-mac-traffic-inset) select-none"
      aria-hidden="true"
    />
  )
}
