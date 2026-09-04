import { useEffect, useRef, useState } from 'react'
import { AnkerPopup, Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/basis'
import { PdfEerstePagina } from '../ui/PdfEerstePagina'
import { haalUblSamenvatting, haalVerzamelbakBestandBlob, type UblSamenvattingDto, type VerzamelbakBestand } from './intakeApi'
import { metViewerOpties } from '../document/pdfWeergaveUrl'

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
 * de hele lijst. UBL/XML heeft geen paginabeeld: dan de tenaamstelling + downloadlink.
 *
 * De hover-popup rendert via `AnkerPopup` op documentniveau (portal + fixed, rechts van het
 * oog-icoon, flipt naar links/schuift omhoog bij de viewport-rand) — feedbackronde 26-08 punt 2:
 * als `position: absolute`-kind van de rij werd hij door `.tabel-scroll`/`table{overflow:hidden}`
 * na ~30 px afgekapt. */
export function VerzamelbakPreview({
  documentId,
  bestandsnaam,
  tenaamstelling,
  beeldBestandsnaam = null,
}: {
  documentId: string
  bestandsnaam: string
  tenaamstelling: string | null
  /** Bundeling/samenvoegen (02-09): naam van het PDF-beeld naast een UBL-document. */
  beeldBestandsnaam?: string | null
}) {
  const [bestand, setBestand] = useState<VerzamelbakBestand | null>(null)
  const [samenvatting, setSamenvatting] = useState<UblSamenvattingDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [hover, setHover] = useState(false)
  const [open, setOpen] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const knopRef = useRef<HTMLButtonElement>(null)

  const isXmlZonderBeeld = /\.xml$/i.test(bestandsnaam) && !beeldBestandsnaam
  const haal = () => {
    if (bestand || fout || samenvatting) return
    if (isXmlZonderBeeld) {
      // Losse UBL zonder beeld (02-09): een leesbare samenvatting i.p.v. "geen paginabeeld".
      haalUblSamenvatting(documentId)
        .then(setSamenvatting)
        .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Samenvatting niet te laden.'))
      return
    }
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

  // Het geserveerde bestand is leidend (bundeling: een UBL-document krijgt de PDF als beeld);
  // vóór de eerste fetch valt de keuze op de bestandsnaam/het beeld.
  const naamZegtPdf = Boolean(beeldBestandsnaam) || bestandsnaam.toLowerCase().endsWith('.pdf')
  const naamZegtAfbeelding = /\.(jpe?g|png|heic|heif)$/i.test(bestandsnaam)
  // Het geserveerde content-type is leidend als het duidelijk is (pdf/xml/image); anders de naam —
  // een testomgeving/proxy levert soms 'text/plain' of niets.
  const ct = (bestand?.contentType ?? '').toLowerCase()
  const isPdf = ct.includes('pdf') || (!/xml|image\//.test(ct) && naamZegtPdf)
  // Een onbruikbare (corrupte) afbeelding ligt als origineel in de verzamelbak (punt 2) — tonen
  // wat de browser ervan kan maken; een omgezette foto is gewoon een PDF.
  const isAfbeelding = ct.startsWith('image/') || (!/pdf|xml/.test(ct) && naamZegtAfbeelding)
  const toonNaam = beeldBestandsnaam ? `${bestandsnaam} + ${beeldBestandsnaam}` : bestandsnaam

  return (
    <span className="verzamelbak-preview" onMouseEnter={startHover} onMouseLeave={stopHover}>
      <button
        ref={knopRef}
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
      <AnkerPopup
        open={hover}
        anker={knopRef}
        kant="rechts"
        afstand={8}
        onAnkerUitBeeld={stopHover}
        className="verzamelbak-preview-popup"
        role="tooltip"
        aria-label={`Voorbeeld ${bestandsnaam}`}
      >
        <div className="verzamelbak-preview-kop">
          {toonNaam}
          {tenaamstelling && <span className="hint" style={{ margin: 0 }}> · &ldquo;{tenaamstelling}&rdquo;</span>}
        </div>
        {fout && <div className="hint">{fout}</div>}
        {!bestand && !samenvatting && !fout && <div className="hint">Voorbeeld laden…</div>}
        {bestand && isPdf && <PdfEerstePagina blobUrl={bestand.url} breedte={PREVIEW_BREEDTE} />}
        {bestand && isAfbeelding && (
          <img src={bestand.url} alt={`Voorbeeld ${bestandsnaam}`} style={{ maxWidth: PREVIEW_BREEDTE, display: 'block' }} />
        )}
        {samenvatting && <UblSamenvattingKaart s={samenvatting} compact />}
        {bestand && !isPdf && !isAfbeelding && (
          <div className="hint">Geen inline weergave voor dit bestandstype.</div>
        )}
      </AnkerPopup>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="verzamelbak-preview-dialog">
          <DialogTitle>{toonNaam}</DialogTitle>
          <DialogDescription>
            Niet toegewezen document{tenaamstelling ? ` — tenaamstelling “${tenaamstelling}”` : ''}. Toewijzen of
            &ldquo;hoort niet bij ons&rdquo; gaat via de rij in de verzamelbak.
          </DialogDescription>
          {fout && <div className="fout">{fout}</div>}
          {!bestand && !samenvatting && !fout && <p className="hint">Bestand laden…</p>}
          {bestand && isPdf && (
            <object data={metViewerOpties(bestand.url)} type="application/pdf" aria-label="Documentweergave" style={{ width: '100%', height: '70vh' }}>
              <p className="hint">Geen inline PDF-weergave beschikbaar in deze browser.</p>
            </object>
          )}
          {bestand && isAfbeelding && (
            <img src={bestand.url} alt={bestandsnaam} style={{ maxWidth: '100%', maxHeight: '70vh', display: 'block' }} />
          )}
          {samenvatting && <UblSamenvattingKaart s={samenvatting} />}
          {bestand && !isPdf && !isAfbeelding && <p className="hint">Geen inline weergave voor dit bestandstype.</p>}
          {bestand && (
            <p style={{ marginTop: 10 }}>
              <a className="btn secondary" href={bestand.url} download={beeldBestandsnaam ?? bestandsnaam}>
                Downloaden{beeldBestandsnaam ? ' (beeld)' : ''}
              </a>
            </p>
          )}
        </DialogContent>
      </Dialog>
    </span>
  )
}


function formatBedrag(bedrag: string | null, valuta: string | null): string {
  if (bedrag === null) return '—'
  const getal = Number(bedrag)
  if (!Number.isFinite(getal)) return bedrag
  return getal.toLocaleString('nl-NL', { style: 'currency', currency: valuta || 'EUR' })
}

/** Gerenderde UBL-samenvatting (02-09): leverancier, afnemer, nummer, datum, totaal, regels. */
export function UblSamenvattingKaart({ s, compact = false }: { s: UblSamenvattingDto; compact?: boolean }) {
  return (
    <div className="ubl-samenvatting" data-testid="ubl-samenvatting" style={{ fontSize: compact ? 12 : 13 }}>
      <div><b>{s.leverancier ?? 'Leverancier onbekend'}</b> → {s.afnemer ?? 'afnemer onbekend'}</div>
      <div className="hint" style={{ margin: '2px 0 6px' }}>
        {s.factuurnummer ? `Factuur ${s.factuurnummer}` : 'Zonder factuurnummer'}
        {s.factuurdatum ? ` · ${s.factuurdatum}` : ''}
        {' · '}
        {formatBedrag(s.totaal_incl, s.valuta)} incl.
        {s.totaal_excl ? ` (${formatBedrag(s.totaal_excl, s.valuta)} excl.)` : ''}
      </div>
      {s.regels.length > 0 && (
        <table className="lines" style={{ fontSize: compact ? 11.5 : 12.5 }}>
          <tbody>
            {s.regels.map((r, i) => (
              <tr key={i}>
                <td>{r.omschrijving ?? '—'}</td>
                <td className="amount">{r.aantal ?? ''}</td>
                <td className="amount">{formatBedrag(r.netto_bedrag, s.valuta)}</td>
              </tr>
            ))}
            {s.regelaantal > s.regels.length && (
              <tr>
                <td colSpan={3} className="hint">
                  … en {s.regelaantal - s.regels.length} regel(s) meer
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
