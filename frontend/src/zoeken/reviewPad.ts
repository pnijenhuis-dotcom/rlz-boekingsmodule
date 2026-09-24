import { documentPad } from '../werkvoorraad/format'

/** Zelfde soort-switch als de werkvoorraad — sinds 24-09 (BUG 23-09) een dunne laag op de ene bron
 * `werkvoorraad/format.ts::documentPad`: kassarapport → omzetreview, verkoopfactuur → verkoopreview, waarborg,
 * verplichting, al het andere → inkoop-controlescherm. */
export function reviewPad(soort: string, administratieId: string, documentId: string): string {
  return documentPad(administratieId, { id: documentId, soort })
}
