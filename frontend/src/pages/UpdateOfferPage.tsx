import { useMemo, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, FileStack } from "lucide-react"
import { listOffersPage } from "../api/offerApi"
import { AppHeader } from "../components/layout/AppHeader"
import { AppShell } from "../components/layout/AppShell"
import { FileDropzone } from "../components/upload/FileDropzone"
import { SelectedFileList } from "../components/upload/SelectedFileList"
import { PrimaryButton } from "../components/ui/PrimaryButton"
import { Pill } from "../components/ui/Pill"
import { Spinner } from "../components/ui/Spinner"
import { EmptyState } from "../components/ui/EmptyState"
import { ErrorBanner } from "../components/ui/ErrorBanner"
import { formatMoney } from "../lib/format"
import { cn } from "../lib/cn"

export function UpdateOfferPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const uploadError = (location.state as { uploadError?: string } | null)?.uploadError ?? null
  const [supplierName, setSupplierName] = useState<string | null>(null)
  const [offerId, setOfferId] = useState<number | null>(null)
  const [files, setFiles] = useState<File[]>([])

  const { data: page, isLoading, isError } = useQuery({
    queryKey: ["offers", "latest", 200],
    // A picker for versioning, not the main list - one big page rather than
    // paging through it, up to a generous ceiling. No status filter: the
    // default is the working list, so an archived offer (retired on purpose)
    // does not quietly show up as something to version.
    queryFn: () => listOffersPage({ limit: 200 }),
  })
  const offers = page?.items

  const suppliers = useMemo(() => {
    if (!offers) return []
    const names = new Set(offers.map((o) => o.supplier_name).filter((n): n is string => !!n))
    return [...names].sort((a, b) => a.localeCompare(b))
  }, [offers])

  const offersForSupplier = useMemo(
    () => (offers ?? []).filter((o) => o.supplier_name === supplierName),
    [offers, supplierName],
  )

  const selectedOffer = offersForSupplier.find((o) => o.id === offerId) ?? null

  function addFiles(newFiles: File[]) {
    setFiles((prev) => {
      const seen = new Set(prev.map((f) => `${f.name}:${f.size}`))
      const additions = newFiles.filter((f) => !seen.has(`${f.name}:${f.size}`))
      return [...prev, ...additions]
    })
  }

  function startProcessing() {
    if (!selectedOffer) return
    navigate("/processing", {
      state: {
        files,
        targetOfferId: selectedOffer.id,
        targetOfferLabel: selectedOffer.offer_ref ?? `offer #${selectedOffer.id}`,
      },
    })
  }

  return (
    <AppShell>
      <AppHeader />
      <main className="px-6 pb-20 pt-11">
        <div className="mx-auto flex max-w-[720px] flex-col gap-[26px]">
          <div className="flex flex-col gap-2.5">
            <button
              type="button"
              onClick={() => navigate("/upload")}
              className="inline-flex h-[26px] items-center gap-1.5 self-start text-[12.5px] font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
              Back
            </button>
            <div className="flex items-center gap-2 text-accent">
              <FileStack className="h-4 w-4" aria-hidden />
              <span className="text-[11px] font-bold uppercase tracking-[0.12em]">New version</span>
            </div>
            <h1 className="m-0 text-[30px] font-bold leading-[1.15] tracking-[-0.025em]">Add a new version</h1>
            <p className="m-0 max-w-[540px] text-[15px] leading-[1.6] text-pretty text-muted-foreground">
              Pick the supplier and offer this new file revises. We'll check it's really the same offer, then save
              it as a new version alongside the existing one — nothing is overwritten or deleted.
            </p>
          </div>

          {uploadError && <ErrorBanner>{uploadError}</ErrorBanner>}

          {isLoading && (
            <div className="flex justify-center py-10">
              <Spinner label="Loading offers..." />
            </div>
          )}

          {isError && <p className="text-sm text-destructive">Could not load existing offers.</p>}

          {offers && offers.length === 0 && (
            <EmptyState
              title="No offers yet"
              description="Upload a new offer first before you can attach a version to it."
              action={
                <Pill onClick={() => navigate("/upload")}>Upload a new offer</Pill>
              }
            />
          )}

          {offers && offers.length > 0 && (
            <>
              <div className="flex flex-col gap-2">
                <span className="text-[12.5px] font-semibold">1. Supplier</span>
                <div className="flex flex-wrap gap-2">
                  {suppliers.map((name) => (
                    <button
                      key={name}
                      type="button"
                      onClick={() => {
                        setSupplierName(name)
                        setOfferId(null)
                      }}
                      className={cn(
                        "h-8 rounded-full border px-3 text-[12.5px] font-medium transition-colors",
                        name === supplierName
                          ? "border-accent bg-accent text-accent-foreground"
                          : "border-border bg-card text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {name}
                    </button>
                  ))}
                </div>
              </div>

              {supplierName && (
                <div className="flex flex-col gap-2">
                  <span className="text-[12.5px] font-semibold">2. Offer</span>
                  <div className="flex flex-col gap-1.5">
                    {offersForSupplier.map((offer) => (
                      <button
                        key={offer.id}
                        type="button"
                        onClick={() => setOfferId(offer.id)}
                        className={cn(
                          "flex items-center justify-between gap-3 rounded-[10px] border px-3.5 py-2.5 text-left transition-colors",
                          offer.id === offerId
                            ? "border-accent bg-[color-mix(in_oklab,var(--accent)_7%,var(--card))]"
                            : "border-border bg-card hover:bg-muted",
                        )}
                      >
                        <div className="flex min-w-0 flex-col">
                          <span className="truncate text-[13.5px] font-semibold">
                            {offer.offer_ref ?? `Offer #${offer.id}`}
                            {offer.version_count > 1 && (
                              <span className="ml-2 text-xs font-normal text-muted-foreground">
                                v{offer.version_count}
                              </span>
                            )}
                          </span>
                          <span className="truncate text-xs text-muted-foreground">
                            {offer.project_label ?? offer.project_name_original}
                          </span>
                        </div>
                        <span className="tabular flex-none text-[12.5px] text-muted-foreground">
                          {formatMoney(offer.grand_total, offer.grand_total_currency)}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {selectedOffer && (
                <div className="flex flex-col gap-2">
                  <span className="text-[12.5px] font-semibold">3. New version file(s)</span>
                  <FileDropzone onFilesSelected={addFiles} />
                  <SelectedFileList files={files} onRemove={(i) => setFiles((p) => p.filter((_, idx) => idx !== i))} onClear={() => setFiles([])} />
                </div>
              )}

              <PrimaryButton type="button" disabled={!selectedOffer || files.length === 0} onClick={startProcessing}>
                Check &amp; save as new version
              </PrimaryButton>
            </>
          )}
        </div>
      </main>
    </AppShell>
  )
}
