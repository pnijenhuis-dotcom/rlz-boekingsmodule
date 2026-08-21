import type { MatchAfwijkingDetailDto } from '../api/types'
import { formatBedrag } from '../werkvoorraad/format'

interface Props {
  melding: string | null
  match: MatchAfwijkingDetailDto
  /** Knoplabel wisselt met de flow: "Boeken ondanks afwijking" vs "Ter accordering ondanks afwijking". */
  actieLabel: string
  bezig: boolean
  onBevestig: () => void
  onSluiten: () => void
}

function uren(waarde: string | null): string {
  return waarde === null ? '—' : `${waarde.replace('.', ',')} uur`
}

/** Pop-up bij een onbevestigde urenmatch-afwijking (factuurmatch fase 2, besluit 2): de server
 * weigert de boek-/aanbiedenactie met 409 + de match-cijfers; hier beslist de mens bewust —
 * bevestigen herhaalt de actie mét de vlag, en het boekstuk draagt daarna zichtbaar
 * "geboekt ondanks match-afwijking" in tijdlijn + audit. Zelfde modal-opbouw als ChecksPopup. */
export function MatchAfwijkingPopup({ melding, match, actieLabel, bezig, onBevestig, onSluiten }: Props) {
  return (
    <div className="modal-bg" role="presentation" onClick={onSluiten}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="match-popup-titel"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="match-popup-titel">Urenmatch wijkt af</h2>
        {melding && <p className="hint">{melding}</p>}
        <table className="lines">
          <tbody>
            <tr>
              <td>Goedgekeurde weekstaten</td>
              <td>{uren(match.staten_som_uren)}</td>
              <td className="amount">{match.staten_som_bedrag ? formatBedrag(match.staten_som_bedrag) : '—'}</td>
            </tr>
            <tr>
              <td>Factuur</td>
              <td>{uren(match.factuur_uren)}</td>
              <td className="amount">{match.factuur_bedrag ? formatBedrag(match.factuur_bedrag) : '—'}</td>
            </tr>
            <tr>
              <td>
                <b>Verschil</b>
              </td>
              <td>
                <b>{uren(match.verschil_uren)}</b>
              </td>
              <td className="amount">
                <b>{match.verschil_bedrag ? formatBedrag(match.verschil_bedrag) : '—'}</b>
              </td>
            </tr>
          </tbody>
        </table>
        {match.tarief_ontbreekt && (
          <p className="hint">Voor (een deel van) de betrokken veldwerkers is geen tarief bekend.</p>
        )}
        <p className="hint">
          Doorgaan boekt het document ondanks deze afwijking — dat wordt zichtbaar vastgelegd in de
          tijdlijn en het auditlog.
        </p>
        <div className="actions" style={{ marginTop: 12 }}>
          <button type="button" className="btn secondary" onClick={onSluiten}>
            Annuleren
          </button>
          <button type="button" className="btn warn" disabled={bezig} onClick={onBevestig}>
            {bezig ? 'Bezig…' : actieLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
