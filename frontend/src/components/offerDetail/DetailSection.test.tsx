import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { DetailSection } from "./DetailSection"

describe("DetailSection", () => {
  it("renders its body and no toggle when not collapsible", () => {
    render(
      <DetailSection title="Project">
        <p>Body content</p>
      </DetailSection>,
    )

    expect(screen.getByText("Body content")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /collapse|expand/i })).not.toBeInTheDocument()
  })

  it("is open by default when collapsible with no defaultOpen given", () => {
    render(
      <DetailSection title="Summary" collapsible>
        <p>Body content</p>
      </DetailSection>,
    )

    expect(screen.getByText("Body content")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Collapse Summary" })).toBeInTheDocument()
  })

  it("starts closed when collapsible with defaultOpen false, and opens on click", async () => {
    render(
      <DetailSection title="Completeness check" collapsible defaultOpen={false}>
        <p>Body content</p>
      </DetailSection>,
    )

    expect(screen.queryByText("Body content")).not.toBeInTheDocument()
    const toggle = screen.getByRole("button", { name: "Expand Completeness check" })
    expect(toggle).toHaveAttribute("aria-expanded", "false")

    await userEvent.click(toggle)

    expect(screen.getByText("Body content")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Collapse Completeness check" })).toHaveAttribute(
      "aria-expanded",
      "true",
    )
  })

  it("closes again on a second click", async () => {
    render(
      <DetailSection title="Items by discipline" collapsible>
        <p>Body content</p>
      </DetailSection>,
    )

    await userEvent.click(screen.getByRole("button", { name: "Collapse Items by discipline" }))

    expect(screen.queryByText("Body content")).not.toBeInTheDocument()
  })

  it("keeps the aside action reachable regardless of open state", () => {
    render(
      <DetailSection title="Items by discipline" collapsible defaultOpen={false} aside={<button>Sort again</button>}>
        <p>Body content</p>
      </DetailSection>,
    )

    expect(screen.getByRole("button", { name: "Sort again" })).toBeInTheDocument()
  })
})
