import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Button } from "./Button"

describe("Button", () => {
  it("renders children and responds to click", async () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Start Processing</Button>)

    const button = screen.getByRole("button", { name: "Start Processing" })
    await userEvent.click(button)

    expect(onClick).toHaveBeenCalledOnce()
  })

  it("is disabled and non-interactive while loading", async () => {
    const onClick = vi.fn()
    render(
      <Button loading onClick={onClick}>
        Start Processing
      </Button>,
    )

    const button = screen.getByRole("button")
    expect(button).toBeDisabled()
    await userEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it("respects an explicit disabled prop", () => {
    render(<Button disabled>Start Processing</Button>)
    expect(screen.getByRole("button")).toBeDisabled()
  })
})
