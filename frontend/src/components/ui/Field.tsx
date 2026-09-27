import type { ReactNode } from "react"

interface FieldProps {
  label: string
  value: ReactNode
}

/** A single label/value pair - the building block of the "read the cover letter" layout. */
export function Field({ label, value }: FieldProps) {
  const isEmpty = value === null || value === undefined || value === ""
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-ink-subtle">{label}</dt>
      <dd className={isEmpty ? "mt-0.5 text-sm text-ink-faint" : "mt-0.5 text-sm text-ink"}>
        {isEmpty ? "Not stated" : value}
      </dd>
    </div>
  )
}

export function FieldGrid({ children }: { children: ReactNode }) {
  return <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">{children}</dl>
}
