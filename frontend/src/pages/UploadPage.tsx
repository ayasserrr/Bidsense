import { useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { ShieldCheck } from "lucide-react"
import { FileDropzone } from "../components/upload/FileDropzone"
import { SelectedFileList } from "../components/upload/SelectedFileList"
import { PrimaryButton } from "../components/ui/PrimaryButton"
import { AppHeader } from "../components/layout/AppHeader"
import { AppShell } from "../components/layout/AppShell"
import { SegmentedControl } from "../components/ui/SegmentedControl"
import { ErrorBanner } from "../components/ui/ErrorBanner"

const INPUT_CLASS =
  "h-11 w-full rounded-[10px] border-2 border-input bg-background px-3 text-[14px] text-foreground outline-none focus:border-ring"

export function UploadPage() {
  const [files, setFiles] = useState<File[]>([])
  // Both optional (see UploadController.create_offer's own note: someone in a
  // hurry can still upload with nothing typed). Neither decides which offer a
  // new file lands on as a version - offer_versioning.check_same_offer_identity
  // compares the EXTRACTED project name, never this one. These are for
  // grouping and display: the RFQ groups what the compare screen lines up,
  // and the typed name is what the offers list shows when there is one.
  const [projectName, setProjectName] = useState("")
  const [rfqNumber, setRfqNumber] = useState("")
  const navigate = useNavigate()
  const location = useLocation()
  const uploadError = (location.state as { uploadError?: string } | null)?.uploadError ?? null

  function addFiles(newFiles: File[]) {
    setFiles((prev) => {
      // Same-offer dedup mirrors the backend's own per-offer checksum
      // dedup intent closely enough for a client-side sanity check - name
      // + size is a reasonable proxy without reading file contents twice.
      const seen = new Set(prev.map((f) => `${f.name}:${f.size}`))
      const additions = newFiles.filter((f) => !seen.has(`${f.name}:${f.size}`))
      return [...prev, ...additions]
    })
  }

  function removeFile(index: number) {
    setFiles((prev) => prev.filter((_, i) => i !== index))
  }

  function startProcessing() {
    navigate("/processing", {
      state: {
        files,
        projectName: projectName.trim() || undefined,
        rfqNumber: rfqNumber.trim() || undefined,
      },
    })
  }

  return (
    <AppShell>
      <AppHeader />
      <main className="px-6 pb-20 pt-11">
        <div className="mx-auto flex max-w-[720px] flex-col gap-[26px]">
          <div className="flex flex-col gap-2.5">
            <div className="flex items-center gap-2 text-accent">
              <ShieldCheck className="h-4 w-4" aria-hidden />
              <span className="text-[11px] font-bold uppercase tracking-[0.12em]">New check</span>
            </div>
            <h1 className="m-0 text-[30px] font-bold leading-[1.15] tracking-[-0.025em]">Check a new offer</h1>
            <p className="m-0 max-w-[540px] text-[15px] leading-[1.6] text-pretty text-muted-foreground">
              Upload a supplier's offer and we'll read it, cross-check the numbers, and flag anything that needs a
              second look.
            </p>
          </div>

          {uploadError && <ErrorBanner>{uploadError}</ErrorBanner>}

          <SegmentedControl
            ariaLabel="Upload mode"
            value="new"
            options={[
              { value: "new", label: "Upload new offer" },
              { value: "existing", label: "Add a new version of an offer" },
            ]}
            onChange={(value) => {
              if (value === "existing") navigate("/upload/existing")
            }}
          />

          <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,240px),1fr))] gap-3.5">
            <label className="block">
              <span className="mb-1.5 block text-[12px] font-bold text-foreground">Project name</span>
              <input
                type="text"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="e.g. Nile Delta 220 kV Substation"
                className={INPUT_CLASS}
              />
              <span className="mt-1 block text-[12px] text-muted-foreground">
                Optional - helps the offer show up under a name you recognise. It never overrides what the
                document itself says.
              </span>
            </label>
            <label className="block">
              <span className="mb-1.5 block text-[12px] font-bold text-foreground">RFQ number</span>
              <input
                type="text"
                value={rfqNumber}
                onChange={(e) => setRfqNumber(e.target.value)}
                placeholder="e.g. RFQ-2026-0188"
                className={INPUT_CLASS}
              />
              <span className="mt-1 block text-[12px] text-muted-foreground">
                Optional - offers on the same RFQ can be filtered and compared together.
              </span>
            </label>
          </div>

          <FileDropzone onFilesSelected={addFiles} />
          <SelectedFileList files={files} onRemove={removeFile} onClear={() => setFiles([])} />

          <PrimaryButton type="button" disabled={files.length === 0} onClick={startProcessing}>
            Start processing
          </PrimaryButton>
          {files.length === 0 && (
            <p className="-mt-4 text-center text-xs text-muted-foreground">Add at least one file to continue.</p>
          )}
        </div>
      </main>
    </AppShell>
  )
}
