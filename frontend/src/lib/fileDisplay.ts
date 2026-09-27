export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const EXTENSION_LABELS: Record<string, string> = {
  pdf: "PDF",
  xlsx: "Excel",
  xls: "Excel",
  doc: "Word",
  docx: "Word",
  txt: "Text",
}

export function fileTypeLabel(filename: string): string {
  const ext = filename.includes(".") ? filename.split(".").pop()!.toLowerCase() : ""
  return EXTENSION_LABELS[ext] ?? "File"
}

// Matches the backend's own FILE_ALLOWED_TYPES (.env) - kept as extensions
// here since that's what a drag-and-drop/file-picker interaction naturally
// works with. Every one of these is read by the Parsing Studio service.
export const ACCEPTED_EXTENSIONS = [".pdf", ".xlsx", ".xls", ".doc", ".docx", ".txt"]
