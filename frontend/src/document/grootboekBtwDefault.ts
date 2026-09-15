/** Btw-default per grootboekrekening — één bron voor het controlescherm (BoekvoorstelPanel) én de bankschermen
 * (HandmatigBoekenForm, SplitsenForm) sinds 15-09 (bug-onderzoek L.H.G. Holding "Kosten mobiele telefonie": de casus
 * bleek een bank-direct-boeking vanuit het bankscherm; dáár volgde de btw-code de gekozen rekening nog niet).
 *
 * Per rekening: de RLZ-/Odoo-default ('grootboek', grijze chip "standaard grootboek") óf — als die ontbreekt — de uit de
 * eigen historie afgeleide default ('grootboek_historie', oranje "meestal op deze rekening (n×)"), dezelfde volgorde als
 * server-side (regel_prefill.py stap 5 → 5b). Alleen tarieven die in de btw-lijst van de administratie staan (een
 * verdwenen tarief vult nooit). Code, geen AI. */
import type { ComboboxOptie } from './SearchableCombobox'

export interface GrootboekBtwDefault {
  taxrateId: string
  bron: 'grootboek' | 'grootboek_historie'
  detail: string | null
}

export type GrootboekBtwDefaultMap = Record<string, GrootboekBtwDefault>

export function bouwGrootboekBtwDefaultMap(grootboekOpties: ComboboxOptie[], taxrateOpties: ComboboxOptie[]): GrootboekBtwDefaultMap {
  const map: GrootboekBtwDefaultMap = {}
  const bekendeTarieven = new Set(taxrateOpties.map((t) => t.id))
  for (const optie of grootboekOpties) {
    if (optie.standaardTaxrateId && bekendeTarieven.has(optie.standaardTaxrateId)) {
      map[optie.id] = { taxrateId: optie.standaardTaxrateId, bron: 'grootboek', detail: null }
    } else if (optie.historieTaxrateId && bekendeTarieven.has(optie.historieTaxrateId)) {
      map[optie.id] = {
        taxrateId: optie.historieTaxrateId,
        bron: 'grootboek_historie',
        detail: optie.historieTaxrateN ? `meestal op deze rekening (${optie.historieTaxrateN}×)` : null,
      }
    }
  }
  return map
}

/** Btw-keuze die de gekozen grootboekrekening volgt (bankschermen): `null` = leegmaken (rekening zonder default). Alleen
 * aanroepen zolang de btw-code niet van de mens is — die wint altijd. */
export function btwVolgtRekening(
  ledgerId: string | null,
  map: GrootboekBtwDefaultMap,
): { taxrateId: string | null; bron: GrootboekBtwDefault['bron'] | null; detail: string | null } {
  const standaard = ledgerId ? map[ledgerId] : undefined
  return standaard ? { ...standaard } : { taxrateId: null, bron: null, detail: null }
}
