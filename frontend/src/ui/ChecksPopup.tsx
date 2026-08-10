import type { CheckRapportDto } from '../api/types'

interface Props {
  titel?: string
  melding: string | null
  checks: CheckRapportDto
  onSluiten: () => void
}

/** Pop-up bij een server-side geblokkeerde boekactie (blok B 2026-08-10): "Boeken in RLZ"
 * herdraait de harde checks server-side; faalt er één, dan noemt deze pop-up de concrete
 * gefaalde check(s) — de inline checklijst op het scherm blijft daarnaast gewoon staan.
 * Zelfde modal-opbouw als AfwijsModal (.modal-bg/.modal). */
export function ChecksPopup({ titel, melding, checks, onSluiten }: Props) {
  const gefaald = checks.resultaten.filter((r) => !r.ok)
  return (
    <div className="modal-bg" role="presentation" onClick={onSluiten}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="checks-popup-titel"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="checks-popup-titel">{titel ?? 'Boeken geblokkeerd door harde checks'}</h2>
        {melding && <p className="hint">{melding}</p>}
        <table className="lines">
          <tbody>
            {gefaald.map((r) => (
              <tr key={r.naam}>
                <td>
                  <span className="chip blokkerend">Blokkerend</span>
                </td>
                <td>
                  <b>{r.naam}</b>
                </td>
                <td>{r.melding}</td>
              </tr>
            ))}
            {gefaald.length === 0 && (
              <tr>
                <td colSpan={3} className="hint">
                  De server gaf geen individuele checkresultaten mee — zie de melding hierboven.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <div className="actions" style={{ marginTop: 12 }}>
          <button type="button" className="btn secondary" onClick={onSluiten}>
            Sluiten
          </button>
        </div>
      </div>
    </div>
  )
}
