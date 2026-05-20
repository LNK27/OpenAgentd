import { describe, it, expect, beforeEach } from "bun:test"
import { useTeamStore } from "@/stores/useTeamStore"

/**
 * Coding-mode workspace invalidation.
 *
 * When ``_workspace`` is set (coding mode), file-mutating ``tool_end``
 * events emit a ``coding_workspace`` invalidation keyed by the absolute
 * workspace path instead of a session-scoped ``workspace_files`` event.
 * The bridge then refreshes the files/diff/status queries on the
 * Coding Workspace Sidebar.
 *
 * ``shell`` / ``patch`` / ``generate_image`` always invalidate the
 * workspace regardless of args. ``write`` / ``edit`` / ``rm`` to a
 * ``wiki/`` path are routed to the wiki cache only.
 */

function primeBlock(
  agent: string,
  toolName: string,
  toolCallId: string,
  args: Record<string, unknown>,
) {
  const state = useTeamStore.getState()
  state._handleSSEEvent("tool_call", { name: toolName, agent, tool_call_id: toolCallId })
  state._handleSSEEvent("tool_start", {
    name: toolName,
    agent,
    tool_call_id: toolCallId,
    arguments: JSON.stringify(args),
  })
}

function resetStore(overrides: Partial<ReturnType<typeof useTeamStore.getState>> = {}) {
  useTeamStore.setState({
    agentStreams: {},
    activeAgent: null,
    leadName: null,
    agentNames: [],
    liveAgentNames: null,
    sidebarOpen: false,
    sessionId: null,
    sessionTitle: null,
    isTeamWorking: false,
    isConnected: false,
    error: null,
    _pendingMessages: [],
    _sessionGeneration: 0,
    cacheInvalidations: [],
    _workspace: null,
    ...overrides,
  })
}

describe("useTeamStore — coding_workspace invalidation", () => {
  beforeEach(() => resetStore())

  it("emits coding_workspace event when `write` targets workspace files in coding mode", () => {
    resetStore({ sessionId: "sess-c1", _workspace: "/Users/me/proj" })
    primeBlock("claude", "write", "tc-1", { path: "src/app.ts", content: "..." })
    useTeamStore.getState()._handleSSEEvent("tool_end", {
      name: "write",
      agent: "claude",
      tool_call_id: "tc-1",
      result: "Written 42 bytes",
    })
    expect(useTeamStore.getState().cacheInvalidations).toEqual([
      { kind: "coding_workspace", workspace: "/Users/me/proj" },
    ])
  })

  it("emits coding_workspace event when `shell` runs in coding mode (no path arg required)", () => {
    resetStore({ sessionId: "sess-c2", _workspace: "/tmp/proj" })
    primeBlock("claude", "shell", "tc-2", { command: "mkdir build && touch build/out" })
    useTeamStore.getState()._handleSSEEvent("tool_end", {
      name: "shell",
      agent: "claude",
      tool_call_id: "tc-2",
      result: "exit 0",
    })
    expect(useTeamStore.getState().cacheInvalidations).toEqual([
      { kind: "coding_workspace", workspace: "/tmp/proj" },
    ])
  })

  it.each(["patch", "bg", "generate_image", "generate_video"] as const)(
    "emits coding_workspace event when `%s` finishes in coding mode",
    (toolName) => {
      resetStore({ sessionId: "sess-c3", _workspace: "/tmp/proj" })
      primeBlock("claude", toolName, `tc-${toolName}`, { foo: "bar" })
      useTeamStore.getState()._handleSSEEvent("tool_end", {
        name: toolName,
        agent: "claude",
        tool_call_id: `tc-${toolName}`,
        result: "ok",
      })
      expect(useTeamStore.getState().cacheInvalidations).toEqual([
        { kind: "coding_workspace", workspace: "/tmp/proj" },
      ])
    },
  )

  it("emits ONLY wiki (not coding_workspace) when `write` targets wiki/ in coding mode", () => {
    resetStore({ sessionId: "sess-c4", _workspace: "/tmp/proj" })
    primeBlock("claude", "write", "tc-w", { path: "wiki/topics/x.md", content: "y" })
    useTeamStore.getState()._handleSSEEvent("tool_end", {
      name: "write",
      agent: "claude",
      tool_call_id: "tc-w",
      result: "Written",
    })
    expect(useTeamStore.getState().cacheInvalidations).toEqual([{ kind: "wiki" }])
  })

  it("falls back to workspace_files (session-scoped) when _workspace is unset", () => {
    resetStore({ sessionId: "sess-n1", _workspace: null })
    primeBlock("claude", "write", "tc-n1", { path: "out.txt", content: "..." })
    useTeamStore.getState()._handleSSEEvent("tool_end", {
      name: "write",
      agent: "claude",
      tool_call_id: "tc-n1",
      result: "Written",
    })
    expect(useTeamStore.getState().cacheInvalidations).toEqual([
      { kind: "workspace_files", sessionId: "sess-n1" },
    ])
  })

  it("does not double-fire when both wiki and workspace would match", () => {
    // Writing to wiki/ must only invalidate wiki, never the coding workspace,
    // because the write never actually touched the workspace tree.
    resetStore({ sessionId: "sess-c5", _workspace: "/tmp/proj" })
    primeBlock("claude", "edit", "tc-w2", {
      path: "wiki/system/USER.md",
      old_string: "a",
      new_string: "b",
    })
    useTeamStore.getState()._handleSSEEvent("tool_end", {
      name: "edit",
      agent: "claude",
      tool_call_id: "tc-w2",
      result: "Edit applied",
    })
    expect(useTeamStore.getState().cacheInvalidations).toEqual([{ kind: "wiki" }])
  })

  it("queues one event per file-mutating tool_end across a burst", () => {
    resetStore({ sessionId: "sess-c6", _workspace: "/tmp/proj" })
    const state = useTeamStore.getState()
    for (let i = 0; i < 3; i++) {
      const tcid = `tc-burst-${i}`
      primeBlock("claude", "write", tcid, { path: `f${i}.txt`, content: "x" })
      state._handleSSEEvent("tool_end", {
        name: "write",
        agent: "claude",
        tool_call_id: tcid,
        result: "Written",
      })
    }
    expect(useTeamStore.getState().cacheInvalidations).toEqual([
      { kind: "coding_workspace", workspace: "/tmp/proj" },
      { kind: "coding_workspace", workspace: "/tmp/proj" },
      { kind: "coding_workspace", workspace: "/tmp/proj" },
    ])
  })
})
