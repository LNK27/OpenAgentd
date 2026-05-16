/**
 * /settings — "About openagentd" landing.
 *
 * Desktop hides the sidebar category list (the rail already shows them);
 * mobile re-uses this page as the settings hub by rendering nav cards.
 *
 * Updates are not surfaced here: desktop uses **OpenAgentd → Check for
 * Updates…** in the menu bar; CLI users run ``openagentd update``.
 */
import { Link } from '@tanstack/react-router'
import {
  ChevronRight,
  Info,
  KeyRound,
  Mic,
  Moon,
  Plug,
  Shield,
  Sparkles,
  Wrench,
  type LucideIcon,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import { useIsMobile } from '@/hooks/use-mobile'
import {
  useAgentFilesQuery,
  useHealthQuery,
  useMcpServersQuery,
  useProvidersQuery,
  useSandboxSettingsQuery,
  useSkillFilesQuery,
  useSpeechConfigQuery,
} from '@/queries'

interface CardProps {
  to:
    | '/settings/agents'
    | '/settings/skills'
    | '/settings/mcp'
    | '/settings/providers'
    | '/settings/sandbox'
    | '/settings/dream'
    | '/settings/voice'
  icon: LucideIcon
  title: string
  description: string
  count: number | null
  countLabel: string
}

function SettingsNavCard({ to, icon: Icon, title, description, count, countLabel }: CardProps) {
  return (
    <Link
      to={to}
      className={cn(
        'group flex items-center gap-4 rounded-xl border border-(--color-border) bg-(--bg-card) p-4 text-(--color-text) transition-colors',
        'hover:border-(--color-border-strong) hover:bg-(--color-surface)',
        'focus-visible:border-(--focus-ring) focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-(--focus-ring)/40',
      )}
    >
      <span
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border) transition-colors group-hover:text-(--color-text)"
        aria-hidden="true"
      >
        <Icon size={18} />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-semibold text-(--color-text)">{title}</span>
          <span className="rounded-md bg-(--bg-key) px-2 py-0.5 font-mono text-[10px] tabular-nums text-(--color-text-muted)">
            {count === null ? '–' : count} {countLabel}
          </span>
        </div>
        <p className="mt-0.5 truncate text-xs text-(--color-text-muted)">{description}</p>
      </div>

      <ChevronRight
        size={16}
        className="shrink-0 text-(--color-text-muted) transition-transform group-hover:translate-x-0.5 group-hover:text-(--color-text)"
        aria-hidden="true"
      />
    </Link>
  )
}

function SectionHeader({ children }: { children: string }) {
  return (
    <h2 className="mb-2 px-1 text-[11px] font-medium tracking-wider text-(--color-text-muted) uppercase">
      {children}
    </h2>
  )
}

export function SettingsHubPage() {
  const isMobile = useIsMobile()
  const agentsQ = useAgentFilesQuery()
  const skillsQ = useSkillFilesQuery()
  const mcpQ = useMcpServersQuery()
  const providersQ = useProvidersQuery()
  const sandboxQ = useSandboxSettingsQuery()
  const speechQ = useSpeechConfigQuery()
  const healthQ = useHealthQuery()

  const agentsCount = agentsQ.data?.agents.length ?? null
  const skillsCount = skillsQ.data?.skills.length ?? null
  const mcpCount = mcpQ.data?.servers.length ?? null
  const connectedProvidersCount = providersQ.data?.providers.filter((provider) => provider.is_configured).length ?? null
  const sandboxCount = sandboxQ.data?.denied_patterns.length ?? null
  const voiceEnabled = speechQ.data?.enabled ?? false
  const version = healthQ.data?.version

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-8 px-4 pt-8 pb-12 sm:px-8">
        <header className="flex items-center gap-3">
          <span
            className="flex h-10 w-10 items-center justify-center rounded-xl bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border)"
            aria-hidden="true"
          >
            <Info size={18} />
          </span>
          <div>
            <h1 className="text-lg font-semibold text-(--color-text)">About openagentd</h1>
            <p className="text-xs text-(--color-text-muted)">
              {version
                ? `On-machine AI assistant · v${version}`
                : 'On-machine AI assistant'}
            </p>
          </div>
        </header>

        {/* Mobile picks up navigation from this list because the sidebar is
            hidden on small screens. */}
        {isMobile && (
          <>
            <section>
              <SectionHeader>Workspace</SectionHeader>
              <div className="space-y-2">
                <SettingsNavCard
                  to="/settings/agents"
                  icon={Wrench}
                  title="Agents"
                  description="Define and edit your agent team — model, tools, system prompt"
                  count={agentsCount}
                  countLabel={agentsCount === 1 ? 'agent' : 'agents'}
                />
                <SettingsNavCard
                  to="/settings/skills"
                  icon={Sparkles}
                  title="Skills"
                  description="Reusable instruction modules agents load on demand"
                  count={skillsCount}
                  countLabel={skillsCount === 1 ? 'skill' : 'skills'}
                />
                <SettingsNavCard
                  to="/settings/mcp"
                  icon={Plug}
                  title="MCP servers"
                  description="External tool providers via Model Context Protocol"
                  count={mcpCount}
                  countLabel={mcpCount === 1 ? 'server' : 'servers'}
                />
                <SettingsNavCard
                  to="/settings/providers"
                  icon={KeyRound}
                  title="Providers"
                  description="Configure API keys and OAuth model providers"
                  count={connectedProvidersCount}
                  countLabel="connected"
                />
              </div>
            </section>

            <section>
              <SectionHeader>System</SectionHeader>
              <div className="space-y-2">
                <SettingsNavCard
                  to="/settings/sandbox"
                  icon={Shield}
                  title="Sandbox"
                  description="Files and folders agents cannot access"
                  count={sandboxCount}
                  countLabel={sandboxCount === 1 ? 'pattern' : 'patterns'}
                />
                <SettingsNavCard
                  to="/settings/dream"
                  icon={Moon}
                  title="Dream"
                  description="Cron agent that synthesises sessions into wiki topics"
                  count={null}
                  countLabel=""
                />
                <SettingsNavCard
                  to="/settings/voice"
                  icon={Mic}
                  title="Voice input"
                  description="Transcribe mic recordings locally and insert into the chat input"
                  count={null}
                  countLabel={voiceEnabled ? 'enabled' : 'disabled'}
                />
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  )
}
