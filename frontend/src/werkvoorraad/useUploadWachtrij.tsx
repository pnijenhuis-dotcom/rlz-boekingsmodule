import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { documentPad } from './format'
import { Button } from '../ui/basis'
import {
  aantalHerkansbaar,
  filterToegestaan,
  isBezig,
  maakItems,
  markeerVoorHerkansing,
  samenvatting,
  voerWachtrijUit,
  voortgangTekst,
  type UploadItem,
  type Uploader,
} from './uploadWachtrij'

/** Hook + statusblok voor de bulk-upload (18-09): één wachtrij per upload-plek, de aanroeper geeft alleen zijn
 * per-bestand-`uploader` en `onAfgerond` (één lijst-verversing ná de hele batch — niet per bestand). De pagina
 * verlaten tijdens een batch geeft de browser-waarschuwing (beforeunload). */
export function useUploadWachtrij(uploader: Uploader, onAfgerond: () => void) {
  const [items, setItems] = useState<UploadItem[]>([])
  const [afgerondSamenvatting, setAfgerondSamenvatting] = useState<string | null>(null)
  const besturing = useRef<{ stop: () => void } | null>(null)
  const uploaderRef = useRef(uploader)
  uploaderRef.current = uploader
  const onAfgerondRef = useRef(onAfgerond)
  onAfgerondRef.current = onAfgerond
  const bezig = isBezig(items)

  useEffect(() => {
    if (!bezig) return
    const waarschuw = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', waarschuw)
    return () => window.removeEventListener('beforeunload', waarschuw)
  }, [bezig])

  const draai = useCallback((start: UploadItem[]) => {
    setAfgerondSamenvatting(null)
    setItems(start)
    const b = voerWachtrijUit(start, (bestand) => uploaderRef.current(bestand), setItems)
    besturing.current = b
    void b.klaar.then((eind) => {
      besturing.current = null
      setAfgerondSamenvatting(samenvatting(eind))
      onAfgerondRef.current()
    })
  }, [])

  const start = useCallback(
    (bestanden: File[]) => {
      if (bestanden.length === 0) return
      const { toegestaan, geweigerd } = filterToegestaan(bestanden)
      const nieuw = maakItems(toegestaan)
      const geweigerdItems: UploadItem[] = maakItems(geweigerd).map((i) => ({
        ...i,
        status: 'fout',
        melding: 'bestandstype niet ondersteund (PDF, UBL/XML, .eml of foto)',
        opnieuw: false,
      }))
      draai([...nieuw, ...geweigerdItems])
    },
    [draai],
  )

  const stop = useCallback(() => besturing.current?.stop(), [])
  const opnieuw = useCallback(() => draai(markeerVoorHerkansing(items)), [draai, items])
  const wis = useCallback(() => {
    setItems([])
    setAfgerondSamenvatting(null)
  }, [])

  return { items, bezig, start, stop, opnieuw, wis, afgerondSamenvatting }
}

const STATUS_LABEL: Record<UploadItem['status'], string> = {
  wachten: 'wachten',
  bezig: 'bezig…',
  klaar: 'klaar',
  al_aanwezig: 'al aanwezig',
  onzeker: 'onzeker',
  fout: 'fout',
  gestopt: 'niet gestart',
}

const STATUS_CHIP: Record<UploadItem['status'], string> = {
  wachten: '',
  bezig: 'ai',
  klaar: 'geboekt',
  al_aanwezig: 'geheugen',
  onzeker: 'vraag',
  fout: 'blokkerend',
  gestopt: '',
}

/** Het zichtbare batch-blok onder de zone: voortgang "37 van 180 · 2 fouten", per bestand een regel, knoppen Stoppen /
 * Mislukte opnieuw / Sluiten, en ná afloop de samenvatting. Bij 1 bestand blijft het één regel (zelfde component). */
export function UploadBatchStatus({
  items,
  bezig,
  afgerondSamenvatting,
  onStop,
  onOpnieuw,
  onWis,
  administratieId,
}: {
  items: UploadItem[]
  bezig: boolean
  afgerondSamenvatting: string | null
  onStop: () => void
  onOpnieuw: () => void
  onWis: () => void
  /** Administratie van de upload-plek (klantpagina) — terugval voor de link "→ bestaand document" als het 409-detail 'm niet draagt. */
  administratieId?: string | null
}) {
  const [uitgeklapt, setUitgeklapt] = useState(false)
  if (items.length === 0) return null
  const herkansbaar = aantalHerkansbaar(items)
  const toonAlles = uitgeklapt || items.length <= 8
  const zichtbaar = toonAlles ? items : items.filter((i) => i.status !== 'klaar' && i.status !== 'wachten').slice(0, 8)
  return (
    <div className="panel upload-batch" data-testid="upload-batch" role="status" aria-live="polite">
      <div className="upload-batch-kop">
        <b data-testid="upload-voortgang">{bezig ? `Bezig: ${voortgangTekst(items)}` : afgerondSamenvatting ?? voortgangTekst(items)}</b>
        <span className="upload-batch-knoppen">
          {bezig && (
            <Button variant="secundair" maat="klein" onClick={onStop} data-testid="upload-stoppen">
              Stoppen
            </Button>
          )}
          {!bezig && herkansbaar > 0 && (
            <Button variant="secundair" maat="klein" onClick={onOpnieuw} data-testid="upload-opnieuw">
              Mislukte opnieuw ({herkansbaar})
            </Button>
          )}
          {!bezig && (
            <button type="button" className="linkbtn" onClick={onWis}>
              Sluiten
            </button>
          )}
        </span>
      </div>
      {bezig && (
        <progress
          className="upload-batch-balk"
          max={items.length}
          value={items.filter((i) => i.status !== 'wachten' && i.status !== 'bezig').length}
          aria-label="Voortgang upload"
        />
      )}
      <ul className="upload-batch-lijst">
        {zichtbaar.map((i) => (
          <li key={i.id} data-status={i.status}>
            <span className={`chip ${STATUS_CHIP[i.status]}`.trim()}>{STATUS_LABEL[i.status]}</span>
            <span className="upload-batch-naam" title={i.bestand.name}>
              {i.bestand.name}
            </span>
            {i.melding && <span className="upload-batch-melding">— {i.melding}</span>}
            {i.status === 'al_aanwezig' && i.bestaandDocumentId && (i.bestaandAdministratieId ?? administratieId) && (
              // Besluit Peter 18-09: "al aanwezig" is geen doodlopende melding — direct naar het bestaande document.
              <Link
                className="linkbtn"
                to={documentPad((i.bestaandAdministratieId ?? administratieId) as string, { id: i.bestaandDocumentId })}
                data-testid="upload-bestaand-document-link"
              >
                → bestaand document
              </Link>
            )}
          </li>
        ))}
      </ul>
      {!toonAlles && (
        <button type="button" className="linkbtn" onClick={() => setUitgeklapt(true)}>
          Toon alle {items.length} bestanden
        </button>
      )}
    </div>
  )
}
