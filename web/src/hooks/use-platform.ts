/**
 * usePlatform — single source of truth for runtime platform detection.
 *
 * We can't decide platform behaviour at build time because the same
 * bundle ships to:
 *
 *   - Browser  (any OS) — `bun dev`, hosted web build
 *   - Tauri WebView (macOS / Windows / Linux desktop builds)
 *
 * The two facts we need everywhere are:
 *
 *   1. `isTauri`  — is the bundle running inside a Tauri WebView?
 *      Detected via `window.__TAURI_INTERNALS__`, which Tauri 2.x sets
 *      on `window` before any app code runs.
 *
 *   2. `os`       — the host operating system family. Browsers report
 *      this via `navigator.platform` (legacy but universally
 *      supported) with a fallback to `navigator.userAgentData.platform`
 *      (UA-CH) for forward-compat. iOS / Android are exposed only for
 *      completeness — Tauri doesn't currently ship there, so callers
 *      mostly only care about `'macos' | 'windows' | 'linux'`.
 *
 * `isMacOverlay` is a convenience: macOS + Tauri = the OS overlays the
 * traffic-light buttons over our WebView content, so chrome must
 * reserve left padding for them and the window has no native title
 * bar to drag from. This is the only combination that needs the
 * 70 px left inset and the manual `useTauriDrag` mousedown handler.
 *
 * Detection runs once at module load (it doesn't change for the
 * lifetime of the WebView) and is exposed as a hook for ergonomic
 * consumption from components.
 */

export type OS = 'macos' | 'windows' | 'linux' | 'ios' | 'android' | 'unknown'

export interface PlatformInfo {
  /** Running inside a Tauri WebView (vs a plain browser). */
  isTauri: boolean
  /** Host operating system family. */
  os: OS
  /** macOS + Tauri: traffic-lights overlay our content; need drag region + inset. */
  isMacOverlay: boolean
}

interface UAClientHints {
  platform?: string
}

function detectOS(): OS {
  if (typeof navigator === 'undefined') return 'unknown'

  // Cheap path: legacy `navigator.platform`. Frozen in modern Chrome but
  // still populated. Tauri WebViews (WKWebView on macOS, WebView2 on
  // Windows, WebKitGTK on Linux) all report sensible values here.
  const legacy = navigator.platform || ''
  if (/Mac/i.test(legacy)) return 'macos'
  if (/Win/i.test(legacy)) return 'windows'
  if (/Linux/i.test(legacy)) {
    // Android user-agents include "Linux" — disambiguate before we
    // claim Linux desktop.
    if (/Android/i.test(navigator.userAgent)) return 'android'
    return 'linux'
  }
  if (/iPhone|iPad|iPod/i.test(legacy)) return 'ios'

  // Forward-compat fallback for browsers that have frozen
  // `navigator.platform` to an opaque string.
  const uaData = (navigator as unknown as { userAgentData?: UAClientHints }).userAgentData
  const uaPlatform = uaData?.platform?.toLowerCase() ?? ''
  if (uaPlatform === 'macos') return 'macos'
  if (uaPlatform === 'windows') return 'windows'
  if (uaPlatform === 'linux') return 'linux'
  if (uaPlatform === 'android') return 'android'
  if (uaPlatform === 'ios') return 'ios'

  return 'unknown'
}

function detectTauri(): boolean {
  if (typeof window === 'undefined') return false
  return '__TAURI_INTERNALS__' in window
}

// Detection is computed per call rather than memoised at module load
// so tests can patch `navigator.platform` / `window.__TAURI_INTERNALS__`
// between cases without having to bust the module cache. The cost is
// negligible: a couple of regex tests over short strings.
function compute(): PlatformInfo {
  const os: OS = detectOS()
  const isTauri = detectTauri()
  return {
    isTauri,
    os,
    isMacOverlay: os === 'macos' && isTauri,
  }
}

/** Returns the current platform info. Recomputed on each call — keep
 *  the result in a local if you need a stable reference within a
 *  render. */
export function usePlatform(): PlatformInfo {
  return compute()
}

/** Non-hook accessor for code paths that can't call hooks (effects in
 *  module init, plain functions, etc.). Same values as `usePlatform()`. */
export function getPlatform(): PlatformInfo {
  return compute()
}
