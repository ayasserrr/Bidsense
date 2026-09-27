import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { Badge } from "./Badge"

describe("Badge", () => {
  it("renders its label text", () => {
    render(<Badge tone="critical">Critical</Badge>)
    expect(screen.getByText("Critical")).toBeInTheDocument()
  })

  it.each(["neutral", "brand", "success", "warning", "critical", "info"] as const)(
    "renders without crashing for tone=%s",
    (tone) => {
      render(<Badge tone={tone}>Status</Badge>)
      expect(screen.getByText("Status")).toBeInTheDocument()
    },
  )
})
