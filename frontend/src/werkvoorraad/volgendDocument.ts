import type { DocumentListItemDto } from '../api/types'
import { SOORT_VOLGORDE } from './format'

/** Statussen waarin een document "te verwerken" is voor de doorloop ná boeken/afwijzen/ter
 * accordering (besluit Peter 25-08, deel 4 punt 1): alleen werk waar de controleur zelf iets
 * mee kan — geen open vragen, geen documenten bij de klant, niets terminaal. */
export const VERWERKBARE_STATUSSEN = new Set(['te_controleren', 'klaar_om_te_boeken', 'handmatig_afmaken', 'boeken_mislukt'])

function soortRang(soort: string): number {
  const i = SOORT_VOLGORDE.indexOf(soort)
  return i === -1 ? SOORT_VOLGORDE.length : i
}

/** Kiest het eerstvolgende te verwerken document van dezelfde klant (puur, client-side):
 *  1. kandidaten = verwerkbare status én niet het huidige document (lijstvolgorde = backend-
 *     volgorde, nieuwste eerst);
 *  2. zelfde soort eerst (in lijstvolgorde);
 *  3. anders de eerste kandidaat van de volgende soort in SOORT_VOLGORDE (cyclisch ná de huidige
 *     soort; onbekende soorten helemaal achteraan);
 *  4. niets → null (de aanroeper gaat terug naar de documentenlijst). */
export function kiesVolgendDocument(
  items: DocumentListItemDto[],
  huidigId: string,
  huidigSoort: string,
): DocumentListItemDto | null {
  const kandidaten = items.filter((d) => d.id !== huidigId && VERWERKBARE_STATUSSEN.has(d.status))
  if (kandidaten.length === 0) return null
  const zelfdeSoort = kandidaten.find((d) => d.soort === huidigSoort)
  if (zelfdeSoort) return zelfdeSoort

  const n = SOORT_VOLGORDE.length
  const huidigRang = SOORT_VOLGORDE.indexOf(huidigSoort)
  const start = huidigRang === -1 ? 0 : huidigRang
  const afstand = (soort: string): number => {
    const r = soortRang(soort)
    return r >= n ? Number.POSITIVE_INFINITY : (r - start + n) % n
  }
  // Stabiele sortering: binnen één soort blijft de lijstvolgorde staan.
  return [...kandidaten].sort((a, b) => afstand(a.soort) - afstand(b.soort))[0] ?? null
}
