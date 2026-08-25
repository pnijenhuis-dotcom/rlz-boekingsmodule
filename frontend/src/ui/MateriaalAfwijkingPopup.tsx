import type { MateriaalmatchDto } from '../planning/transportApi'

/* Bevestigingspop-up "boeken ondanks materiaal-afwijking" (steigerbouw-run D6, besluit Peter
 * 24-08 — zelfde vlag-patroon als de urenmatch): de factuurregels van de verhuur-crediteur vs.
 * de geregistreerde leveringen/huurperiodes (aantal × huurperiode per item). Bevestigen herhaalt
 * de boek-/aanbiedactie mét materiaal_afwijking_bevestigd; server legt de bevestiging persistent
 * vast + audit ("geboekt ondanks materiaal-afwijking"). */
interface Props {
  melding: string | null
  match: Pick<MateriaalmatchDto, 'uitkomst' | 'aantal_regels_getoetst' | 'aantal_regels_afwijkend' | 'aantal_regels_onbekend'> & {
    regels?: NonNullable<MateriaalmatchDto['details']>['regels']
  }
  actieLabel: string
  bezig: boolean
  onBevestig: () => void
  onSluiten: () => void
}

export function MateriaalAfwijkingPopup({ melding, match, actieLabel, bezig, onBevestig, onSluiten }: Props) {
  const regels = (match.regels ?? []).filter((r) => r.status === 'afwijking')
  return (
    <div className="modal-bg" role="presentation" onClick={onSluiten}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="materiaal-popup-titel" onClick={(e) => e.stopPropagation()}>
        <h2 id="materiaal-popup-titel">Materiaalcontrole wijkt af</h2>
        {melding && <p className="hint">{melding}</p>}
        <p className="hint" style={{ marginTop: 0 }}>
          {match.aantal_regels_afwijkend} van {match.aantal_regels_getoetst} getoetste factuurregel(s) sluit niet op de geregistreerde
          leveringen (aantal × huurperiode per item)
          {match.aantal_regels_onbekend > 0 ? ` · ${match.aantal_regels_onbekend} regel(s) niet herkend als catalogusproduct` : ''}.
        </p>
        {regels.length > 0 && (
          <table className="lines">
            <tbody>
              <tr>
                <th>Factuurregel</th>
                <th>Hoeveelheid</th>
                <th>Verwacht (aantal)</th>
                <th>Verwacht (item-weken)</th>
              </tr>
              {regels.map((r, i) => (
                <tr key={i}>
                  <td>
                    {r.omschrijving}
                    {r.product_naam && <div className="hint" style={{ fontSize: 11 }}>→ {r.product_naam}</div>}
                  </td>
                  <td>{r.hoeveelheid ?? '—'}</td>
                  <td>{r.verwacht_aantal ?? '—'}</td>
                  <td>{r.verwacht_huur_eenheden ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="hint">
          Boeken mág — met deze bewuste klik wordt &quot;geboekt ondanks materiaal-afwijking&quot; in de tijdlijn en het audit-log
          vastgelegd. Controleer anders eerst de leveringen op de Transport-tab.
        </p>
        <div className="actions">
          <button className="btn secondary" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </button>
          <button className="btn" onClick={onBevestig} disabled={bezig}>
            {bezig ? 'Bezig…' : actieLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
