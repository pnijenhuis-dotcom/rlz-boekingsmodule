import type { ComboboxOptie } from './SearchableCombobox'

/** Fix 2 (2026-07-10): de AI las een leveranciersnaam die niet (uniek) in de crediteuren-cache
 * matcht — het controlescherm toont dan klikbare "koppel aan bestaande crediteur"-suggesties.
 * Dit is puur presentatie-ordening (welke cache-namen lijken op de gelezen naam); de keuze zelf
 * blijft altijd een menselijke klik, en de backend-controlelaag (app/extractie/controle.py)
 * blijft de enige bron voor het automatische voorstel. Normalisatie spiegelt de backend:
 * rechtsvorm-ruis (BV/NV/VOF/CV/Holding) en leestekens tellen niet mee. */

const RECHTSVORM = /\b(b\.?v\.?|n\.?v\.?|v\.?o\.?f\.?|c\.?v\.?|holding)\b/gi

export function normaliseerNaam(naam: string): string {
  return naam
    .toLowerCase()
    .replace(RECHTSVORM, ' ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

function bigrammen(tekst: string): Map<string, number> {
  const map = new Map<string, number>()
  for (let i = 0; i < tekst.length - 1; i++) {
    const gram = tekst.slice(i, i + 2)
    map.set(gram, (map.get(gram) ?? 0) + 1)
  }
  return map
}

/** Sørensen–Dice op tekens-bigrammen: 0..1, robuust voor woordvolgorde-varianten en kleine
 * spelverschillen — genoeg voor suggestie-ordening, bewust geen exacte-matchlogica. */
export function naamGelijkenis(a: string, b: string): number {
  const na = normaliseerNaam(a)
  const nb = normaliseerNaam(b)
  if (!na || !nb) return 0
  if (na === nb) return 1
  const ga = bigrammen(na)
  const gb = bigrammen(nb)
  let overlap = 0
  let totaalA = 0
  let totaalB = 0
  for (const n of ga.values()) totaalA += n
  for (const n of gb.values()) totaalB += n
  for (const [gram, n] of ga) overlap += Math.min(n, gb.get(gram) ?? 0)
  if (totaalA + totaalB === 0) return 0
  return (2 * overlap) / (totaalA + totaalB)
}

// Lager dan de backend-drempel voor het automatische voorstel (0.85): dit zijn klikbare
// suggesties die de controleur zelf beoordeelt, geen automatische keuze.
const SUGGESTIE_DREMPEL = 0.5
const MAX_SUGGESTIES = 3

export interface CrediteurSuggestie {
  optie: ComboboxOptie
  score: number
}

/** Beste cache-kandidaten voor een AI-gelezen leveranciersnaam, gesorteerd op gelijkenis. */
export function crediteurSuggesties(aiNaam: string, opties: ComboboxOptie[]): CrediteurSuggestie[] {
  return opties
    .map((optie) => ({ optie, score: naamGelijkenis(aiNaam, optie.label) }))
    .filter((s) => s.score >= SUGGESTIE_DREMPEL)
    .sort((a, b) => b.score - a.score)
    .slice(0, MAX_SUGGESTIES)
}
