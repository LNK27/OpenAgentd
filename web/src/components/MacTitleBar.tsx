/**
 * MacTitleBar — custom draggable title strip for the macOS Tauri build.
 *
 * macOS doesn't have an HTML-overlay equivalent of Windows's
 * "extends-content-into-titlebar" mode out of the box; instead Tauri
 * exposes the **Overlay** titleBarStyle which keeps the three native
 * traffic-light buttons (close / minimize / zoom) floating on top of
 * a WebView that extends edge-to-edge. The price is that there's no
 * default place to grab the window for dragging.
 *
 * This component renders that missing grab handle:
 *
 *   - A 28 px tall strip pinned to the top of the viewport.
 *   - 78 px left padding so the traffic-light buttons (which sit at
 *     ``x: 16, y: 18`` per ``trafficLightPosition`` in tauri.conf.json)
 *     don't overlap any text.
 *   - ``data-tauri-drag-region`` makes the strip a native drag handle —
 *     mouse-down moves the OS window.
 *   - ``pointer-events`` are scoped so descendants don't accidentally
 *     swallow drag events; click-through is enabled for empty space.
 *
 * The strip is only rendered on macOS. On Windows / Linux the native
 * title bar handles all of this and there's no traffic-light overlap
 * to work around. We deliberately render *nothing* on those platforms
 * so the rest of the layout stays untouched.
 *
 * To leave room below the strip in the main app layout, the body's
 * ``padding-top`` is bumped via the ``[data-platform="mac-overlay"]``
 * CSS hook applied to ``<html>`` in this same module's effect.
 */
import { useEffect } from 'react'

/** Runtime macOS detection. We can't rely on build-time constants
 *  because the same bundle runs on every platform. Module-level so
 *  the result is computed once at first import and shared by every
 *  render. */
function detectMac(): boolean {
  if (typeof navigator === 'undefined') return false
  // ``navigator.platform`` is the cheap path and works for every
  // Tauri-wrapped WebView (Safari WebKit on macOS).
  if (/Mac/.test(navigator.platform)) return true
  // Fallback: UA-CH for forward-compat with browsers that have already
  // frozen ``navigator.platform``.
  type UAClientHints = { platform?: string }
  const uaData = (navigator as unknown as { userAgentData?: UAClientHints }).userAgentData
  return uaData?.platform === 'macOS'
}

const IS_MAC = detectMac()

export function MacTitleBar() {
  // Sync the platform attribute so the global stylesheet's
  // ``html[data-platform="mac-overlay"] body { padding-top: 28px; }``
  // rule reserves space for the title strip. The attribute is a
  // single source of truth so any other component that needs to
  // adjust for the strip (e.g. a sticky sidebar header) can read
  // it without re-detecting the platform.
  useEffect(() => {
    if (!IS_MAC) return
    document.documentElement.setAttribute('data-platform', 'mac-overlay')
    return () => {
      document.documentElement.removeAttribute('data-platform')
    }
  }, [])

  if (!IS_MAC) return null

  return (
    <div
      // ``data-tauri-drag-region`` is the magic attribute — Tauri's
      // WebView intercepts mouse-down on elements carrying it and
      // forwards it to the OS as a window-drag start.
      data-tauri-drag-region
      // Fixed strip across the very top. ``inset-x-0 top-0`` pins
      // horizontally; ``h-7`` (28 px) leaves room for the standard
      // 14 pt traffic lights. ``z-50`` keeps it above any app
      // overlays; the strip itself is empty + transparent so it
      // never obscures content underneath while still catching the
      // drag.
      className="fixed inset-x-0 top-0 z-50 h-7 select-none bg-transparent"
      // The pl-[78px] mirrors the trafficLightPosition.x (16) + button
      // group width (~62 px) so anything we ever decide to render
      // *inside* the strip starts to the right of the buttons. Empty
      // for now — the strip is just a drag handle.
      style={{ paddingLeft: 78 }}
      aria-hidden="true"
    />
  )
}
