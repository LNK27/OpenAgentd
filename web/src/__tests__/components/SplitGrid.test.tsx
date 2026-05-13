import { afterEach, describe, expect, it, mock } from "bun:test"
import { cleanup, render, screen } from "@testing-library/react"
import type { AgentStream } from "@/stores/useTeamStore"

afterEach(cleanup)

mock.module("@/components/AgentPane", () => ({
  AgentPane: ({ name }: { name: string }) => <section>{name}</section>,
}))

function makeStream(overrides: Partial<AgentStream> = {}): AgentStream {
  return {
    blocks: [],
    currentBlocks: [],
    currentText: "",
    currentThinking: "",
    status: "idle",
    usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0, cachedTokens: 0 },
    _completionBase: 0,
    model: null,
    lastError: null,
    ...overrides,
  }
}

function makeStreams(names: string[]): Record<string, AgentStream> {
  return Object.fromEntries(names.map((name) => [name, makeStream()]))
}

async function renderGrid(agentNames: string[], streams = makeStreams(agentNames)) {
  const { SplitGrid } = await import("@/components/TeamChatView/SplitGrid")
  const result = render(
    <SplitGrid
      agentNames={agentNames}
      leadName="lead"
      agentStreams={streams}
    />,
  )
  const root = result.container.firstElementChild as HTMLElement | null
  return { ...result, root }
}

function columnTexts(root: HTMLElement | null): string[][] {
  if (!root) return []
  return Array.from(root.children).map((column) =>
    Array.from(column.children).map((pane) => pane.textContent ?? ""),
  )
}

describe("SplitGrid automatic layout", () => {
  it("renders one agent as a single full-height column", async () => {
    const { root } = await renderGrid(["lead"])

    expect(columnTexts(root)).toHaveLength(1)
    expect(screen.getAllByText("lead")).toHaveLength(1)
  })

  it("adds a second spawned agent as a side-by-side column", async () => {
    const { root } = await renderGrid(["lead", "executor#1"])

    const columns = columnTexts(root)
    expect(columns).toHaveLength(2)
    expect(columns[0][0]).toContain("lead")
    expect(columns[1][0]).toContain("executor#1")
  })

  it("places the third spawned agent under the right column", async () => {
    const { root } = await renderGrid(["lead", "executor#1", "reviewer#1"])

    const columns = columnTexts(root)
    expect(columns).toHaveLength(2)
    expect(columns[0]).toHaveLength(1)
    expect(columns[0][0]).toContain("lead")
    expect(columns[1]).toHaveLength(2)
    expect(columns[1][0]).toContain("executor#1")
    expect(columns[1][1]).toContain("reviewer#1")
  })

  it("grows to three columns at five agents and stacks extra panes to the right", async () => {
    const { root } = await renderGrid([
      "lead",
      "executor#1",
      "executor#2",
      "reviewer#1",
      "reviewer#2",
    ])

    const columns = columnTexts(root)
    expect(columns).toHaveLength(3)
    expect(columns[0]).toHaveLength(1)
    expect(columns[0][0]).toContain("lead")
    expect(columns[1]).toHaveLength(2)
    expect(columns[1][0]).toContain("executor#1")
    expect(columns[1][1]).toContain("executor#2")
    expect(columns[2]).toHaveLength(2)
    expect(columns[2][0]).toContain("reviewer#1")
    expect(columns[2][1]).toContain("reviewer#2")
  })

  it("ignores transient roster entries that do not have streams yet", async () => {
    const { root } = await renderGrid(["lead", "executor#1"], makeStreams(["lead"]))

    const columns = columnTexts(root)
    expect(columns).toHaveLength(1)
    expect(columns[0][0]).toContain("lead")
    expect(screen.queryByText("executor#1")).toBeNull()
  })

  it("hides offline members from split panes", async () => {
    const streams = {
      ...makeStreams(["lead", "executor#1"]),
      "executor#1": makeStream({ status: "offline" }),
    }

    const { root } = await renderGrid(["lead", "executor#1"], streams)

    const columns = columnTexts(root)
    expect(columns).toHaveLength(1)
    expect(columns[0][0]).toContain("lead")
    expect(screen.queryByText("executor#1")).toBeNull()
  })
})
