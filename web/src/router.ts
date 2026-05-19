import { lazy } from 'react'
import { createRootRoute, createRoute, createRouter } from '@tanstack/react-router'
import { Root, NotFound } from './routes/__root'

const HomePage = lazy(() => import('./routes/index').then((m) => ({ default: m.HomePage })))
const TeamLayout = lazy(() => import('./routes/cockpit').then((m) => ({ default: m.TeamLayout })))
const CodingLayout = lazy(() => import('./routes/cockpit').then((m) => ({ default: m.CodingLayout })))
const SettingsLayout = lazy(() => import('./routes/settings').then((m) => ({ default: m.SettingsLayout })))
const SettingsHubPage = lazy(() => import('./routes/settings.index').then((m) => ({ default: m.SettingsHubPage })))
const AgentsListPage = lazy(() => import('./routes/settings.agents').then((m) => ({ default: m.AgentsListPage })))
const AgentEditorPage = lazy(() => import('./routes/settings.agents.$name').then((m) => ({ default: m.AgentEditorPage })))
const NewAgentPage = lazy(() => import('./routes/settings.agents.new').then((m) => ({ default: m.NewAgentPage })))
const SkillsListPage = lazy(() => import('./routes/settings.skills').then((m) => ({ default: m.SkillsListPage })))
const SkillEditorPage = lazy(() => import('./routes/settings.skills.$name').then((m) => ({ default: m.SkillEditorPage })))
const NewSkillPage = lazy(() => import('./routes/settings.skills.new').then((m) => ({ default: m.NewSkillPage })))
const McpListPage = lazy(() => import('./routes/settings.mcp').then((m) => ({ default: m.McpListPage })))
const NewMcpServerPage = lazy(() => import('./routes/settings.mcp.new').then((m) => ({ default: m.NewMcpServerPage })))
const McpServerDetailPage = lazy(() => import('./routes/settings.mcp.$name').then((m) => ({ default: m.McpServerDetailPage })))
const SandboxSettingsPage = lazy(() => import('./routes/settings.sandbox').then((m) => ({ default: m.SandboxSettingsPage })))
const ProvidersSettingsPage = lazy(() => import('./routes/settings.providers').then((m) => ({ default: m.ProvidersSettingsPage })))
const MultimodalSettingsPage = lazy(() => import('./routes/settings.multimodal').then((m) => ({ default: m.MultimodalSettingsPage })))
const DreamSettingsPage = lazy(() => import('./routes/settings.dream').then((m) => ({ default: m.DreamSettingsPage })))
const TitleGenerationSettingsPage = lazy(() => import('./routes/settings.title-generation').then((m) => ({ default: m.TitleGenerationSettingsPage })))
const VoiceSettingsPage = lazy(() => import('./routes/settings.voice').then((m) => ({ default: m.VoiceSettingsPage })))
const TelemetryPage = lazy(() => import('./routes/telemetry').then((m) => ({ default: m.TelemetryPage })))
const SchedulerPage = lazy(() => import('./routes/scheduler').then((m) => ({ default: m.SchedulerPage })))

const rootRoute = createRootRoute({
  component: Root,
  notFoundComponent: NotFound,
})

// / → Home (mode picker)
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: HomePage,
})

// /cockpit layout — persists across /cockpit and /cockpit/$sessionId
const teamLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/cockpit',
  component: TeamLayout,
})
const teamIndexRoute = createRoute({
  getParentRoute: () => teamLayoutRoute,
  path: '/',
  component: () => null,
})
const teamSessionRoute = createRoute({
  getParentRoute: () => teamLayoutRoute,
  path: '$sessionId',
  component: () => null,
})

// /coding layout — coding mode without query-string mode state
const codingLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/coding',
  component: CodingLayout,
})
const codingIndexRoute = createRoute({
  getParentRoute: () => codingLayoutRoute,
  path: '/',
  component: () => null,
})
const codingSessionRoute = createRoute({
  getParentRoute: () => codingLayoutRoute,
  path: '$sessionId',
  component: () => null,
})

// /settings — hub of cards
const settingsLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: SettingsLayout,
})
const settingsIndexRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: '/',
  component: SettingsHubPage,
})

// /settings/agents
const settingsAgentsRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'agents',
  component: AgentsListPage,
})
const settingsAgentsNewRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'agents/new',
  component: NewAgentPage,
})
const settingsAgentDetailRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'agents/$name',
  component: AgentEditorPage,
})

// /settings/skills
const settingsSkillsRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'skills',
  component: SkillsListPage,
})
const settingsSkillsNewRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'skills/new',
  component: NewSkillPage,
})
const settingsSkillDetailRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'skills/$name',
  component: SkillEditorPage,
})

// /settings/mcp
const settingsMcpRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'mcp',
  component: McpListPage,
})
const settingsMcpNewRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'mcp/new',
  component: NewMcpServerPage,
})
const settingsMcpDetailRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'mcp/$name',
  component: McpServerDetailPage,
})

// /settings/sandbox
const settingsSandboxRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'sandbox',
  component: SandboxSettingsPage,
})

// /settings/providers
const settingsProvidersRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'providers',
  component: ProvidersSettingsPage,
})

const settingsMultimodalRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'multimodal',
  component: MultimodalSettingsPage,
})

// /settings/dream
const settingsDreamRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'dream',
  component: DreamSettingsPage,
})

const settingsTitleGenerationRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'title-generation',
  component: TitleGenerationSettingsPage,
})

// /settings/voice
const settingsVoiceRoute = createRoute({
  getParentRoute: () => settingsLayoutRoute,
  path: 'voice',
  component: VoiceSettingsPage,
})

// /telemetry — standalone observability page (span aggregates & latency)
const telemetryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/telemetry',
  component: TelemetryPage,
})

// /scheduler — standalone scheduler page (manage scheduled tasks)
const schedulerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/scheduler',
  component: SchedulerPage,
})

const routeTree = rootRoute.addChildren([
  indexRoute,
  teamLayoutRoute.addChildren([teamIndexRoute, teamSessionRoute]),
  codingLayoutRoute.addChildren([codingIndexRoute, codingSessionRoute]),
  settingsLayoutRoute.addChildren([
    settingsIndexRoute,
    settingsAgentsRoute,
    settingsAgentsNewRoute,
    settingsAgentDetailRoute,
    settingsSkillsRoute,
    settingsSkillsNewRoute,
    settingsSkillDetailRoute,
    settingsMcpRoute,
    settingsMcpNewRoute,
    settingsMcpDetailRoute,
    settingsSandboxRoute,
    settingsProvidersRoute,
    settingsMultimodalRoute,
    settingsDreamRoute,
    settingsTitleGenerationRoute,
    settingsVoiceRoute,
  ]),
  telemetryRoute,
  schedulerRoute,
])

export const router = createRouter({ routeTree, defaultPreload: 'intent' })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
