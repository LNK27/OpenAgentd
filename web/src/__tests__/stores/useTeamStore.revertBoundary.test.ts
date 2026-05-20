/**
 * Optimization 1 — local revert-boundary application.
 *
 * Verifies that ``undoTeam`` / ``redoTeam`` move the revert boundary
 * locally by sliding finalized blocks between ``blocks`` and
 * ``_revertedSuffix`` — without firing a follow-up history GET via
 * ``loadSession``. This is the dominant /undo + /redo latency win
 * (~150–500ms saved per call).
 *
 * Also covers ``applyRevertBoundary`` invariants directly, and the
 * ``loadSession`` change that parses ALL messages (not just the
 * pre-boundary slice) so an already-reverted session can /redo
 * locally without a refetch.
 */

import { mock, describe, it, expect, beforeEach } from "bun:test"

/* eslint-disable @typescript-eslint/no-explicit-any */
const mockPostTeamChat = mock(() =>
  Promise.resolve({ status: "ok", session_id: "team-sid" })
) as any
const mockPostTeamCommand = mock(() =>
  Promise.resolve({ status: "accepted", session_id: "team-sid", command: "undo" })
) as any
const mockTeamStream = mock((_sid: any, _cbs: any, _signal?: any) => {}) as any
const mockTeamStatus = mock(() =>
  Promise.resolve({
    team: "team",
    lead: { name: "lead", model: "gpt-4", state: "idle" },
    members: [],
  })
) as any
const mockTeamHistory = mock(() =>
  Promise.resolve({
    lead: {
      id: "lead-sess",
      agent_name: "lead",
      title: null,
      created_at: null,
      updated_at: null,
      sub_sessions: [],
      messages: [],
    },
    members: [],
    has_more: false,
    next_cursor: null,
  })
) as any
/* eslint-enable @typescript-eslint/no-explicit-any */

/* eslint-disable @typescript-eslint/no-explicit-any */
;(mock as any).module("@/api/client", () => ({
  postTeamChat: mockPostTeamChat,
  postTeamCommand: mockPostTeamCommand,
  teamStream: mockTeamStream,
  teamStatus: mockTeamStatus,
  teamHistory: mockTeamHistory,
  postChat: mock(() => Promise.resolve({ session_id: "chat-sid" })) as any,
  streamChat: mock(() => {}) as any,
  listTeamAgents: mock(() => Promise.resolve({ agents: [] })) as any,
  listTeamSessions: mock(() => Promise.resolve([])) as any,
  deleteTeamSession: mock(() => Promise.resolve()) as any,
}))
/* eslint-enable @typescript-eslint/no-explicit-any */

import { useTeamStore } from "@/stores/useTeamStore"
import { applyRevertBoundary } from "@/stores/useTeamStore/helpers"
import type { AgentStream } from "@/stores/useTeamStore"
import type { ContentBlock } from "@/api/types"

// ── Test fixtures ─────────────────────────────────────────────────────────────

function block(
  id: string,
  type: ContentBlock["type"],
  content: string,
  isoTime: string,
): ContentBlock {
  return { id, type, content, timestamp: new Date(isoTime) }
}

function makeStream(overrides: Partial<AgentStream> = {}): AgentStream {
  return {
    blocks: [],
    currentBlocks: [],
    currentText: "",
    currentThinking: "",
    status: "idle",
    usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0, cachedTokens: 0 },
    _completionBase: 0,
    _completionEstimated: 0,
    model: null,
    lastError: null,
    revertedCount: 0,
    revertedMessages: [],
    _revertedSuffix: [],
    ...overrides,
  }
}

function makeMessageResponse(overrides: Record<string, unknown> = {}) {
  return {
    id: "msg-1",
    session_id: "sess-1",
    role: "user",
    content: "hello",
    reasoning_content: null,
    tool_calls: null,
    tool_call_id: null,
    name: null,
    is_summary: false,
    is_hidden: false,
    extra: null,
    created_at: "2024-01-01T00:00:00Z",
    file_message: false,
    attachments: null,
    ...overrides,
  }
}

const INITIAL_STATE = {
  agentStreams: {},
  activeAgent: null,
  leadName: null,
  agentNames: [],
  liveAgentNames: null,
  sidebarOpen: false,
  sessionId: null,
  sessionTitle: null,
  isTeamWorking: false,
  isContinuing: false,
  isConnected: false,
  error: null,
  setupRequired: null,
  _pendingMessages: [] as import("@/stores/useTeamStore").PendingMessage[],
  _sessionGeneration: 0,
  hasMore: false,
  nextCursor: null,
  _leadRevertTime: null,
  _workspace: null,
  _loadingOlder: false,
  cacheInvalidations: [],
}

beforeEach(() => {
  useTeamStore.setState(INITIAL_STATE)
  mockPostTeamChat.mockReset()
  mockPostTeamCommand.mockReset()
  mockTeamStream.mockReset()
  mockTeamStatus.mockReset()
  mockTeamHistory.mockReset()

  // After ``mockReset()`` the mocks return ``undefined`` — calling
  // ``.then()`` on undefined in ``loadSession`` would throw. Restore
  // sensible promise-returning defaults so per-test mocks only need to
  // override the call(s) they actually care about.
  mockTeamStatus.mockImplementation(() =>
    Promise.resolve({
      team: "team",
      lead: { name: "lead", model: "gpt-4", state: "idle" },
      members: [],
    }),
  )
  mockTeamHistory.mockImplementation(() =>
    Promise.resolve({
      lead: {
        id: "lead-sess",
        agent_name: "lead",
        title: null,
        created_at: null,
        updated_at: null,
        sub_sessions: [],
        messages: [],
      },
      members: [],
      has_more: false,
      next_cursor: null,
    }),
  )
  mockPostTeamCommand.mockImplementation(() =>
    Promise.resolve({ status: "accepted", session_id: "team-sid", command: "undo" }),
  )
  mockPostTeamChat.mockImplementation(() =>
    Promise.resolve({ status: "ok", session_id: "team-sid" }),
  )
})

// ── applyRevertBoundary helper ────────────────────────────────────────────────

describe("applyRevertBoundary", () => {
  it("is a no-op on an empty stream with null boundary", () => {
    const s = makeStream()
    applyRevertBoundary(s, null)
    expect(s.blocks).toEqual([])
    expect(s._revertedSuffix).toEqual([])
    expect(s.revertedCount).toBe(0)
  })

  it("splits blocks by timestamp — strictly-before-boundary stay visible", () => {
    const t1 = block("b1", "user", "first", "2024-01-01T00:00:00Z")
    const t2 = block("b2", "text", "answer one", "2024-01-01T00:00:01Z")
    const t3 = block("b3", "user", "second", "2024-01-01T00:00:02Z")
    const t4 = block("b4", "text", "answer two", "2024-01-01T00:00:03Z")
    const s = makeStream({ blocks: [t1, t2, t3, t4] })

    applyRevertBoundary(s, new Date("2024-01-01T00:00:02Z").getTime())

    // Boundary points at t3 — t3 itself is the first reverted block.
    expect(s.blocks.map((b) => b.id)).toEqual(["b1", "b2"])
    expect(s._revertedSuffix?.map((b) => b.id)).toEqual(["b3", "b4"])
  })

  it("treats blocks exactly at the boundary timestamp as reverted", () => {
    // ``revertBoundaryTime`` semantics: ``msg.created_at >= boundary``
    // is reverted; only strictly-before is visible.
    const boundaryIso = "2024-01-01T00:00:02Z"
    const same = block("b-at-boundary", "user", "boundary msg", boundaryIso)
    const s = makeStream({ blocks: [same] })
    applyRevertBoundary(s, new Date(boundaryIso).getTime())
    expect(s.blocks).toEqual([])
    expect(s._revertedSuffix).toHaveLength(1)
  })

  it("recombines blocks + suffix before splitting (idempotent across calls)", () => {
    // First undo populates suffix; a second call with a *later*
    // boundary moves some blocks back. Verifies the helper restores
    // from ``_revertedSuffix`` rather than truncating destructively.
    const t1 = block("b1", "user", "u1", "2024-01-01T00:00:00Z")
    const t2 = block("b2", "user", "u2", "2024-01-01T00:00:02Z")
    const t3 = block("b3", "user", "u3", "2024-01-01T00:00:04Z")
    const s = makeStream({ blocks: [t1, t2, t3] })

    // Undo to b2 → b2, b3 in suffix
    applyRevertBoundary(s, new Date("2024-01-01T00:00:02Z").getTime())
    expect(s.blocks.map((b) => b.id)).toEqual(["b1"])
    expect(s._revertedSuffix?.map((b) => b.id)).toEqual(["b2", "b3"])

    // Redo back to live tip (null) → everything restored
    applyRevertBoundary(s, null)
    expect(s.blocks.map((b) => b.id)).toEqual(["b1", "b2", "b3"])
    expect(s._revertedSuffix).toEqual([])
  })

  it("counts user + compaction blocks toward revertedCount", () => {
    const s = makeStream({
      blocks: [
        block("u1", "user", "first", "2024-01-01T00:00:00Z"),
        block("a1", "text", "answer", "2024-01-01T00:00:01Z"),
        block("u2", "user", "second", "2024-01-01T00:00:02Z"),
        block("c1", "compaction", "summary", "2024-01-01T00:00:03Z"),
        block("u3", "user", "third", "2024-01-01T00:00:04Z"),
      ],
    })
    applyRevertBoundary(s, new Date("2024-01-01T00:00:02Z").getTime())
    // u2 + compaction + u3 = 3 reverted "messages"
    expect(s.revertedCount).toBe(3)
  })

  it("populates revertedMessages preview with content and compaction label", () => {
    const s = makeStream({
      blocks: [
        block("u1", "user", "kept", "2024-01-01T00:00:00Z"),
        block("u2", "user", "undone-1", "2024-01-01T00:00:02Z"),
        block("c1", "compaction", "ignored body", "2024-01-01T00:00:03Z"),
        block("u3", "user", "undone-2", "2024-01-01T00:00:04Z"),
      ],
    })
    applyRevertBoundary(s, new Date("2024-01-01T00:00:02Z").getTime())
    expect(s.revertedMessages).toEqual([
      { role: "user", content: "undone-1" },
      { role: "user", content: "Session compacted" },
      { role: "user", content: "undone-2" },
    ])
  })

  it("skips empty-content blocks from the preview", () => {
    const s = makeStream({
      blocks: [
        block("u1", "user", "kept", "2024-01-01T00:00:00Z"),
        block("u2", "user", "   ", "2024-01-01T00:00:02Z"),
        block("u3", "user", "real", "2024-01-01T00:00:04Z"),
      ],
    })
    applyRevertBoundary(s, new Date("2024-01-01T00:00:02Z").getTime())
    expect(s.revertedMessages).toEqual([{ role: "user", content: "real" }])
  })
})

// ── undoTeam ──────────────────────────────────────────────────────────────────

describe("undoTeam — local boundary application", () => {
  it("applies the new boundary locally without calling teamHistory", async () => {
    useTeamStore.setState({
      sessionId: "sess-1",
      leadName: "lead",
      agentStreams: {
        lead: makeStream({
          blocks: [
            block("u1", "user", "first", "2024-01-01T00:00:00Z"),
            block("a1", "text", "answer one", "2024-01-01T00:00:01Z"),
            block("u2", "user", "second", "2024-01-01T00:00:02Z"),
            block("a2", "text", "answer two", "2024-01-01T00:00:03Z"),
          ],
        }),
      },
    })

    mockPostTeamCommand.mockImplementation(() =>
      Promise.resolve({
        status: "accepted",
        session_id: "sess-1",
        command: "undo",
        message: makeMessageResponse({
          id: "u2-id",
          role: "user",
          content: "second",
          created_at: "2024-01-01T00:00:02Z",
        }),
      }),
    )

    await useTeamStore.getState().undoTeam()

    // Critical: no history refetch. This is the perf win.
    expect(mockTeamHistory).not.toHaveBeenCalled()
    expect(mockPostTeamCommand).toHaveBeenCalledWith("undo", "sess-1")

    const stream = useTeamStore.getState().agentStreams.lead
    expect(stream.blocks.map((b) => b.id)).toEqual(["u1", "a1"])
    expect(stream._revertedSuffix?.map((b) => b.id)).toEqual(["u2", "a2"])
    expect(useTeamStore.getState()._leadRevertTime).toBe(
      new Date("2024-01-01T00:00:02Z").getTime(),
    )
  })

  it("queues a workspace invalidation event for the post-undo refresh", async () => {
    useTeamStore.setState({
      sessionId: "sess-1",
      leadName: "lead",
      _workspace: "/tmp/proj",
      agentStreams: {
        lead: makeStream({
          blocks: [
            block("u1", "user", "first", "2024-01-01T00:00:00Z"),
            block("u2", "user", "second", "2024-01-01T00:00:02Z"),
          ],
        }),
      },
    })
    mockPostTeamCommand.mockImplementation(() =>
      Promise.resolve({
        status: "accepted",
        session_id: "sess-1",
        command: "undo",
        message: makeMessageResponse({
          created_at: "2024-01-01T00:00:02Z",
        }),
      }),
    )

    await useTeamStore.getState().undoTeam()

    expect(useTeamStore.getState().cacheInvalidations).toEqual([
      { kind: "coding_workspace", workspace: "/tmp/proj" },
    ])
  })

  it("accumulates suffix correctly across multiple consecutive undos", async () => {
    useTeamStore.setState({
      sessionId: "sess-1",
      leadName: "lead",
      agentStreams: {
        lead: makeStream({
          blocks: [
            block("u1", "user", "first", "2024-01-01T00:00:00Z"),
            block("a1", "text", "a1", "2024-01-01T00:00:01Z"),
            block("u2", "user", "second", "2024-01-01T00:00:02Z"),
            block("a2", "text", "a2", "2024-01-01T00:00:03Z"),
            block("u3", "user", "third", "2024-01-01T00:00:04Z"),
            block("a3", "text", "a3", "2024-01-01T00:00:05Z"),
          ],
        }),
      },
    })

    // First undo → boundary at u3
    mockPostTeamCommand.mockImplementationOnce(() =>
      Promise.resolve({
        status: "accepted",
        session_id: "sess-1",
        command: "undo",
        message: makeMessageResponse({ created_at: "2024-01-01T00:00:04Z" }),
      }),
    )
    await useTeamStore.getState().undoTeam()
    let stream = useTeamStore.getState().agentStreams.lead
    expect(stream.blocks.map((b) => b.id)).toEqual(["u1", "a1", "u2", "a2"])
    expect(stream._revertedSuffix?.map((b) => b.id)).toEqual(["u3", "a3"])

    // Second undo → boundary at u2 — suffix now holds 4 blocks
    mockPostTeamCommand.mockImplementationOnce(() =>
      Promise.resolve({
        status: "accepted",
        session_id: "sess-1",
        command: "undo",
        message: makeMessageResponse({ created_at: "2024-01-01T00:00:02Z" }),
      }),
    )
    await useTeamStore.getState().undoTeam()
    stream = useTeamStore.getState().agentStreams.lead
    expect(stream.blocks.map((b) => b.id)).toEqual(["u1", "a1"])
    expect(stream._revertedSuffix?.map((b) => b.id)).toEqual(["u2", "a2", "u3", "a3"])
  })

  it("applies the boundary to every agent stream (lead + members)", async () => {
    useTeamStore.setState({
      sessionId: "sess-1",
      leadName: "lead",
      agentStreams: {
        lead: makeStream({
          blocks: [
            block("L-u1", "user", "1", "2024-01-01T00:00:00Z"),
            block("L-u2", "user", "2", "2024-01-01T00:00:02Z"),
          ],
        }),
        worker: makeStream({
          blocks: [
            block("W-t1", "text", "early", "2024-01-01T00:00:00Z"),
            block("W-t2", "text", "late", "2024-01-01T00:00:03Z"),
          ],
        }),
      },
    })

    mockPostTeamCommand.mockImplementation(() =>
      Promise.resolve({
        status: "accepted",
        session_id: "sess-1",
        command: "undo",
        message: makeMessageResponse({ created_at: "2024-01-01T00:00:02Z" }),
      }),
    )
    await useTeamStore.getState().undoTeam()

    const lead = useTeamStore.getState().agentStreams.lead
    const worker = useTeamStore.getState().agentStreams.worker
    expect(lead.blocks.map((b) => b.id)).toEqual(["L-u1"])
    expect(worker.blocks.map((b) => b.id)).toEqual(["W-t1"])
    expect(worker._revertedSuffix?.map((b) => b.id)).toEqual(["W-t2"])
  })
})

// ── redoTeam ──────────────────────────────────────────────────────────────────

describe("redoTeam — local boundary application", () => {
  it("restores suffix blocks back into blocks when boundary moves forward", async () => {
    useTeamStore.setState({
      sessionId: "sess-1",
      leadName: "lead",
      _leadRevertTime: new Date("2024-01-01T00:00:02Z").getTime(),
      agentStreams: {
        lead: makeStream({
          blocks: [block("u1", "user", "first", "2024-01-01T00:00:00Z")],
          _revertedSuffix: [
            block("u2", "user", "second", "2024-01-01T00:00:02Z"),
            block("a2", "text", "a2", "2024-01-01T00:00:03Z"),
            block("u3", "user", "third", "2024-01-01T00:00:04Z"),
            block("a3", "text", "a3", "2024-01-01T00:00:05Z"),
          ],
          revertedCount: 2,
        }),
      },
    })

    // Boundary moves forward from u2 to u3 → u2 + a2 come back visible.
    mockPostTeamCommand.mockImplementation(() =>
      Promise.resolve({
        status: "accepted",
        session_id: "sess-1",
        command: "redo",
        message: makeMessageResponse({ created_at: "2024-01-01T00:00:04Z" }),
      }),
    )

    await useTeamStore.getState().redoTeam()

    expect(mockTeamHistory).not.toHaveBeenCalled()
    const stream = useTeamStore.getState().agentStreams.lead
    expect(stream.blocks.map((b) => b.id)).toEqual(["u1", "u2", "a2"])
    expect(stream._revertedSuffix?.map((b) => b.id)).toEqual(["u3", "a3"])
    expect(stream.revertedCount).toBe(1) // only u3 still reverted
  })

  it("flushes the entire suffix back when /redo returns message: null (cleared boundary)", async () => {
    useTeamStore.setState({
      sessionId: "sess-1",
      leadName: "lead",
      _leadRevertTime: new Date("2024-01-01T00:00:02Z").getTime(),
      agentStreams: {
        lead: makeStream({
          blocks: [block("u1", "user", "first", "2024-01-01T00:00:00Z")],
          _revertedSuffix: [
            block("u2", "user", "second", "2024-01-01T00:00:02Z"),
            block("a2", "text", "a2", "2024-01-01T00:00:03Z"),
          ],
          revertedCount: 1,
        }),
      },
    })

    mockPostTeamCommand.mockImplementation(() =>
      Promise.resolve({
        status: "accepted",
        session_id: "sess-1",
        command: "redo",
        message: null, // boundary cleared — back to live tip
      }),
    )

    await useTeamStore.getState().redoTeam()

    const stream = useTeamStore.getState().agentStreams.lead
    expect(stream.blocks.map((b) => b.id)).toEqual(["u1", "u2", "a2"])
    expect(stream._revertedSuffix).toEqual([])
    expect(stream.revertedCount).toBe(0)
    expect(useTeamStore.getState()._leadRevertTime).toBeNull()
  })

  it("queues a workspace invalidation event after redo (same hook as undo)", async () => {
    useTeamStore.setState({
      sessionId: "sess-1",
      leadName: "lead",
      _workspace: "/tmp/proj",
      _leadRevertTime: new Date("2024-01-01T00:00:02Z").getTime(),
      agentStreams: {
        lead: makeStream({
          blocks: [block("u1", "user", "first", "2024-01-01T00:00:00Z")],
          _revertedSuffix: [
            block("u2", "user", "second", "2024-01-01T00:00:02Z"),
          ],
        }),
      },
    })
    mockPostTeamCommand.mockImplementation(() =>
      Promise.resolve({
        status: "accepted",
        session_id: "sess-1",
        command: "redo",
        message: null,
      }),
    )

    await useTeamStore.getState().redoTeam()

    expect(useTeamStore.getState().cacheInvalidations).toEqual([
      { kind: "coding_workspace", workspace: "/tmp/proj" },
    ])
  })

  it("does not touch streams when /redo fails (network error)", async () => {
    useTeamStore.setState({
      sessionId: "sess-1",
      leadName: "lead",
      agentStreams: {
        lead: makeStream({
          blocks: [block("u1", "user", "first", "2024-01-01T00:00:00Z")],
          _revertedSuffix: [
            block("u2", "user", "second", "2024-01-01T00:00:02Z"),
          ],
        }),
      },
    })
    mockPostTeamCommand.mockImplementation(() => Promise.reject(new Error("network down")))

    await useTeamStore.getState().redoTeam()

    const stream = useTeamStore.getState().agentStreams.lead
    expect(stream.blocks.map((b) => b.id)).toEqual(["u1"])
    expect(stream._revertedSuffix?.map((b) => b.id)).toEqual(["u2"])
    expect(useTeamStore.getState().error).toBe("network down")
  })
})

// ── loadSession populates _revertedSuffix on reverted sessions ────────────────

describe("loadSession — parses all messages and populates _revertedSuffix", () => {
  it("splits visible vs reverted on initial load of an already-reverted session", async () => {
    // Session loaded with revert pointing at u2 — post-boundary
    // messages must end up in ``_revertedSuffix`` so /redo works
    // locally without a refetch.
    mockTeamHistory.mockImplementation(() =>
      Promise.resolve({
        lead: {
          id: "lead-sess",
          agent_name: "lead",
          title: null,
          created_at: null,
          updated_at: null,
          sub_sessions: [],
          revert: { message_id: "u2" },
          messages: [
            makeMessageResponse({
              id: "u1",
              role: "user",
              content: "first",
              created_at: "2024-01-01T00:00:00Z",
            }),
            makeMessageResponse({
              id: "a1",
              role: "assistant",
              content: "answer one",
              created_at: "2024-01-01T00:00:01Z",
            }),
            makeMessageResponse({
              id: "u2",
              role: "user",
              content: "second",
              created_at: "2024-01-01T00:00:02Z",
            }),
            makeMessageResponse({
              id: "a2",
              role: "assistant",
              content: "answer two",
              created_at: "2024-01-01T00:00:03Z",
            }),
          ],
        },
        members: [],
        has_more: false,
        next_cursor: null,
      }),
    )

    await useTeamStore.getState().loadSession("sess-1")
    const stream = useTeamStore.getState().agentStreams.lead

    // Pre-boundary u1 + a1 visible, post-boundary u2 + a2 in suffix.
    // (Assistant blocks get auto-generated ids via ``generateBlockId``,
    // so assert against ``content`` for those.)
    expect(stream.blocks.map((b) => b.content)).toEqual(["first", "answer one"])
    expect(stream._revertedSuffix?.map((b) => b.content)).toEqual([
      "second",
      "answer two",
    ])
    expect(stream.revertedCount).toBe(1) // one reverted user message
  })

  it("clears _revertedSuffix when loading a non-reverted session", async () => {
    // Seed a stream with leftover suffix from a prior session — load
    // must wipe it so we don't carry stale state across sessions.
    useTeamStore.setState({
      agentStreams: {
        lead: makeStream({
          _revertedSuffix: [
            block("stale", "user", "from old session", "2023-01-01T00:00:00Z"),
          ],
        }),
      },
    })
    mockTeamHistory.mockImplementation(() =>
      Promise.resolve({
        lead: {
          id: "lead-sess",
          agent_name: "lead",
          title: null,
          created_at: null,
          updated_at: null,
          sub_sessions: [],
          messages: [
            makeMessageResponse({
              id: "u1",
              role: "user",
              content: "hi",
              created_at: "2024-01-01T00:00:00Z",
            }),
          ],
        },
        members: [],
        has_more: false,
        next_cursor: null,
      }),
    )

    await useTeamStore.getState().loadSession("sess-1")
    const stream = useTeamStore.getState().agentStreams.lead
    expect(stream._revertedSuffix).toEqual([])
    expect(stream.blocks.map((b) => b.id)).toEqual(["u1"])
  })
})

// ── sendMessage clears the suffix ─────────────────────────────────────────────

describe("sendMessage — clears _revertedSuffix and boundary", () => {
  it("drops local suffix so a stray /redo cannot resurrect deleted rows", async () => {
    // After /undo the backend has the user-visible state; a new
    // ``sendMessage`` causes ``cleanup_reverted_tail`` to delete those
    // rows. The client suffix is therefore stale and must be cleared.
    useTeamStore.setState({
      sessionId: "sess-1",
      leadName: "lead",
      _leadRevertTime: new Date("2024-01-01T00:00:02Z").getTime(),
      agentStreams: {
        lead: makeStream({
          blocks: [block("u1", "user", "kept", "2024-01-01T00:00:00Z")],
          _revertedSuffix: [
            block("u2", "user", "to be deleted", "2024-01-01T00:00:02Z"),
          ],
          revertedCount: 1,
        }),
      },
    })

    await useTeamStore.getState().sendMessage("new message")

    const stream = useTeamStore.getState().agentStreams.lead
    expect(stream._revertedSuffix).toEqual([])
    expect(stream.revertedCount).toBe(0)
    expect(useTeamStore.getState()._leadRevertTime).toBeNull()
  })
})
