import { useState } from 'react'

interface Props {
  bestandsnaam: string
  bezig: boolean
  fout: string | null
  onBevestigen: (reden: string) => void
  onAnnuleren: () => void
}

/** Bevestigingsdialoog met optionele reden (design-pass taak 4) — benoemt expliciet dat dit een
 * soft-delete is ("niets verdwijnt stil"): bestand en geschiedenis blijven bewaard, herstel kan
 * altijd nog via het "toon verwijderde documenten"-filter. */
export function VerwijderDialog({ bestandsnaam, bezig, fout, onBevestigen, onAnnuleren }: Props) {
  const [reden, setReden] = useState('')

  return (
    <div
      className="modal-bg"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onAnnuleren()
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="verwijder-dialog-titel">
        <h2 id="verwijder-dialog-titel">Document verwijderen?</h2>
        <p className="hint" style={{ marginTop: 0 }}>
          "{bestandsnaam}" wordt niet definitief verwijderd — het bestand en de geschiedenis blijven bewaard. Je kunt
          het altijd herstellen via "Toon verwijderde documenten".
        </p>
        <div className="row">
          <label htmlFor="verwijder-reden">Reden (optioneel)</label>
          <input
            id="verwijder-reden"
            value={reden}
            onChange={(e) => setReden(e.target.value)}
            disabled={bezig}
            placeholder="Bijvoorbeeld: per abuis twee keer geüpload"
          />
        </div>
        {fout && <div className="fout">{fout}</div>}
        <div className="actions">
          <button type="button" className="btn secondary" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </button>
          <button type="button" className="btn" onClick={() => onBevestigen(reden)} disabled={bezig}>
            {bezig ? 'Bezig…' : 'Verwijderen'}
          </button>
        </div>
      </div>
    </div>
  )
}
