import { useState } from 'react'
import { ApiError } from '../api/client'
import { stornoDoorbelastingBoeking } from './doorbelastingApi'

interface Props {
  administratieId: string
  boekingId: string
  doelentiteitNaam: string
  onGestorneerd: () => void
  onAnnuleren: () => void
}

/** Storno van één doorbelastings-deelboeking (modal-patroon AfwijsModal): verplichte reden
 * (backend eist ≥5 tekens), actie 19 beide kanten — niets verdwijnt stil, de storno-reden
 * staat in het audit log en de boeking blijft als "gestorneerd" zichtbaar. */
export function StornoModal({ administratieId, boekingId, doelentiteitNaam, onGestorneerd, onAnnuleren }: Props) {
  const [reden, setReden] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const versturen = async () => {
    setBezig(true)
    setFout(null)
    try {
      await stornoDoorbelastingBoeking(administratieId, boekingId, reden.trim())
      onGestorneerd()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Storneren mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const redenTeKort = reden.trim().length < 5

  return (
    <div
      className="modal-bg"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !bezig) onAnnuleren()
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="storno-modal-titel">
        <h2 id="storno-modal-titel">Doorbelasting storneren — {doelentiteitNaam}</h2>
        <div className="row">
          <label htmlFor="storno-reden">Reden van stornering (verplicht, minimaal 5 tekens)</label>
          <textarea
            id="storno-reden"
            rows={3}
            placeholder="Bijv.: verkeerde verdeling / factuur zelf gestorneerd / dubbel doorbelast"
            value={reden}
            onChange={(e) => setReden(e.target.value)}
          />
        </div>
        <p className="hint" style={{ marginTop: 0 }}>
          De verkoopfactuur in de bron én de spiegel-inkoopfactuur in de doel-administratie worden
          teruggezet naar concept (Reeleezee-actie 19) — er wordt nooit iets verwijderd. De reden komt in
          het audit log en de deelboeking blijft zichtbaar als &ldquo;gestorneerd&rdquo;.
        </p>
        {fout && <div className="fout">{fout}</div>}
        <div className="actions">
          <button type="button" className="btn secondary" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </button>
          <button type="button" className="btn warn" onClick={() => void versturen()} disabled={bezig || redenTeKort}>
            {bezig ? 'Bezig…' : 'Storneren'}
          </button>
        </div>
      </div>
    </div>
  )
}
