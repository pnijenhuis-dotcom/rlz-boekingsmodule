import { useMemo } from 'react'
import type { ComboboxOptie } from './SearchableCombobox'

/** Btw-keuzelijst NL-eerst (opdracht Peter 18-09 DEEL B: "ik zie telkens alle nul % tarieven, ook alle EU-regels. Als
 * leverancier NLD adres heeft dan die hele rits graag niet tonen") — ÉÉN hook voor álle tarief-comboboxen (inkoop,
 * verkoop-review, omzet, doorbelasting, bank). Weergave alleen: het prefill-/autoboek-pad verandert niet.
 *
 * - `land` = het land van de leverancier uit de boekvoorstel-respons (`leverancier_land`, deterministisch: btw-nummer
 *   crediteur → btw-nummer factuur → IBAN → onbekend). 'NL' → buitenland-tarieven (naam-prefix ≠ NL) ingeklapt achter
 *   "Buitenland-tarieven tonen (N)" (SearchableCombobox `ingeklapteGroep`); ≠ NL → alles zichtbaar mét de tarieven van
 *   dát land/EU bovenaan; null/undefined (onbekend) → alles zichtbaar. Nooit iets wegnemen op een gok.
 * - Volgorde: de tarieven die deze administratie de laatste 12 maanden gebruikte bovenaan op frequentie
 *   (`gebruik12m` uit `GET …/btw-codes`), daarna alfabetisch; nul-tarieven blijven onderscheidbaar op RLZ-naam.
 * - Een al gekozen buitenland-tarief blijft altijd zichtbaar/geselecteerd (de combobox laat de geselecteerde optie
 *   staan, ook ingeklapt). */

export const GROEP_BUITENLAND = 'buitenland'

export interface TaxrateLandInfo {
  land: string | null | undefined
}

export function landPrefix(label: string): string | null {
  if (!label.includes(',')) return null
  const prefix = label.split(',', 1)[0].trim().toUpperCase()
  return prefix || null
}

/** Pure sortering/groepering — testbaar zonder React. */
export function filterEnSorteerTaxrates(opties: ComboboxOptie[], land: string | null | undefined): ComboboxOptie[] {
  const landCode = land ? land.trim().toUpperCase() : null
  const eigenLand = (o: ComboboxOptie): boolean => {
    if (!landCode || landCode === 'NL') return false
    const prefix = landPrefix(o.label)
    return prefix === landCode || prefix === 'EU' || prefix === 'EU + EX-EU'
  }
  return [...opties]
    .map((o) => ({ ...o, groep: o.buitenland ? GROEP_BUITENLAND : o.groep }))
    .sort((a, b) => {
      // 1. buitenlandse leverancier: de tarieven van dat land/EU bovenaan
      const la = eigenLand(a) ? 0 : 1
      const lb = eigenLand(b) ? 0 : 1
      if (la !== lb) return la - lb
      // 2. gebruik in de laatste 12 maanden (hoog → laag)
      const ga = a.gebruik12m ?? 0
      const gb = b.gebruik12m ?? 0
      if (ga !== gb) return gb - ga
      // 3. alfabetisch op naam
      return a.label.localeCompare(b.label, 'nl')
    })
}

export function useTaxrateOptiesGefilterd(
  opties: ComboboxOptie[],
  land: string | null | undefined,
): { opties: ComboboxOptie[]; ingeklapteGroep?: { groep: string; label: (aantal: number) => string } } {
  const gesorteerd = useMemo(() => filterEnSorteerTaxrates(opties, land), [opties, land])
  const nl = (land ?? '').trim().toUpperCase() === 'NL'
  return useMemo(
    () => ({
      opties: gesorteerd,
      ingeklapteGroep: nl ? { groep: GROEP_BUITENLAND, label: (n: number) => `Buitenland-tarieven tonen (${n})` } : undefined,
    }),
    [gesorteerd, nl],
  )
}
