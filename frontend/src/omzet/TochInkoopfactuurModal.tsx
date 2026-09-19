import { useState } from 'react'
import { ApiError } from '../api/client'
import type { TochInkoopfactuurResponseDto } from '../api/types'
import { tochInkoopfactuur } from './omzetApi'

interface Props {
  administratieId: string
  documentId: string
  /** Leesbare bron van de automatische typering (bv. "ProfX-journaal") — alleen tekst. */
  bronLabel: string
  onTerug: (uitkomst: TochInkoopfactuurResponseDto) => void
  onAnnuleren: () => void
}

/** Terugweg op het omzet-controlescherm (Peter 19-09): het automatisch getypeerde kassarapport is tóch een
 * inkoopfactuur. Verplichte reden (≥ 5 tekens, zelfde modal-opbouw als AfwijsModal); de server zet het document
 * terug in de inkoopstroom en leert: ná twee correcties voor dezelfde afzender/bron meldt de module i.p.v. doen. */
export function TochInkoopfactuurModal({ administratieId, documentId, bronLabel, onTerug, onAnnuleren }: Props) {
  const [reden, setReden] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const redenTeKort = reden.trim().length < 5

  const versturen = async () => {
    setBezig(true)
    setFout(null)
    try {
      onTerug(await tochInkoopfactuur(administratieId, documentId, reden.trim()))
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Terugzetten mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div
      className="modal-bg"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !bezig) onAnnuleren()
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="toch-inkoop-titel">
        <h2 id="toch-inkoop-titel">Tóch een inkoopfactuur</h2>
        <p className="hint" style={{ marginTop: 0 }}>
          Dit document is automatisch als kassarapport getypeerd ({bronLabel} herkend). Zet je het terug, dan gaat het
          opnieuw de inkoopstroom in. Ná twee keer terugzetten voor dezelfde afzender zet de module dit type niet meer
          automatisch om, maar meldt het.
        </p>
        <div className="row">
          <label htmlFor="toch-inkoop-reden">Reden (verplicht)</label>
          <textarea
            id="toch-inkoop-reden"
            rows={3}
            placeholder="Bijv.: factuur van de kassaleverancier, geen omzetrapport"
            value={reden}
            onChange={(e) => setReden(e.target.value)}
          />
        </div>
        {fout && <div className="fout">{fout}</div>}
        <div className="actions">
          <button type="button" className="btn secondary" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </button>
          <button type="button" className="btn" onClick={() => void versturen()} disabled={bezig || redenTeKort}>
            {bezig ? 'Bezig…' : 'Terug naar inkoopfactuur'}
          </button>
        </div>
      </div>
    </div>
  )
}
