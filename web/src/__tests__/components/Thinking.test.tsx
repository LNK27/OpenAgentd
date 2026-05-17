import { describe, it, expect, afterEach } from "bun:test"
import { render, screen, cleanup } from "@testing-library/react"
import { Thinking } from "@/components/Thinking"

afterEach(cleanup)

describe("Thinking — inline rendering", () => {
  it("renders plain reasoning content inline", () => {
    render(<Thinking content="Done thinking" />)

    expect(screen.getByText("Done thinking")).toBeTruthy()
    expect(screen.queryByRole("button")).toBeNull()
  })

  it("preserves multiline reasoning text", () => {
    const content = "Determining response\n\nThe user is asking about capabilities."
    const { container } = render(<Thinking content={content} />)

    expect(container.textContent).toBe(content)
  })

  it("promotes a leading bold line to an inline header", () => {
    render(<Thinking content={"**Determining response needs**\n\nBody text here"} />)

    const header = screen.getByText("Determining response needs")
    expect(header.tagName).toBe("P")
    expect(screen.getByText("Body text here")).toBeTruthy()
    expect(screen.queryByText(/\*\*/)).toBeNull()
  })

  it("does not require special streaming chrome", () => {
    render(<Thinking content="Determining response" isStreaming={true} />)

    expect(screen.getByText("Determining response")).toBeTruthy()
    expect(screen.queryByText("Reasoning")).toBeNull()
  })

  it("renders no body text for empty content", () => {
    const { container } = render(<Thinking content="" />)

    expect(container.textContent).toBe("")
  })
})
