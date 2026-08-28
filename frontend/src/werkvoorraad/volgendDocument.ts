import type { DocumentListItemDto } from '../api/types'
import { SOORT_VOLGORDE } from './format'
import { STATUSFILTER_ALLE, filterDocumenten, type FilterOpties, type LijstContext } from './lijstContext'

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
 *  4. niets → null (de aanroeper gaat terug naar de documentenlijst).
 *
 *  Mét lijstcontext (werkstroom-run 27/28-08, punt 1b): de kandidaten zijn dan de rijen van de
 *  gefilterde lijst (soort-tab + status-filter + zoekterm) — vanuit "Klaar om te boeken" boeken
 *  geeft het volgende klaar-om-te-boeken-document, nooit ineens een te-controleren. De
 *  verwerkbaarheids-eis blijft gelden (een filter "Bij klant" levert geen doorloop op → lijst).
 *  Volgorde binnen het filter: het document ná het huidige in lijstvolgorde, anders het eerste
 *  vóór het huidige (cyclisch — "de stapel"), zodat de gebruiker de lijst van boven naar beneden
 *  afwerkt. Filter leeg → null → terug naar de lijst mét dat filter. */
export function kiesVolgendDocument(
  items: DocumentListItemDto[],
  huidigId: string,
  huidigSoort: string,
  context: LijstContext | null = null,
  opties: FilterOpties = {},
): DocumentListItemDto | null {
  // Punt 21: óók een kale sortering (zonder filter) is context — de doorloop volgt dan die volgorde.
  if (
    context &&
    (context.status !== STATUSFILTER_ALLE || context.zoekterm.trim() || context.soort !== null || context.sortering)
  ) {
    const rijen = filterDocumenten(items, context, opties)
    const kandidaten = rijen.filter((d) => VERWERKBARE_STATUSSEN.has(d.status))
    const huidigIndex = rijen.findIndex((d) => d.id === huidigId)
    const na = kandidaten.find((d) => d.id !== huidigId && rijen.indexOf(d) > huidigIndex)
    if (na) return na
    return kandidaten.find((d) => d.id !== huidigId) ?? null
  }

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
