import { describe, it, expect, afterEach, mock } from "bun:test"
import { act, render, screen, cleanup, waitFor } from "@testing-library/react"
import { MCPAppResult } from "@/components/MCPAppResult"

afterEach(cleanup)

const bridgeInstances: MockBridge[] = []

class MockBridge {
  static lastTransport: unknown

  onsizechange?: (params: { height?: number }) => Promise<void>
  onopenlink?: (params: { url: string }) => Promise<Record<string, unknown>>
  onloggingmessage?: (params: { level: string; logger?: string; data?: unknown }) => void
  onupdatemodelcontext?: () => Promise<Record<string, unknown>>
  onmessage?: () => Promise<Record<string, unknown>>
  onrequestdisplaymode?: (params: { mode: string }) => Promise<{ mode: string }>
  oninitialized?: () => void
  oncalltool?: (params: { name: string }) => Promise<unknown>
  onlistresources?: () => Promise<unknown>
  onlistresourcetemplates?: () => Promise<unknown>
  onreadresource?: (params: { uri: string }) => Promise<unknown>

  sendToolInput = mock(async () => undefined)
  sendToolResult = mock(async () => undefined)
  setHostContext = mock(() => undefined)
  close = mock(async () => undefined)
  connect = mock(async (transport: unknown) => {
    MockBridge.lastTransport = transport
  })

  constructor() {
    bridgeInstances.push(this)
  }
}

mock.module("@modelcontextprotocol/ext-apps/app-bridge", () => ({
  AppBridge: MockBridge,
  buildAllowAttribute: () => "clipboard-write",
}))

describe("MCPAppResult", () => {
  afterEach(() => {
    bridgeInstances.length = 0
    MockBridge.lastTransport = undefined
  })

  it("renders MCP app HTML in a sandboxed iframe", async () => {
    render(
      <MCPAppResult
        mcpApp={{
          tool: "create_view",
          resourceUri: "ui://excalidraw/mcp-app.html",
          html: "<html><body>mcp app</body></html>",
          mimeType: "text/html;profile=mcp-app",
          resourceMeta: { ui: { prefersBorder: true, permissions: { clipboardWrite: true } } },
          toolMeta: { resourceUri: "ui://excalidraw/mcp-app.html" },
          tool_input: { title: "diagram" },
          result: { content: [{ type: "text", text: "Draw a diagram" }] },
        }}
      />,
    )

    await waitFor(() => expect(document.body.querySelector("iframe")?.getAttribute("srcdoc")).toContain("mcp app"))

    const iframe = document.body.querySelector("iframe")
    expect(iframe).toBeTruthy()
    expect(iframe?.getAttribute("sandbox")).toBe("allow-scripts allow-forms")
    expect(iframe?.getAttribute("allow")).toContain("clipboard-write")
    expect(iframe?.getAttribute("srcdoc")).toContain("script-src 'self' blob: data: 'unsafe-inline'")
    expect(iframe?.getAttribute("title")).toBe("create_view")
    expect(screen.getByText(/Experimental sandbox:/)).toBeTruthy()
  })

  it("starts the bridge transport before loading srcdoc so app initialization is not missed", async () => {
    render(
      <MCPAppResult
        mcpApp={{
          tool: "create_view",
          resourceUri: "ui://excalidraw/mcp-app.html",
          html: "<html><body>mcp app</body></html>",
          mimeType: "text/html;profile=mcp-app",
          tool_input: { title: "diagram" },
          result: { content: [{ type: "text", text: "Draw a diagram" }] },
        }}
      />,
    )

    await waitFor(() => expect(bridgeInstances[0]?.connect).toHaveBeenCalled())

    const iframe = document.body.querySelector("iframe")
    expect(iframe?.getAttribute("srcdoc")).toContain("mcp app")
    expect(MockBridge.lastTransport).toBeTruthy()

    bridgeInstances[0]?.oninitialized?.()

    await waitFor(() => expect(bridgeInstances[0]?.sendToolInput).toHaveBeenCalledWith({ arguments: { title: "diagram" } }))
    expect(bridgeInstances[0]?.sendToolResult).toHaveBeenCalledWith({ content: [{ type: "text", text: "Draw a diagram" }] })
  })

  it("allows MCP apps to request fullscreen edit mode", async () => {
    render(
      <MCPAppResult
        mcpApp={{
          tool: "create_view",
          resourceUri: "ui://excalidraw/mcp-app.html",
          html: "<html><body>mcp app</body></html>",
          mimeType: "text/html;profile=mcp-app",
        }}
      />,
    )

    await waitFor(() => expect(bridgeInstances[0]?.connect).toHaveBeenCalled())
    let result: { mode: string } | undefined
    await act(async () => {
      result = await bridgeInstances[0]?.onrequestdisplaymode?.({ mode: "fullscreen" })
    })

    expect(result).toEqual({ mode: "fullscreen" })
    expect(bridgeInstances[0]?.setHostContext).toHaveBeenCalledWith({
      displayMode: "fullscreen",
      containerDimensions: { height: window.innerHeight, width: window.innerWidth },
    })
  })
})
