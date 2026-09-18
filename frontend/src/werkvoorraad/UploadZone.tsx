import { useRef, useState, type ReactNode } from 'react'
import { UPLOAD_ACCEPT } from '../intake/intakeApi'
import { AnkerPopup } from '../ui/basis'
import { verzamelBestanden } from './uploadWachtrij'

/** Compacte uploadzone (werkstroom-run 27/28-08, punt 3d): één regel mét ⓘ-uitleg als popover,
 * de zone zelf lager — gedeeld door de werkvoorraad-sleepzone (tenaamstelling-routing) en de
 * klantpagina-upload (direct toegewezen). Gedrag (klik = bladeren, drag & drop, accept-lijst)
 * ongewijzigd; `extra` = optionele inline bediening (documentsoort-select op de klantpagina).
 * Bulk (Peter 18-09, "180 documenten bij BLOW, gaat niet"): `<input multiple>` + álle gesleepte bestanden — óók een
 * gesleepte map (webkitGetAsEntry, recursief) — gaan als één lijst naar `onBestanden`; de soort-keuze geldt voor de batch. */
export function UploadZone({
  regel,
  uitleg,
  bezig,
  bezigTekst,
  extra,
  onBestanden,
}: {
  /** De ene zichtbare regel ("Sleep hier … of blader"). */
  regel: ReactNode
  /** De uitleg achter het ⓘ (popover). */
  uitleg: ReactNode
  bezig: boolean
  bezigTekst: string
  extra?: ReactNode
  onBestanden: (bestanden: File[]) => void
}) {
  const bestandInputRef = useRef<HTMLInputElement>(null)
  const [sleepActief, setSleepActief] = useState(false)
  const [uitlegOpen, setUitlegOpen] = useState(false)
  const uitlegKnop = useRef<HTMLButtonElement | null>(null)

  return (
    <div
      className={`upload upload-compact${sleepActief ? ' dragover' : ''}`}
      onClick={() => bestandInputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault()
        setSleepActief(true)
      }}
      onDragLeave={() => setSleepActief(false)}
      onDrop={(e) => {
        e.preventDefault()
        setSleepActief(false)
        void verzamelBestanden(e.dataTransfer).then((bestanden) => {
          if (bestanden.length > 0) onBestanden(bestanden)
        })
      }}
    >
      {bezig ? (
        <span>{bezigTekst}</span>
      ) : (
        <span className="upload-regel">
          <span>{regel}</span>
          <button
            ref={uitlegKnop}
            type="button"
            className="icon-btn upload-uitleg-knop"
            aria-label="Uitleg over uploaden"
            aria-expanded={uitlegOpen}
            onClick={(e) => {
              e.stopPropagation()
              setUitlegOpen((o) => !o)
            }}
          >
            ⓘ
          </button>
          <AnkerPopup
            open={uitlegOpen}
            anker={uitlegKnop}
            kant="onder"
            uitlijning="start"
            className="upload-uitleg"
            role="note"
            onAnkerUitBeeld={() => setUitlegOpen(false)}
            onClick={(e) => e.stopPropagation()}
          >
            {uitleg}
          </AnkerPopup>
          {extra && (
            <span className="upload-extra" onClick={(e) => e.stopPropagation()}>
              {extra}
            </span>
          )}
        </span>
      )}
      <input
        ref={bestandInputRef}
        type="file"
        accept={UPLOAD_ACCEPT}
        multiple
        data-testid="upload-input"
        style={{ display: 'none' }}
        onChange={(e) => {
          const bestanden = Array.from(e.target.files ?? [])
          if (bestanden.length > 0) onBestanden(bestanden)
          // Zelfde selectie nog eens kiezen moet opnieuw een change geven.
          e.target.value = ''
        }}
      />
    </div>
  )
}
