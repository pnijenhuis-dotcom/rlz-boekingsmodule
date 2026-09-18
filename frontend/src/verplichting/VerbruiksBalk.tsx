import { onderwegTekst, percentageTekst, verbruikSegmenten } from './verplichtingApi'
import { formatBedrag } from '../werkvoorraad/format'

/** Verbruiksstand van één verplichting (mockup offerte-matching blok 2/3, ③ cumulatief) — het
 * RestantBalk-patroon uit het doorbelasten-blok: teal zolang er ruimte is, groen als het exact
 * vol is, rood zodra het cumulatief boven het goedgekeurde offertebedrag komt. Presentatie only:
 * percentage en bedragen komen als feit uit de server-DTO; alleen de segmentbreedtes zijn verhoudingen.
 *
 * Semantiek-regel designpass v2: teal = voortgang/actie, groen = status (compleet), rood = te veel.
 *
 * Drie segmenten (Peter 18-09, casus Bouwadvies "hij moet wel doortellen"): GEBOEKT vol, ONDERWEG gearceerd (de
 * gematchte facturen die nog niet geboekt zijn — ze tellen sinds 18-09 MEE in het verbruik), de EIGEN factuur
 * gemarkeerd (alleen op het controlescherm/de accordeur-kaart). Onder de balk de zin "waarvan € X nog niet geboekt
 * (N facturen ter accordering)" en, waar de server 'm levert, de drie getallen geboekt · onderweg · restant. */
export function VerbruiksBalk({
  verbruikt,
  totaal,
  percentage,
  over,
  onderweg,
  eigen,
  restant,
  labelBedrag,
  openFacturen,
  testId = 'verbruiks-balk',
}: {
  /** Geboekt (de boekstand). */
  verbruikt: string | null
  totaal: string | null
  /** Percentage van het TOTALE verbruik (geboekt + onderweg [+ eigen]) — server-feit. */
  percentage: number | null
  /** Bedrag boven het offertebedrag (≥ 0) — gevuld = rode balk mét "− € X over". */
  over?: string | null
  /** Onderweg: nog niet geboekte gematchte facturen (tellen mee). */
  onderweg?: { aantal?: number | null; bedrag?: string | null; terAccordering?: number | null } | null
  /** Het bedrag van de factuur die nu bekeken wordt — gemarkeerd segment. */
  eigen?: string | null
  /** Restant = totaal − geboekt − onderweg (negatief = overschreden); gevuld = regel met de drie getallen. */
  restant?: string | null
  /** Bedrag in de vette tekst naast de balk (default = `verbruikt`); het controlescherm toont hier het cumulatief ná
   * deze factuur (geboekt + onderweg + eigen) terwijl de segmenten de splitsing tonen. */
  labelBedrag?: string | null
  /** @deprecated oude naam van `onderweg` (0.1, 04-09) — blijft werken. */
  openFacturen?: { aantal?: number; bedrag?: string | null } | null
  testId?: string
}) {
  const overGetal = over === null || over === undefined ? 0 : Number(over)
  const teVeel = Number.isFinite(overGetal) && overGetal > 0
  const compleet = !teVeel && percentage !== null && percentage >= 100
  const ow = onderweg ?? (openFacturen ? { aantal: openFacturen.aantal, bedrag: openFacturen.bedrag } : null)
  const onderwegAantal = ow?.aantal ?? 0
  const seg = verbruikSegmenten({ geboekt: verbruikt, onderweg: ow?.bedrag, eigen, totaal })
  // Zonder bruikbaar totaal (of zonder segmenten) valt de balk terug op het server-percentage als één segment.
  const somSegmenten = seg.geboekt + seg.onderweg + seg.eigen
  const enkel = somSegmenten === 0 && percentage !== null && percentage > 0
  const zin = onderwegTekst(ow?.bedrag, onderwegAantal, ow?.terAccordering, formatBedrag)
  return (
    <div data-testid={`${testId}-wrap`}>
      <div
        className={`restant-balk ${compleet ? 'compleet' : teVeel ? 'te-veel' : ''}`}
        data-testid={testId}
        aria-label="Verbruik van de offerte"
      >
        <div className="balk" aria-hidden="true">
          {enkel ? (
            <span style={{ width: `${teVeel ? 100 : Math.min(100, Math.max(0, percentage ?? 0))}%` }} />
          ) : (
            <>
              {seg.geboekt > 0 && <span className="geboekt" style={{ width: `${seg.geboekt}%` }} />}
              {seg.onderweg > 0 && (
                <span className="onderweg" data-testid={`${testId}-seg-onderweg`} style={{ width: `${seg.onderweg}%` }} />
              )}
              {seg.eigen > 0 && (
                <span className="eigen" data-testid={`${testId}-seg-eigen`} style={{ width: `${seg.eigen}%` }} />
              )}
            </>
          )}
        </div>
        <b style={{ whiteSpace: 'nowrap' }}>
          {formatBedrag(labelBedrag === undefined ? verbruikt : labelBedrag)} / {formatBedrag(totaal)}
        </b>
        {teVeel ? (
          <span className="te-veel-tekst">− {formatBedrag(over ?? null)} over</span>
        ) : (
          <span className="nog" style={{ color: 'var(--muted)', fontWeight: 600 }}>
            {percentageTekst(percentage)}
          </span>
        )}
      </div>
      {onderwegAantal > 0 && (
        <div
          className="hint"
          data-testid={`${testId}-open`}
          style={{ margin: '2px 0 0', fontSize: 11.5 }}
          title="Nog niet geboekt — telt mee in het verbruik"
        >
          ⏳ {zin || `${onderwegAantal} ${onderwegAantal === 1 ? 'factuur' : 'facturen'} nog niet geboekt`} — telt mee
        </div>
      )}
      {restant !== undefined && restant !== null && (
        <div className="hint" data-testid={`${testId}-drie`} style={{ margin: '2px 0 0', fontSize: 11.5 }}>
          geboekt {formatBedrag(verbruikt)} · onderweg {formatBedrag(ow?.bedrag ?? '0')} · restant{' '}
          {Number(restant) < 0 ? (
            <span style={{ color: 'var(--red)', fontWeight: 600 }}>{formatBedrag(restant)}</span>
          ) : (
            formatBedrag(restant)
          )}
        </div>
      )}
    </div>
  )
}
