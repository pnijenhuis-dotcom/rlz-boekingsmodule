import { balkBreedte, percentageTekst } from './verplichtingApi'
import { formatBedrag } from '../werkvoorraad/format'

/** Verbruiksstand van één verplichting (mockup offerte-matching blok 2/3, ③ cumulatief) — het
 * RestantBalk-patroon uit het doorbelasten-blok: teal zolang er ruimte is, groen als het exact
 * vol is, rood zodra het cumulatief boven het goedgekeurde offertebedrag komt. Presentatie only:
 * percentage en bedragen komen als feit uit de server-DTO, hier wordt niets gerekend.
 *
 * Semantiek-regel designpass v2: teal = voortgang/actie, groen = status (compleet), rood = te veel. */
export function VerbruiksBalk({
  verbruikt,
  totaal,
  percentage,
  over,
  testId = 'verbruiks-balk',
}: {
  verbruikt: string | null
  totaal: string | null
  percentage: number | null
  /** Bedrag boven het offertebedrag (≥ 0) — gevuld = rode balk mét "− € X over". */
  over?: string | null
  testId?: string
}) {
  const overGetal = over === null || over === undefined ? 0 : Number(over)
  const teVeel = Number.isFinite(overGetal) && overGetal > 0
  const compleet = !teVeel && percentage !== null && percentage >= 100
  const breedte = teVeel ? 100 : balkBreedte(percentage)
  return (
    <div
      className={`restant-balk ${compleet ? 'compleet' : teVeel ? 'te-veel' : ''}`}
      data-testid={testId}
      aria-label="Verbruik van de offerte"
    >
      <div className="balk" aria-hidden="true">
        <span style={{ width: `${breedte}%` }} />
      </div>
      <b style={{ whiteSpace: 'nowrap' }}>
        {formatBedrag(verbruikt)} / {formatBedrag(totaal)}
      </b>
      {teVeel ? (
        <span className="te-veel-tekst">− {formatBedrag(over ?? null)} over</span>
      ) : (
        <span className="nog" style={{ color: 'var(--muted)', fontWeight: 600 }}>
          {percentageTekst(percentage)}
        </span>
      )}
    </div>
  )
}
