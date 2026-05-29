import { useEffect } from 'react'
import { setApiBaseUrl } from '@/api/base-url'
import { getAppBackendStatus } from '@/lib/app-backend'

export function useAppBackendBootstrap(): void {
  useEffect(() => {
    let cancelled = false
    void getAppBackendStatus().then((status) => {
      if (cancelled || !status?.base_url) return
      setApiBaseUrl(status.base_url)
    })
    return () => {
      cancelled = true
    }
  }, [])
}
