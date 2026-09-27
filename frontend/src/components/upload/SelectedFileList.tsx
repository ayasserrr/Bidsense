import { FileText, Table2, X } from "lucide-react"
import { formatFileSize, fileTypeLabel } from "../../lib/fileDisplay"
import { StatusChip } from "../ui/StatusChip"

interface SelectedFileListProps {
  files: File[]
  onRemove: (index: number) => void
  onClear: () => void
}

export function SelectedFileList({ files, onRemove, onClear }: SelectedFileListProps) {
  if (files.length === 0) return null

  const totalBytes = files.reduce((sum, file) => sum + file.size, 0)

  return (
    <div className="overflow-hidden rounded-[14px] border border-border bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex items-baseline gap-2">
          <span className="text-[13px] font-semibold">Selected documents</span>
          <span className="tabular text-xs text-muted-foreground">
            {files.length} {files.length === 1 ? "file" : "files"} · {formatFileSize(totalBytes)}
          </span>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="h-7 rounded-[7px] px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          Clear all
        </button>
      </div>
      <ul className="m-0 list-none p-1.5">
        {files.map((file, index) => {
          const label = fileTypeLabel(file.name)
          const Icon = label === "Excel" ? Table2 : FileText
          return (
            <li
              key={`${file.name}-${file.lastModified}-${index}`}
              className="flex items-center gap-3 rounded-[10px] px-2.5 py-[9px] transition-colors hover:bg-muted-60"
            >
              <span className="grid h-[34px] w-[34px] flex-none place-items-center rounded-[9px] bg-muted text-muted-foreground">
                <Icon className="h-4 w-4" aria-hidden />
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-px">
                <span className="truncate text-[13.5px] font-medium">{file.name}</span>
                <span className="tabular text-[11.5px] text-muted-foreground">
                  {label} · {formatFileSize(file.size)}
                </span>
              </span>
              <span className="flex flex-none items-center gap-1.5">
                {/* The app doesn't classify a document's role yet, so the
                    chip carries the one thing it does know: the file type. */}
                <StatusChip tone={index === 0 ? "accent" : "neutral"}>{label}</StatusChip>
                <button
                  type="button"
                  onClick={() => onRemove(index)}
                  aria-label={`Remove ${file.name}`}
                  className="grid h-[30px] w-[30px] place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  <X className="h-[15px] w-[15px]" aria-hidden />
                </button>
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
