import { cn } from "../../lib/cn"

/** "Bidsense" with the second half in the accent - the product wordmark. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("text-[15px] font-bold tracking-[-0.02em]", className)}>
      Bid<span className="text-accent">sense</span>
    </span>
  )
}
