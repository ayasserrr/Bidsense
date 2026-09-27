import { describe, expect, it, vi } from "vitest"
import type { ComponentProps } from "react"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ConfirmDialog, useConfirmAction } from "./ConfirmDialog"

function renderDialog(props: Partial<ComponentProps<typeof ConfirmDialog>> = {}) {
  const onConfirm = vi.fn()
  const onCancel = vi.fn()
  render(
    <ConfirmDialog
      open
      title="Delete offer?"
      body="This cannot be undone."
      confirmLabel="Delete"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...props}
    />,
  )
  return { onConfirm, onCancel }
}

function backdrop(): HTMLElement {
  const element = screen.getByRole("alertdialog").parentElement
  if (!element) throw new Error("The dialog rendered without a backdrop")
  return element
}

describe("ConfirmDialog", () => {
  it("renders nothing while closed", () => {
    renderDialog({ open: false })

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
  })

  it("opens with focus on Cancel, so a reflexive Enter backs out", () => {
    renderDialog()

    const dialog = screen.getByRole("alertdialog", { name: "Delete offer?" })
    expect(dialog).toHaveAttribute("aria-modal", "true")
    expect(dialog).toHaveAccessibleDescription("This cannot be undone.")
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus()
  })

  it("confirms only from the confirm button", async () => {
    const { onConfirm, onCancel } = renderDialog()

    await userEvent.click(screen.getByText("This cannot be undone."))
    expect(onCancel).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole("button", { name: "Delete" }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onCancel).not.toHaveBeenCalled()
  })

  it("cancels on Escape and on a backdrop click", async () => {
    const { onConfirm, onCancel } = renderDialog()

    await userEvent.keyboard("{Escape}")
    expect(onCancel).toHaveBeenCalledTimes(1)

    await userEvent.click(backdrop())
    expect(onCancel).toHaveBeenCalledTimes(2)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it("while busy says it is working and can't be dismissed", async () => {
    const { onCancel } = renderDialog({ busy: true })

    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled()
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument()

    await userEvent.keyboard("{Escape}")
    await userEvent.click(backdrop())
    expect(onCancel).not.toHaveBeenCalled()
  })
})

function Harness({ action }: { action: () => Promise<void> }) {
  const confirm = useConfirmAction(action)
  return (
    <>
      <button type="button" onClick={confirm.request}>
        Remove
      </button>
      <ConfirmDialog {...confirm.dialogProps} title="Delete offer?" confirmLabel="Delete it" />
    </>
  )
}

describe("useConfirmAction", () => {
  it("runs nothing until confirmed, and closes on Cancel", async () => {
    const action = vi.fn().mockResolvedValue(undefined)
    render(<Harness action={action} />)

    await userEvent.click(screen.getByRole("button", { name: "Remove" }))
    expect(screen.getByRole("alertdialog")).toBeInTheDocument()

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }))
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
    expect(action).not.toHaveBeenCalled()
  })

  it("holds the dialog busy until the action settles, then closes it", async () => {
    let finish = () => {}
    const action = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)))
    render(<Harness action={action} />)

    await userEvent.click(screen.getByRole("button", { name: "Remove" }))
    await userEvent.click(screen.getByRole("button", { name: "Delete it" }))

    expect(action).toHaveBeenCalledTimes(1)
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled()

    finish()
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument())
  })
})
