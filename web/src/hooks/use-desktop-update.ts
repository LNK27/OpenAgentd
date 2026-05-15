/**
 * Desktop auto-update hook.
 *
 * Wraps ``@tauri-apps/plugin-updater`` so the Settings UI doesn't have
 * to deal with dynamic imports or Tauri-only types. Two distinct
 * concerns:
 *
 * 1. ``useDesktopUpdateCheck()`` — checks the rolling ``latest.json``
 *    manifest published by ``release-desktop.yml`` to see if a new
 *    bundle is available. Returns the same ``{ current_version,
 *    latest_version, update_available, can_install,
 *    install_blocked_reason }`` shape as the PyPI-backed
 *    ``useUpdateStatusQuery`` so the card can render either source
 *    interchangeably.
 *
 * 2. ``useDesktopUpdateInstall()`` — downloads the update, verifies
 *    the minisign signature (handled by the plugin), stages the new
 *    bundle, and triggers a relaunch.
 *
 * Both are guarded by ``isTauri`` so calling them in a browser context
 * fails fast with a clear error instead of importing a plugin that
 * doesn't exist there.
 */
import { useMutation, useQuery } from '@tanstack/react-query'

import { getPlatform } from '@/hooks/use-platform'

import type { UpdateStatus } from '@/api/client'

const NOT_TAURI_ERROR
  = 'Desktop updater is only available inside the OpenAgentd desktop app.'

async function fetchDesktopUpdateStatus(): Promise<UpdateStatus> {
  const { isTauri } = getPlatform()
  if (!isTauri) throw new Error(NOT_TAURI_ERROR)

  // Dynamic import keeps the plugin out of the browser bundle's static
  // graph — in dev the JS server has no Tauri host to call into, and
  // including the plugin statically would crash the page.
  const [{ check }, { getVersion }] = await Promise.all([
    import('@tauri-apps/plugin-updater'),
    import('@tauri-apps/api/app'),
  ])
  const currentVersion = await getVersion()

  // ``check()`` returns ``null`` when no update is available, or an
  // ``Update`` instance with ``version``/``date``/``body`` metadata
  // when one is. The plugin reads ``plugins.updater`` from
  // ``tauri.conf.json`` for the endpoint + pubkey.
  const update = await check()
  if (update === null) {
    return {
      current_version: currentVersion,
      latest_version: currentVersion,
      update_available: false,
      can_install: true,
      install_blocked_reason: null,
    }
  }

  return {
    current_version: currentVersion,
    latest_version: update.version,
    update_available: true,
    can_install: true,
    install_blocked_reason: null,
  }
}

export function useDesktopUpdateCheck() {
  return useQuery({
    queryKey: ['desktop-update-status'] as const,
    queryFn: fetchDesktopUpdateStatus,
    // Manual trigger only — the user explicitly clicks "Check for
    // updates". Auto-polling on mount surprises users and burns the
    // GitHub releases download endpoint.
    enabled: false,
    retry: false,
    gcTime: 60_000,
  })
}

async function downloadAndInstallDesktopUpdate(): Promise<void> {
  const { isTauri } = getPlatform()
  if (!isTauri) throw new Error(NOT_TAURI_ERROR)

  const { check } = await import('@tauri-apps/plugin-updater')
  const { relaunch } = await import('@tauri-apps/plugin-process')

  const update = await check()
  if (update === null) {
    throw new Error('No update available to install.')
  }

  // The plugin handles signature verification (minisign pubkey from
  // ``tauri.conf.json``) and atomic staging. A signature mismatch
  // throws here, which becomes a toast in the calling component.
  await update.downloadAndInstall()

  // On macOS the new bundle is in place and the process can restart
  // immediately. On Windows the installer mode is ``passive`` so
  // ``relaunch`` is the right call there too. On Linux (AppImage)
  // the plugin atomically swaps the binary and ``relaunch`` re-execs.
  await relaunch()
}

export function useDesktopUpdateInstall() {
  return useMutation({
    mutationFn: downloadAndInstallDesktopUpdate,
  })
}
