import { motion } from 'framer-motion'
import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import OpenAgentdAppIcon from '@/assets/brand/openagentd-app-icon.png'

import { DesktopBackendDialog } from '@/components/DesktopBackendDialog'
import { Activity, AlertCircle, Code2, Gauge, Settings, Wifi } from 'lucide-react'
import { useHealthQuery } from '@/queries/useHealthQuery'
import { useTeamStatusQuery } from '@/queries/useTeamStatusQuery'
import { usePlatform } from '@/hooks/use-platform'
import { useTauriDrag } from '@/hooks/use-tauri-drag'
import { useReducedMotion } from '@/hooks/useReducedMotion'

export function HomePage() {
  const navigate = useNavigate()
  const health = useHealthQuery()
  const team = useTeamStatusQuery()
  // The home page is a splash screen with no AppHeader — without an
  // explicit drag region the user can't move the window on macOS Tauri
  // (the OS draws traffic-lights over the WebView but doesn't provide
  // drag elsewhere). MacTitleBar already covers the 70px traffic-light
  // inset; this strip extends the drag area across the rest of the top
  // edge. Other platforms have a native OS title bar so the strip is
  // gated to ``isMacOverlay``.
  const { isMacOverlay } = usePlatform()
  const dragHandlers = useTauriDrag()
  const prefersReducedMotion = useReducedMotion()
  const [backendDialogOpen, setBackendDialogOpen] = useState(false)

  const backendOk = health.isSuccess
  const hasTeam = team.isSuccess && team.data !== null
  const loading = health.isLoading || team.isLoading
  const error = health.isError

  const openCodingMode = () => {
    navigate({ to: '/coding' })
  }

  return (
    <main id="main" className="flex h-screen flex-col items-center justify-center bg-(--bg-page) px-4">
      {isMacOverlay && (
        <div
          {...dragHandlers}
          aria-hidden="true"
          className="fixed left-(--spacing-mac-traffic-inset) right-0 top-0 z-20 h-10 select-none"
        />
      )}
      <motion.div
        initial={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 24 }}
        animate={prefersReducedMotion ? { opacity: 1 } : { opacity: 1, y: 0 }}
        transition={{ duration: prefersReducedMotion ? 0.01 : 0.45, ease: 'easeOut' }}
        className="flex w-full max-w-sm flex-col items-center gap-8"
      >
        {/* Logo */}
        <div className="flex select-none flex-col items-center gap-4">
          <div className="relative">
            <div className="absolute inset-0 rounded-3xl bg-(--bg-key) blur-2xl" />
            <div className="relative flex h-20 w-20 items-center justify-center rounded-3xl bg-(--bg-key) ring-1 ring-(--bg-key)">
              <img src={OpenAgentdAppIcon} width={72} height={72} alt="OpenAgentd logo" className="rounded-2xl" />
            </div>
          </div>
          <div className="text-center">
            <h1 className="font-hand text-5xl leading-none text-(--color-text)">
              OpenAgentd
            </h1>
            <p className="mt-1 text-sm text-(--color-text-muted)">
              Your on-machine AI assistant
            </p>
          </div>
        </div>

        {/* Mode picker */}
        <div className="flex w-full flex-col gap-3">
          <ModeCard
            icon={Gauge}
            title="Cockpit"
            description={
              loading && !error
                ? 'Checking team…'
                : hasTeam
                  ? `${[team.data!.lead, ...team.data!.members].length} agents ready`
                  : 'No team configured'
            }
            disabled={!backendOk || !hasTeam}
            loading={loading && !error}
            onClick={() => navigate({ to: '/cockpit' })}
          />
          <ModeCard
            icon={Code2}
            title="Coding"
            description="Use a project workspace"
            disabled={!backendOk}
            loading={loading && !error}
            onClick={openCodingMode}
          />
           <ModeCard
             icon={Activity}
             title="Telemetry"
             description="Span aggregates & latency"
             disabled={!backendOk}
             loading={loading && !error}
             onClick={() => navigate({ to: '/telemetry' })}
           />
           <ModeCard
             icon={Settings}
             title="Settings"
             description="Agents, skills, MCP servers, sandbox"
             disabled={!backendOk}
             loading={loading && !error}
             onClick={() => navigate({ to: '/settings' })}
           />
        </div>

        {/* Backend status */}
        <div className="flex items-center gap-2 text-xs">
          {loading && !error ? (
            <span className="animate-pulse text-(--color-text-muted)">Connecting…</span>
          ) : error ? (
            <button
              type="button"
              onClick={() => setBackendDialogOpen(true)}
              className="flex items-center gap-2 rounded-md px-2 py-1 text-(--color-error) transition-colors hover:bg-(--color-error)/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
            >
              <AlertCircle size={12} />
              <span>Backend unreachable</span>
              <span className="text-(--color-text-muted)">Choose server</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setBackendDialogOpen(true)}
              className="flex items-center gap-2 rounded-md px-2 py-1 transition-colors hover:bg-(--bg-key) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
            >
              <Wifi size={12} className="text-(--color-success)" />
              <span className="text-(--color-text-muted)">Connected</span>
              <span className="text-(--color-text-muted)">Change server</span>
            </button>
          )}
        </div>
      </motion.div>
      <DesktopBackendDialog open={backendDialogOpen} onOpenChange={setBackendDialogOpen} />
    </main>
  )
}

function ModeCard({
  icon: Icon,
  title,
  description,
  disabled,
  loading,
  onClick,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>
  title: string
  description: string
  disabled: boolean
  loading: boolean
  onClick: () => void
}) {
  return (
    <motion.button
      whileHover={disabled ? {} : { scale: 1.015 }}
      whileTap={disabled ? {} : { scale: 0.985 }}
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      className={`flex w-full items-center gap-4 rounded-2xl border px-5 py-4 text-left transition-all ${
        disabled
          ? 'cursor-not-allowed border-(--bg-key) bg-(--bg-key) opacity-40'
          : 'border-(--bg-key) bg-(--bg-key) hover:border-(--color-border-strong) hover:bg-(--bg-key)'
      }`}
    >
      <div
        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
          disabled
            ? 'bg-(--bg-key)'
            : 'bg-(--bg-key) ring-1 ring-(--color-border-strong)'
        }`}
      >
        <Icon
          size={18}
          className={
            disabled
              ? 'text-(--color-text-muted)'
              : loading
                ? 'animate-pulse text-(--color-accent)'
                : 'text-(--color-accent)'
          }
        />
      </div>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-(--color-text)">{title}</p>
        <p className="mt-0.5 text-xs text-(--color-text-muted)">{description}</p>
      </div>
    </motion.button>
  )
}
