import { describe, it, expect, afterEach } from "bun:test"
import { render, screen, cleanup } from "@testing-library/react"
import { DiffView } from "@/components/ToolCall/DiffView"
import { diffLines } from "@/components/ToolCall/diffUtils"

afterEach(cleanup)

describe("diffLines", () => {
  it("computes line-by-line diff correctly", () => {
    const oldStr = "line1\nline2\nline3"
    const newStr = "line1\nline2 modified\nline3\nline4"
    const result = diffLines(oldStr, newStr)

    expect(result).toEqual([
      { type: "equal", value: "line1" },
      { type: "removed", value: "line2" },
      { type: "added", value: "line2 modified" },
      { type: "equal", value: "line3" },
      { type: "added", value: "line4" },
    ])
  })
})

describe("DiffView", () => {
  it("renders edit tool diff correctly", () => {
    const args = JSON.stringify({
      path: "src/main.py",
      old_string: "def hello():\n    print('hello')",
      new_string: "def hello():\n    print('hello world')",
    })

    render(<DiffView toolName="edit" args={args} result={'@@ openagentd-diff-meta {"path":"src/main.py","old_start":42,"new_start":42}'} />)

    expect(screen.getByText("src/main.py")).toBeTruthy()
    expect(screen.getByText("def hello():")).toBeTruthy()
    expect(screen.getByText("print('hello')")).toBeTruthy()
    expect(screen.getByText("print('hello world')")).toBeTruthy()
    expect(screen.getByText('42')).toBeTruthy()
  })

  it("renders patch tool diff correctly", () => {
    const patchText = [
      "*** Begin Patch",
      "*** Update File: src/utils.py",
      "@@",
      "-old line",
      "+new line",
      "*** End Patch",
    ].join("\n")

    const args = JSON.stringify({ patch_text: patchText })

    render(
      <DiffView
        toolName="patch"
        args={args}
        result={'@@ openagentd-diff-meta {"files":[{"path":"src/utils.py","hunks":[{"old_start":17,"new_start":17}]}]}' }
      />,
    )

    expect(screen.getByText("src/utils.py")).toBeTruthy()
    expect(screen.getByText("old line")).toBeTruthy()
    expect(screen.getByText("new line")).toBeTruthy()
    expect(screen.getAllByText('17')).toHaveLength(2)
  })

  it("renders patch hunks with their own line starts", () => {
    const patchText = [
      "*** Begin Patch",
      "*** Update File: src/utils.py",
      "@@",
      "-first old",
      "+first new",
      "@@",
      "-second old",
      "+second new",
      "*** End Patch",
    ].join("\n")

    const args = JSON.stringify({ patch_text: patchText })

    render(
      <DiffView
        toolName="patch"
        args={args}
        result={'@@ openagentd-diff-meta {"files":[{"path":"src/utils.py","hunks":[{"old_start":10,"new_start":10},{"old_start":20,"new_start":21}]}]}' }
      />,
    )

    expect(screen.getByText("first old")).toBeTruthy()
    expect(screen.getByText("first new")).toBeTruthy()
    expect(screen.getByText("second old")).toBeTruthy()
    expect(screen.getByText("second new")).toBeTruthy()
    expect(screen.getAllByText('10')).toHaveLength(2)
    expect(screen.getByText('20')).toBeTruthy()
    expect(screen.getByText('21')).toBeTruthy()
  })

  it("renders write tool diff correctly", () => {
    const args = JSON.stringify({
      path: "src/new_file.py",
      content: "print('hello world')",
    })

    render(<DiffView toolName="write" args={args} />)

    expect(screen.getByText("src/new_file.py")).toBeTruthy()
    expect(screen.getByText("print('hello world')")).toBeTruthy()
  })

  it("handles invalid JSON gracefully", () => {
    render(<DiffView toolName="edit" args="invalid json" />)
    expect(screen.getByText("invalid json")).toBeTruthy()
  })
})
