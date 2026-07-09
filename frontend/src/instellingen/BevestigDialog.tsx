interface Props {
  titel: string
  bericht: string
  bezig: boolean
  fout: string | null
  onBevestigen: () => void
  onAnnuleren: () => void
}

/** Generieke bevestigingsdialoog voor beheerinstellingen (design-pass taak 3: "elke wijziging
 * toont een bevestiging") — zelfde modal-patroon als werkvoorraad/VerwijderDialog, maar zonder
 * redenveld: dit zijn schakelaars, geen document-actie met audit-reden. */
export function BevestigDialog({ titel, bericht, bezig, fout, onBevestigen, onAnnuleren }: Props) {
  return (
    <div
      className="modal-bg"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onAnnuleren()
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="bevestig-dialog-titel">
        <h2 id="bevestig-dialog-titel">{titel}</h2>
        <p className="hint" style={{ marginTop: 0 }}>
          {bericht}
        </p>
        {fout && <div className="fout">{fout}</div>}
        <div className="actions">
          <button type="button" className="btn secondary" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </button>
          <button type="button" className="btn" onClick={onBevestigen} disabled={bezig}>
            {bezig ? 'Bezig…' : 'Bevestigen'}
          </button>
        </div>
      </div>
    </div>
  )
}
