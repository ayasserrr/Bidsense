import { useCallback, useRef, useState, type DragEvent } from "react"
import { UploadCloud } from "lucide-react"
import { ACCEPTED_EXTENSIONS } from "../../lib/fileDisplay"
import { StatusChip } from "../ui/StatusChip"
import { cn } from "../../lib/cn"

interface FileDropzoneProps {
  onFilesSelected: (files: File[]) => void
}

export function FileDropzone({ onFilesSelected }: FileDropzoneProps) {
  const [isDragActive, setIsDragActive] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      setIsDragActive(false)
      const files = Array.from(e.dataTransfer.files)
      if (files.length > 0) onFilesSelected(files)
    },
    [onFilesSelected],
  )

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") inputRef.current?.click()
      }}
      onDragOver={(e) => {
        e.preventDefault()
        setIsDragActive(true)
      }}
      onDragLeave={() => setIsDragActive(false)}
      onDrop={handleDrop}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-3.5 rounded-[14px] px-6 py-[52px] text-center transition-colors",
        isDragActive
          ? "border-2 border-accent bg-[color-mix(in_oklab,var(--accent)_7%,var(--card))]"
          : "border-[1.5px] border-dashed border-input bg-card",
      )}
    >
      <div
        className={cn(
          "grid h-[52px] w-[52px] place-items-center rounded-full transition-colors",
          isDragActive ? "bg-accent text-accent-foreground" : "bg-muted text-muted-foreground",
        )}
      >
        <UploadCloud className="h-6 w-6" aria-hidden />
      </div>
      <div className="flex flex-col gap-[5px]">
        <p className="m-0 text-[15px] font-semibold text-foreground">
          {isDragActive ? "Drop to add these files" : "Drag and drop your offer files, or browse"}
        </p>
        <p className="m-0 max-w-[430px] text-[13px] leading-[1.55] text-muted-foreground">
          Add the main offer PDF and any supporting documents — a technical datasheet, a BOQ — in one go.
        </p>
      </div>
      <div className="mt-0.5 flex gap-1.5">
        <StatusChip tone="muted">PDF</StatusChip>
        <StatusChip tone="muted">Excel</StatusChip>
        <StatusChip tone="muted">Word</StatusChip>
        <StatusChip tone="muted">Text</StatusChip>
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED_EXTENSIONS.join(",")}
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          if (files.length > 0) onFilesSelected(files)
          e.target.value = ""
        }}
      />
    </div>
  )
}
