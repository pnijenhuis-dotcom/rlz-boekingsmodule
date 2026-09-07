import type { DocumentListItemDto } from '../api/types'
import { filterDocumenten, type FilterOpties, type LijstContext } from './lijstContext'

/** Statussen waarin een document "te verwerken" is voor de doorloop ná boeken/afwijzen/ter
 * accordering (besluit Peter 25-08, deel 4 punt 1): alleen werk waar de controleur zelf iets
 * mee kan — geen open vragen, geen documenten bij de klant, niets terminaal. */
export const VERWERKBARE_STATUSSEN = new Set(['te_controleren', 'klaar_om_te_boeken', 'handmatig_afmaken', 'boeken_mislukt'])

/** Kiest het eerstvolgende te verwerken document (puur, client-side).
 *
 *  **Besluit Peter 07-09 (herziet de soort-voorkeur van 25-08/27-08): positie in de GETOONDE
 *  lijstvolgorde wint altijd** — het eerstvolgende verwerkbare document NÁ het huidige document,
 *  daarna cyclisch verder vanaf de bovenkant van de lijst, tot (niet incl.) het huidige document
 *  zelf weer aan de beurt zou zijn. Er is geen soort-voorkeur meer: een document van een andere
 *  soort dat direct ná het huidige in de lijst staat, is gewoon de volgende stap. De
 *  verwerkbaarheids-eis (`VERWERKBARE_STATUSSEN`) blijft het enige filter op de kandidaten.
 *
 *  "Getoonde volgorde":
 *  - **Mét lijstcontext** (werkstroom-run 27/28-08, punt 1b/21): de rijen zijn de gefilterde +
 *    gesorteerde lijst van `filterDocumenten` (soort-tab, status-filter, zoekterm, kolomsortering)
 *    — exact wat de gebruiker op de documentenlijst zag. Staat het huidige document niet (meer)
 *    in dat filter (bv. de status is net veranderd door de eigen boeking), dan start de zoektocht
 *    vanaf de bovenkant van de gefilterde lijst.
 *  - **Zonder lijstcontext** (besluit Peter 07-09): de volgorde van de meegegeven `items`-lijst
 *    zoals die is aangeleverd — de aanroeper is verantwoordelijk voor het meegeven van de lijst in
 *    getoonde volgorde.
 *
 *  Niets verwerkbaars over → null (de aanroeper gaat terug naar de documentenlijst). */
export function kiesVolgendDocument(
  items: DocumentListItemDto[],
  huidigId: string,
  context: LijstContext | null = null,
  opties: FilterOpties = {},
): DocumentListItemDto | null {
  const rijen = context ? filterDocumenten(items, context, opties) : items
  const n = rijen.length
  if (n === 0) return null

  const huidigIndex = rijen.findIndex((d) => d.id === huidigId)
  // Niet (meer) in de lijst → start vanaf de bovenkant (offset 1 landt op index 0).
  const start = huidigIndex === -1 ? n - 1 : huidigIndex

  // Cyclische scan: precies de n posities ná `start`, dus élke rij komt exact één keer aan de
  // beurt en de laatste (offset n) is `start` zelf — daar wordt het huidige document alsnog
  // uitgesloten door de id-toets, zodat "alleen het huidige is verwerkbaar" → null oplevert.
  for (let offset = 1; offset <= n; offset++) {
    const kandidaat = rijen[(start + offset) % n]
    if (kandidaat.id !== huidigId && VERWERKBARE_STATUSSEN.has(kandidaat.status)) return kandidaat
  }
  return null
}
