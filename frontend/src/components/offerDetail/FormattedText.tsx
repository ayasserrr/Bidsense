import { splitClauses } from "../../lib/textFormat"

/** Renders a long verbatim field (payment terms, delivery terms, notes...) as
 * a readable list of clauses instead of one dense paragraph, when it's
 * actually made of several - a single short value renders as plain text. */
export function FormattedText({ text }: { text: string }) {
  const clauses = splitClauses(text)

  if (clauses.length <= 1) {
    return <span>{text}</span>
  }

  return (
    <ul className="m-0 flex list-none flex-col gap-[7px] p-0">
      {clauses.map((clause, index) => (
        <li key={index} className="flex gap-2 text-sm leading-[1.5]">
          <span
            className="mt-[8px] h-[3px] w-[3px] flex-none rounded-full bg-muted-foreground"
            aria-hidden="true"
          />
          <span>{clause}</span>
        </li>
      ))}
    </ul>
  )
}
