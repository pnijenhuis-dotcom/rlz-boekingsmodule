import { useState } from 'react'

interface Props {
  bestandsnaam: string
  bezig: boolean
  fout: string | null
  onBevestigen: (reden: string) => void
  onAnnuleren: () => void
}

/** Bevestigingsdialoog mét VERPLICHTE reden (werkstroom-run 27/28-08, punt 4 — herziet
 * design-pass taak 4 "reden optioneel"): verwijderen zit sinds die run achter het ⋯-rijmenu en
 * volgt het afwijs-patroon, zodat een zware actie nooit meer op één onbeschermde klik gebeurt.
 * Benoemt expliciet wat er gebeurt ("niets verdwijnt stil"): soft-delete — bestand en
 * geschiedenis blijven bewaard, herstel via "Toon verwijderde documenten". De server eist de
 * reden óók (422 zonder). */
export function VerwijderDialog({ bestandsnaam, bezig, fout, onBevestigen, onAnnuleren }: Props) {
  const [reden, setReden] = useState('')
  const redenOk = reden.trim().length > 0

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
          "{bestandsnaam}" verdwijnt uit de werkvoorraad en telt niet meer mee in de standen. Het wordt niet
          definitief verwijderd — het bestand en de geschiedenis blijven bewaard en het is altijd te herstellen via
          "Toon verwijderde documenten". De reden komt in de tijdlijn en het auditlog.
        </p>
        <div className="row">
          <label htmlFor="verwijder-reden">Reden (verplicht)</label>
          <input
            id="verwijder-reden"
            value={reden}
            onChange={(e) => setReden(e.target.value)}
            disabled={bezig}
            autoFocus
            placeholder="Bijvoorbeeld: per abuis twee keer geüpload"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && redenOk && !bezig) onBevestigen(reden.trim())
            }}
          />
        </div>
        {fout && <div className="fout">{fout}</div>}
        <div className="actions">
          <button type="button" className="btn secondary" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => onBevestigen(reden.trim())}
            disabled={bezig || !redenOk}
            title={redenOk ? undefined : 'Vul eerst een reden in'}
          >
            {bezig ? 'Bezig…' : 'Verwijderen'}
          </button>
        </div>
      </div>
    </div>
  )
}
