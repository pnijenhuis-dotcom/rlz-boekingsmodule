import { balkBreedte, percentageTekst } from './verplichtingApi'
import { formatBedrag } from '../werkvoorraad/format'

/** Verbruiksstand van één verplichting (mockup offerte-matching blok 2/3, ③ cumulatief) — het
 * RestantBalk-patroon uit het doorbelasten-blok: teal zolang er ruimte is, groen als het exact
 * vol is, rood zodra het cumulatief boven het goedgekeurde offertebedrag komt. Presentatie only:
 * percentage en bedragen komen als feit uit de server-DTO, hier wordt niets gerekend.
 *
 * Semantiek-regel designpass v2: teal = voortgang/actie, groen = status (compleet), rood = te veel.
 *
 * Voorwaarschuwing (besluit Peter 04-09, mee-lift-punt 0.1): `openFacturen` = gematchte facturen die
 * nog niet geboekt zijn. Eén informatieve regel onder de balk — ze tellen NIET in het verbruik (③),
 * de balk zelf verandert er niet van. */
export function VerbruiksBalk({
  verbruikt,
  totaal,
  percentage,
  over,
  openFacturen,
  testId = 'verbruiks-balk',
}: {
  verbruikt: string | null
  totaal: string | null
  percentage: number | null
  /** Bedrag boven het offertebedrag (≥ 0) — gevuld = rode balk mét "− € X over". */
  over?: string | null
  /** Open (nog niet geboekte) gematchte facturen; aantal 0/undefined = geen regel. */
  openFacturen?: { aantal?: number; bedrag?: string | null } | null
  testId?: string
}) {
  const overGetal = over === null || over === undefined ? 0 : Number(over)
  const teVeel = Number.isFinite(overGetal) && overGetal > 0
  const compleet = !teVeel && percentage !== null && percentage >= 100
  const breedte = teVeel ? 100 : balkBreedte(percentage)
  const openAantal = openFacturen?.aantal ?? 0
  return (
    <div data-testid={`${testId}-wrap`}>
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
      {openAantal > 0 && (
        <div
          className="hint"
          data-testid={`${testId}-open`}
          style={{ margin: '2px 0 0', fontSize: 11.5 }}
          title="Nog niet geboekt — telt niet mee in het verbruik"
        >
          ⏳ {openAantal} open {openAantal === 1 ? 'factuur' : 'facturen'} op deze offerte
          {openFacturen?.bedrag ? ` (${formatBedrag(openFacturen.bedrag)})` : ''} — nog niet geboekt, telt niet mee
        </div>
      )}
    </div>
  )
}
