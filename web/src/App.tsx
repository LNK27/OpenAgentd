import { Suspense } from 'react'
import { RouterProvider } from '@tanstack/react-router'
import { router } from './router'

function App() {
  return (
    <Suspense fallback={<AppLoadingScreen />}>
      <RouterProvider router={router} />
    </Suspense>
  )
}

function AppLoadingScreen() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-(--bg-page) text-(--color-text-muted)" role="status" aria-live="polite">
      <div className="flex items-center gap-3 rounded-full border border-(--color-border) bg-(--bg-card) px-4 py-3 text-sm shadow-sm">
        <span className="h-2 w-2 animate-pulse rounded-full bg-(--color-accent) motion-reduce:animate-none" />
        Loading OpenAgentd...
      </div>
    </div>
  )
}

export default App
