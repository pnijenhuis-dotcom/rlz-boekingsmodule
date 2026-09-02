/** Percentage-invoer voor de doorbelasting-verdeling (bugfix 02-09, mockup
 * `doorbelasten-blok-v2.html` ontwerpnotitie ⑦): één bron voor parsen, sommeren en
 * omrekenen % ↔ bedrag. Regels: alleen 0–100, hooguit 2 decimalen, komma óf punt als
 * decimaalteken; alles anders (duizendtal-scheiders, twee scheidingstekens, letters) is een
 * zichtbare fout — nooit stil doorgerekend. De bindende centenverdeling (grootste-rest) blijft
 * server-side (`app/doorbelasting/geld.py`); alles hier is weergave en invoer-poort. */

export interface PercentageParse {
  /** Genormaliseerde waarde (0–100, max 2 decimalen); null bij leeg of ongeldig. */
  waarde: number | null
  /** Menselijke uitleg bij ongeldige invoer; null bij leeg of geldig. */
  fout: string | null
}

const GELDIG = /^\d{1,3}(?:[.,]\d{1,2})?$/

export const PERCENTAGE_UITLEG = 'Alleen 0–100 met hooguit 2 decimalen (bv. 33,33).'

/** Parseert een getypt percentage. Leeg = geen waarde, geen fout (de rij telt als 0). */
export function parsePercentage(invoer: string): PercentageParse {
  const schoon = invoer.trim()
  if (schoon === '') return { waarde: null, fout: null }
  if (!GELDIG.test(schoon)) {
    return { waarde: null, fout: `"${schoon}" is geen geldig percentage. ${PERCENTAGE_UITLEG}` }
  }
  const getal = Number(schoon.replace(',', '.'))
  if (!Number.isFinite(getal) || getal < 0 || getal > 100) {
    return { waarde: null, fout: `${schoon}% ligt buiten 0–100. ${PERCENTAGE_UITLEG}` }
  }
  return { waarde: rond2(getal), fout: null }
}

/** Percentage als string voor de backend (punt-decimaal), of null als de invoer ongeldig is. */
export function percentageVoorBackend(invoer: string): string | null {
  const { waarde } = parsePercentage(invoer)
  return waarde === null ? null : String(waarde)
}

export function rond2(x: number): number {
  return Math.round(x * 100) / 100
}

/** NL-weergave van een percentage-getal zonder overbodige nullen: 50 → "50", 33.333 → "33,33". */
export function formatPct(x: number): string {
  return String(rond2(x)).replace('.', ',')
}

/** Som van getypte percentages; ongeldige of lege invoer telt als 0 (de poort staat elders). */
export function somPercentages(invoer: string[]): number {
  return rond2(invoer.reduce((acc, p) => acc + (parsePercentage(p).waarde ?? 0), 0))
}

/** Wat er nog te verdelen is (nooit negatief) — voorgevuld in een nieuwe rij. */
export function restPercentage(invoer: string[]): number {
  return Math.max(0, rond2(100 - somPercentages(invoer)))
}

/** Indicatief bedrag bij een percentage (weergave; de server rondt bindend). */
export function percentageNaarBedrag(netto: number, percentage: number): number {
  return rond2((netto * percentage) / 100)
}

/** Percentage dat bij een getypt bedrag hoort; null als er geen regelbedrag is of het bedrag
 * niet parseert. Boven 100 % of onder 0 wordt niet geclampt — de balk toont dan "te veel". */
export function bedragNaarPercentage(netto: number, bedragInvoer: string): number | null {
  if (!Number.isFinite(netto) || netto === 0) return null
  const schoon = bedragInvoer.trim()
  if (!/^-?\d{1,9}(?:[.,]\d{1,2})?$/.test(schoon)) return null
  const bedrag = Number(schoon.replace(',', '.'))
  if (!Number.isFinite(bedrag)) return null
  return rond2((bedrag / netto) * 100)
}

/** Stand van de restant-balk: één van drie standen (mockup "Foutstaten — altijd menselijk"). */
export type RestantStand = 'open' | 'compleet' | 'te_veel'

export function restantStand(som: number): RestantStand {
  if (som === 100) return 'compleet'
  return som > 100 ? 'te_veel' : 'open'
}
