import { isDesktopMode } from '@/api/auth'

export interface SavedDesktopServer {
  base_url: string
  name?: string | null
}

export interface DesktopBackendStatus {
  base_url: string
  sidecar_running: boolean
  external: boolean
  servers: SavedDesktopServer[]
}

export async function getDesktopBackendStatus(): Promise<DesktopBackendStatus | null> {
  if (!isDesktopMode() && typeof window !== 'undefined' && !window.__OAD_API_BASE_URL__) return null
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    return await invoke<DesktopBackendStatus>('desktop_backend_status')
  } catch {
    return null
  }
}

export async function setDesktopBackendBaseUrl(baseUrl: string): Promise<void> {
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('desktop_set_backend_base_url', { baseUrl })
}

export async function saveDesktopBackendServer(baseUrl: string, name: string): Promise<DesktopBackendStatus> {
  const { invoke } = await import('@tauri-apps/api/core')
  return await invoke<DesktopBackendStatus>('desktop_save_backend_server', { baseUrl, name })
}

export async function removeDesktopBackendServer(baseUrl: string): Promise<DesktopBackendStatus> {
  const { invoke } = await import('@tauri-apps/api/core')
  return await invoke<DesktopBackendStatus>('desktop_remove_backend_server', { baseUrl })
}

export async function useBundledDesktopBackend(): Promise<void> {
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('desktop_use_bundled_backend')
}
