import { beforeEach, describe, expect, it, vi } from "vitest"
import type { ComponentProps } from "react"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { EmailDraftModal } from "./EmailDraftModal"

function renderModal(overrides: Partial<ComponentProps<typeof EmailDraftModal>> = {}) {
  const onClose = vi.fn()
  render(
    <EmailDraftModal
      open
      emailTo="ali@supplier.example"
      emailSubject="Clarification needed - warranty terms"
      emailBody={"Hello,\n\nCould you confirm the warranty period?\n\nThanks"}
      onClose={onClose}
      {...overrides}
    />,
  )
  return { onClose }
}

beforeEach(() => {
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
})

describe("EmailDraftModal", () => {
  it("renders nothing while closed", () => {
    renderModal({ open: false })
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("shows the To, Subject and Body", () => {
    renderModal()

    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(screen.getByText("ali@supplier.example")).toBeInTheDocument()
    expect(screen.getByText("Clarification needed - warranty terms")).toBeInTheDocument()
    expect(screen.getByText(/Could you confirm the warranty period/)).toBeInTheDocument()
  })

  it("says there is no recipient on file, without inventing a placeholder address", () => {
    renderModal({ emailTo: null })

    expect(screen.getByText(/No recipient email on file/)).toBeInTheDocument()
    expect(screen.queryByText("ali@supplier.example")).not.toBeInTheDocument()
  })

  it("closes on Escape and via the Close button", async () => {
    const { onClose } = renderModal()

    await userEvent.keyboard("{Escape}")
    expect(onClose).toHaveBeenCalledTimes(1)

    await userEvent.click(screen.getByRole("button", { name: "Close" }))
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it("copies the whole formatted email to the clipboard and confirms briefly", async () => {
    renderModal()

    await userEvent.click(screen.getByRole("button", { name: "Copy text" }))

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "To: ali@supplier.example\nSubject: Clarification needed - warranty terms\n\n" +
        "Hello,\n\nCould you confirm the warranty period?\n\nThanks",
    )
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument()
  })

  it("includes the placeholder text in the copied email when there is no recipient", async () => {
    renderModal({ emailTo: null })

    await userEvent.click(screen.getByRole("button", { name: "Copy text" }))

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining("To: (no recipient on file)"))
  })

  it("does not throw and stays on 'Copy text' when clipboard access is denied", async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } })
    renderModal()

    await userEvent.click(screen.getByRole("button", { name: "Copy text" }))

    expect(navigator.clipboard.writeText).toHaveBeenCalled()
    expect(screen.getByRole("button", { name: "Copy text" })).toBeInTheDocument()
  })
})
