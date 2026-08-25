import { useEffect, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/basis'
import { PdfEerstePagina } from '../ui/PdfEerstePagina'
import { haalVerzamelbakBestandBlob, type VerzamelbakBestand } from './intakeApi'

const HOVER_VERTRAGING_MS = 200
const PREVIEW_BREEDTE = 300

/** Blob-cache per document voor de levensduur van het paneel: één keer ophalen, daarna hover
 * en klik zonder nieuwe request. Nooit vooraf voor de hele lijst (D1: lazy). */
const cache = new Map<string, Promise<VerzamelbakBestand>>()

function laad(documentId: string): Promise<VerzamelbakBestand> {
  let belofte = cache.get(documentId)
  if (!belofte) {
    belofte = haalVerzamelbakBestandBlob(documentId).catch((err: unknown) => {
      cache.delete(documentId)
      throw err
    })
    cache.set(documentId, belofte)
  }
  return belofte
}

/** Preview-knop per verzamelbak-rij (besluit Peter 25-08, punt D1): hover (desktop) toont na
 * een korte vertraging een popup met de eerste pagina van de PDF zodat je ziet voor wie het
 * document is; klik opent de bestaande volledige weergave (zelfde <object>-viewer als het
 * controlescherm). Het bestand wordt pas bij de eerste hover/klik opgehaald — nooit vooraf voor
 * de hele lijst. UBL/XML heeft geen paginabeeld: dan de tenaamstelling + downloadlink. */
export function VerzamelbakPreview({
  documentId,
  bestandsnaam,
  tenaamstelling,
}: {
  documentId: string
  bestandsnaam: string
  tenaamstelling: string | null
}) {
  const [bestand, setBestand] = useState<VerzamelbakBestand | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [hover, setHover] = useState(false)
  const [open, setOpen] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const haal = () => {
    if (bestand || fout) return
    laad(documentId)
      .then(setBestand)
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Bestand niet te laden.'))
  }

  const startHover = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      setHover(true)
      haal()
    }, HOVER_VERTRAGING_MS)
  }
  const stopHover = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    setHover(false)
  }
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  const isPdf = bestandsnaam.toLowerCase().endsWith('.pdf')

  return (
    <span className="verzamelbak-preview" onMouseEnter={startHover} onMouseLeave={stopHover}>
      <button
        type="button"
        className="icon-btn"
        aria-label={`Voorbeeld van ${bestandsnaam}`}
        title="Voorbeeld (hover) · klik voor de volledige weergave"
        onClick={(e) => {
          e.stopPropagation()
          setHover(false)
          haal()
          setOpen(true)
        }}
      >
        👁
      </button>
      {hover && (
        <div className="verzamelbak-preview-popup" role="tooltip" aria-label={`Voorbeeld ${bestandsnaam}`}>
          <div className="verzamelbak-preview-kop">
            {bestandsnaam}
            {tenaamstelling && <span className="hint" style={{ margin: 0 }}> · &ldquo;{tenaamstelling}&rdquo;</span>}
          </div>
          {fout && <div className="hint">{fout}</div>}
          {!bestand && !fout && <div className="hint">Voorbeeld laden…</div>}
          {bestand && isPdf && <PdfEerstePagina blobUrl={bestand.url} breedte={PREVIEW_BREEDTE} />}
          {bestand && !isPdf && (
            <div className="hint">UBL/XML-bestand — geen paginabeeld; tenaamstelling staat in de rij.</div>
          )}
        </div>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="verzamelbak-preview-dialog">
          <DialogTitle>{bestandsnaam}</DialogTitle>
          <DialogDescription>
            Niet toegewezen document{tenaamstelling ? ` — tenaamstelling “${tenaamstelling}”` : ''}. Toewijzen of
            &ldquo;hoort niet bij ons&rdquo; gaat via de rij in de verzamelbak.
          </DialogDescription>
          {fout && <div className="fout">{fout}</div>}
          {!bestand && !fout && <p className="hint">Bestand laden…</p>}
          {bestand && isPdf && (
            <object data={bestand.url} type="application/pdf" aria-label="Documentweergave" style={{ width: '100%', height: '70vh' }}>
              <p className="hint">Geen inline PDF-weergave beschikbaar in deze browser.</p>
            </object>
          )}
          {bestand && !isPdf && <p className="hint">UBL/XML-bestand — geen inline weergave.</p>}
          {bestand && (
            <p style={{ marginTop: 10 }}>
              <a className="btn secondary" href={bestand.url} download={bestandsnaam}>
                Downloaden
              </a>
            </p>
          )}
        </DialogContent>
      </Dialog>
    </span>
  )
}
