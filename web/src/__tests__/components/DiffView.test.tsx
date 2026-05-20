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

    render(<DiffView toolName="edit" args={args} />)

    expect(screen.getByText("src/main.py")).toBeTruthy()
    expect(screen.getByText("def hello():")).toBeTruthy()
    expect(screen.getByText("print('hello')")).toBeTruthy()
    expect(screen.getByText("print('hello world')")).toBeTruthy()
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

    render(<DiffView toolName="patch" args={args} />)

    expect(screen.getByText("src/utils.py")).toBeTruthy()
    expect(screen.getByText("old line")).toBeTruthy()
    expect(screen.getByText("new line")).toBeTruthy()
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
