export interface SavedAppServer {
  base_url: string
  name?: string | null
}

export interface AppBackendStatus {
  base_url: string
  sidecar_running: boolean
  external: boolean
  supports_bundled: boolean
  servers: SavedAppServer[]
}

export async function getAppBackendStatus(): Promise<AppBackendStatus | null> {
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    return await invoke<AppBackendStatus>('app_backend_status')
  } catch {
    return null
  }
}

export async function saveAppBackendServer(baseUrl: string, name: string): Promise<AppBackendStatus> {
  const { invoke } = await import('@tauri-apps/api/core')
  return await invoke<AppBackendStatus>('app_save_backend_server', { baseUrl, name })
}

export async function removeAppBackendServer(baseUrl: string): Promise<AppBackendStatus> {
  const { invoke } = await import('@tauri-apps/api/core')
  return await invoke<AppBackendStatus>('app_remove_backend_server', { baseUrl })
}

export async function useBundledAppBackend(): Promise<void> {
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('app_use_bundled_backend')
}
