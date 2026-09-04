/** Herkomst-chips voor regel-niveau voorstellen op het controlescherm (medewerker-wensen 04-09,
 * mockup projectverdeling-en-regelvoorstellen.html blok 2 + 3 — 1-op-1):
 * - grootboek per regel (blok D, backend `gb_bron`): groen "uit geheugen" (deterministisch, app-bevestigd),
 *   oranje "uit historie, nog niet bevestigd" (alleen RLZ-historie), oranje "geheugen wisselend" (conflict,
 *   jongste keuze), oranje "AI-voorstel — bevestig" (AI-classificatie tegen de historische grootboeken);
 * - btw-default van de administratie (blok E, backend `btw_bron = 'standaard'`): neutrale grijze chip
 *   "standaard administratie".
 * Pure beslislogica los van React (zelfde patroon als geheugenVoorstel.ts) zodat de chip-stand direct
 * unit-testbaar is. Teal = actie, groen = status, oranje = bevestigen (semantiek-regel designpass v2). */

export type GbBron = 'geheugen' | 'geheugen_seed' | 'geheugen_conflict' | 'ai'

export type BtwBron = 'factuur' | 'standaard'

export interface RegelChip {
  /** CSS-klassen naast `chip` — `ok` (groen), `afwijking` (oranje), `handmatig` (neutraal grijs). */
  klasse: 'ok' | 'afwijking' | 'handmatig'
  tekst: string
  titel: string
}

const GB_BRONNEN: ReadonlySet<string> = new Set<GbBron>(['geheugen', 'geheugen_seed', 'geheugen_conflict', 'ai'])

/** Server-waarde → gevalideerde bron; onbekende/lege waarden tellen als "geen voorstel". */
export function gbBronUitDto(waarde: string | null | undefined): GbBron | null {
  return waarde && GB_BRONNEN.has(waarde) ? (waarde as GbBron) : null
}

export function btwBronUitDto(waarde: string | null | undefined, taxrateId: string | null): BtwBron | null {
  if (!taxrateId) return null
  return waarde === 'factuur' || waarde === 'standaard' ? waarde : null
}

/** Chip-besluit voor het grootboek-veld: alleen zolang het voorstel nog in het veld staat én de mens het
 * veld niet zelf heeft aangeraakt (zelfde regel als de btw-chip "uit factuur"). */
export function bepaalGbChip(
  bron: GbBron | null,
  detail: string | null,
  huidigLedgerId: string | null,
  handmatig: boolean,
): RegelChip | null {
  if (!bron || !huidigLedgerId || handmatig) return null
  const toelichting = detail ? ` ${detail}.` : ''
  switch (bron) {
    case 'geheugen':
      return {
        klasse: 'ok',
        tekst: 'uit geheugen',
        titel: `Deterministisch regel-geheugen: deze omschrijving is bij deze leverancier eerder zo geboekt en door een mens bevestigd.${toelichting} De harde checks blijven de poort.`,
      }
    case 'geheugen_seed':
      return {
        klasse: 'afwijking',
        tekst: 'uit historie, nog niet bevestigd',
        titel: `Regel-geheugen uit de Reeleezee-historie — nog niet in de app bevestigd.${toelichting} Bevestigen (boeken) maakt 'm voortaan groen.`,
      }
    case 'geheugen_conflict':
      return {
        klasse: 'afwijking',
        tekst: 'geheugen wisselend — controleer',
        titel: `Deze omschrijving is bij deze leverancier op verschillende grootboeken geboekt; de jongste keuze staat vooringevuld.${toelichting}`,
      }
    case 'ai':
      return {
        klasse: 'afwijking',
        tekst: 'AI-voorstel — bevestig',
        titel: `AI-classificatie tegen de grootboeken die deze leverancier eerder gebruikte — een voorstel, geen geheugen.${toelichting} Bevestigen (boeken) of corrigeren leert het regel-geheugen; daarna is dezelfde omschrijving groen.`,
      }
  }
}

/** Chip-besluit voor de btw-default van de administratie (blok E). De factuur-chip blijft in het paneel
 * zelf (percentage in de tekst). */
export function bepaalBtwStandaardChip(bron: BtwBron | null, huidigTaxrateId: string | null, handmatig: boolean): RegelChip | null {
  if (bron !== 'standaard' || !huidigTaxrateId || handmatig) return null
  return {
    klasse: 'handmatig',
    tekst: 'standaard administratie',
    titel:
      'Standaard btw-voorstel van deze administratie (Instellingen › Boeken & AI) — vult alleen regels waar factuur en leverancier-geheugen niets opleveren. Controleer; de harde checks blijven de poort.',
  }
}
